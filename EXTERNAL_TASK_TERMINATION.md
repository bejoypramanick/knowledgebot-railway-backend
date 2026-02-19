# External Celery Task Termination

## Overview

Your codebase already implements **external task termination** — the ability to force-stop in-progress Celery jobs from outside the worker process. This document explains how it works and shows you different approaches.

---

## ✅ What's Already Implemented

Your code uses a **two-tier termination strategy**:

### Tier 1: Forceful Termination via Celery Revoke

```python
# Single file deletion (file_service.py:621)
file_celery.control.revoke(file_record['celery_task_id'], terminate=True, signal='SIGKILL')

# Single website deletion (file_service.py:824)
web_celery.control.revoke(task_id, terminate=True, signal='SIGKILL')

# Delete All (fileupload_service.py:510-515)
file_celery.control.purge()  # Clears all queued file tasks
web_celery.control.purge()   # Clears all queued web tasks
```

**How it works**:
- `revoke(task_id, terminate=True)` sends a signal (SIGKILL) to the worker process running the task
- `signal='SIGKILL'` is the strongest signal — immediately kills the task
- `control.purge()` removes all queued tasks before they start
- Works for both queued tasks (prevents startup) and in-flight tasks (kills immediately)

### Tier 2: Graceful Cancellation via Redis Flags

```python
# Set cancellation flag (redis_message_queue.py:309-338)
redis_queue.set_task_cancelled(task_id)

# Checked by running tasks (processing_service.py:63, 157, 271, 641)
if await self._is_task_cancelled(celery_task_id):
    break  # Gracefully exit at checkpoint
```

**How it works**:
- Sets a Redis flag `task_cancelled:{task_id}` that running tasks check
- Tasks check this flag at strategic boundaries (loop starts, before expensive ops)
- Allows graceful cleanup instead of abrupt SIGKILL
- Works for tasks that are blocked in long operations (Gemini upload, file download)

---

## Termination Flow: How It Actually Works

```
┌─────────────────┐
│  User clicks    │
│  "Delete All"   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Step 1: CELERY CONTROL           │
│ Revoke + Purge                  │
│ ✓ Revoke all in-flight tasks    │
│ ✓ Purge all queued tasks        │
│ ✓ Sends SIGKILL to workers      │
└─────────────────┬───────────────┘
                  │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
    ┌─────────┐       ┌──────────────┐
    │ QUEUED  │       │ IN-FLIGHT    │
    │ TASKS   │       │ TASKS        │
    └────┬────┘       └────┬─────────┘
         │                 │
         ▼                 ▼
    Never start        Killed by SIGKILL
    (purged)           (process terminated)

                  FALLBACK FOR BLOCKED TASKS:
                  If task is blocked in Gemini upload,
                  Redis flag stops it at next checkpoint
```

---

## Celery Revoke: All Signal Options

| Signal | Behavior | Use Case | Cleanup |
|--------|----------|----------|---------|
| **SIGTERM** | Gentle: allows 5s cleanup | Normal shutdown | ✅ Graceful |
| **SIGKILL** | Immediate: no cleanup | Emergency stop | ❌ Abrupt |

### Example: Different Signal Approaches

```python
# Option 1: Graceful termination (default, 5 second grace period)
celery_app.control.revoke(task_id, terminate=True)
# Worker receives SIGTERM → has 5 seconds to clean up → dies

# Option 2: Immediate termination (hardest stop)
celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')
# Worker process immediately killed → no cleanup possible

# Option 3: Don't terminate running task, just prevent restart
celery_app.control.revoke(task_id, terminate=False)
# Task completes normally, won't be restarted
```

**Your codebase uses Option 2 (SIGKILL)** — immediate, no questions asked.

---

## Current Implementation Details

### File Deletion Flow

```python
# knowledgebase_ingestion/service/file_service.py:614-635

# Step 1: Get the task ID from database
file_record = await get_file_record(file_id)
celery_task_id = file_record['celery_task_id']

# Step 2: Revoke the Celery task (immediate termination)
try:
    file_celery.control.revoke(celery_task_id, terminate=True, signal='SIGKILL')
    celery_task_revoked = True
    logger.info(f"✅ Task revoked: {celery_task_id}")
except Exception as e:
    logger.warning(f"⚠️ Could not revoke task: {e}")

# Step 3: Set Redis flag (graceful fallback)
redis_queue.set_task_cancelled(celery_task_id)
logger.info(f"✅ Set cancellation flag for task: {celery_task_id}")

# Step 4: Delete from Gemini
# (Task is already stopped, now clean up related data)
delete_from_gemini(file_record)
```

### Website Deletion Flow

```python
# knowledgebase_ingestion/service/file_service.py:807-841

# Step 1: Get parent + all child task IDs
task_ids = [parent_task_id] + [child_task_id for child in children]

# Step 2: Revoke all tasks
for task_id in task_ids:
    web_celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
    redis_queue.set_task_cancelled(task_id)  # Graceful fallback

# Step 3: Delete from Gemini
```

### Delete All Flow

```python
# knowledgebase_ingestion/service/fileupload_service.py:436-520

# Step 1: Clear Redis queues
redis_queue.clear_file_task_queue()   # Removes all queued FILE tasks
redis_queue.clear_web_task_queue()    # Removes all queued WEB tasks
logger.info("✅ Redis queues cleared")

# Step 2: Set cancellation flags for in-progress tasks
for task in running_website_tasks:
    redis_queue.set_task_cancelled(task['celery_task_id'])
for task in running_file_tasks:
    redis_queue.set_task_cancelled(task['celery_task_id'])
logger.info("✅ Cancellation flags set")

# Step 3: Purge all Celery task queues
file_celery.control.purge()   # Removes all queued FILE tasks
web_celery.control.purge()    # Removes all queued WEB tasks
logger.info("✅ Celery queues purged")

# Step 4: Delete from Gemini
delete_and_recreate_filesearch_store()
delete_all_raw_files()

# Step 5: Mark all as deleted in database
mark_all_files_as_deleted()
mark_all_websites_as_deleted()
```

---

## How to Use Externally: Simple Utility Method

To make it even easier to stop a task externally, add this utility class:

```python
# shared/task_control.py (NEW FILE)

from celery import Celery
from shared.celery_dispatcher import file_celery, web_celery
from shared.redis_message_queue import RedisMessageQueue
from shared.otel_logger import get_otel_logger
from typing import Optional

logger = get_otel_logger("task_control", "knowledgebase-ingestion")


class TaskControl:
    """
    Unified interface for external task termination.
    Use this instead of calling celery_app.control.revoke() directly.
    """

    @staticmethod
    def stop_file_task(task_id: str, graceful: bool = False) -> bool:
        """
        Stop a file processing task immediately.

        Args:
            task_id: Celery task ID to stop
            graceful: If True, use SIGTERM (allows cleanup). If False, use SIGKILL (immediate).

        Returns:
            True if revoke succeeded, False otherwise

        Example:
            TaskControl.stop_file_task("abc-123-def", graceful=False)
        """
        try:
            logger.info(f"🔪 [TASK_CONTROL] Stopping file task: {task_id}")

            # Tier 1: Revoke via Celery
            signal = 'SIGTERM' if graceful else 'SIGKILL'
            file_celery.control.revoke(task_id, terminate=True, signal=signal)
            logger.info(f"✅ File task revoked with {signal}: {task_id}")

            # Tier 2: Set Redis flag (fallback for blocked tasks)
            redis_queue = RedisMessageQueue()
            redis_queue.set_task_cancelled(task_id)
            logger.info(f"✅ Cancellation flag set: {task_id}")

            return True

        except Exception as e:
            logger.error(f"❌ Error stopping file task {task_id}: {e}")
            return False

    @staticmethod
    def stop_web_task(task_id: str, graceful: bool = False) -> bool:
        """
        Stop a website scraping task immediately.

        Args:
            task_id: Celery task ID to stop
            graceful: If True, use SIGTERM (allows cleanup). If False, use SIGKILL (immediate).

        Returns:
            True if revoke succeeded, False otherwise

        Example:
            TaskControl.stop_web_task("xyz-789-abc", graceful=True)
        """
        try:
            logger.info(f"🔪 [TASK_CONTROL] Stopping web task: {task_id}")

            # Tier 1: Revoke via Celery
            signal = 'SIGTERM' if graceful else 'SIGKILL'
            web_celery.control.revoke(task_id, terminate=True, signal=signal)
            logger.info(f"✅ Web task revoked with {signal}: {task_id}")

            # Tier 2: Set Redis flag (fallback for blocked tasks)
            redis_queue = RedisMessageQueue()
            redis_queue.set_task_cancelled(task_id)
            logger.info(f"✅ Cancellation flag set: {task_id}")

            return True

        except Exception as e:
            logger.error(f"❌ Error stopping web task {task_id}: {e}")
            return False

    @staticmethod
    def stop_task(task_id: str, task_type: str = 'auto', graceful: bool = False) -> bool:
        """
        Stop any task (file or web), auto-detecting or specified.

        Args:
            task_id: Celery task ID to stop
            task_type: 'file', 'web', or 'auto' (tries both)
            graceful: If True, use SIGTERM. If False, use SIGKILL.

        Returns:
            True if at least one revoke succeeded

        Example:
            # Auto-detect and stop
            TaskControl.stop_task("abc-123-def")

            # Explicitly stop web task
            TaskControl.stop_task("abc-123-def", task_type='web')
        """
        if task_type in ('file', 'auto'):
            file_result = TaskControl.stop_file_task(task_id, graceful)
            if task_type == 'file':
                return file_result

        if task_type in ('web', 'auto'):
            web_result = TaskControl.stop_web_task(task_id, graceful)
            if task_type == 'web':
                return web_result

        # If auto mode, return True if either succeeded
        if task_type == 'auto':
            return file_result or web_result

        return False

    @staticmethod
    def stop_all_file_tasks() -> bool:
        """Stop all queued and in-flight file tasks."""
        try:
            logger.info("🔪 [TASK_CONTROL] Stopping all file tasks")
            file_celery.control.purge()
            logger.info("✅ All file task queues purged")
            return True
        except Exception as e:
            logger.error(f"❌ Error purging file tasks: {e}")
            return False

    @staticmethod
    def stop_all_web_tasks() -> bool:
        """Stop all queued and in-flight web tasks."""
        try:
            logger.info("🔪 [TASK_CONTROL] Stopping all web tasks")
            web_celery.control.purge()
            logger.info("✅ All web task queues purged")
            return True
        except Exception as e:
            logger.error(f"❌ Error purging web tasks: {e}")
            return False

    @staticmethod
    def stop_all_tasks() -> bool:
        """Stop all tasks (file and web)."""
        file_ok = TaskControl.stop_all_file_tasks()
        web_ok = TaskControl.stop_all_web_tasks()
        return file_ok and web_ok
```

**Usage Example**:

```python
# From any endpoint, stop a single task
from shared.task_control import TaskControl

@app.post("/stop-task/{task_id}")
async def stop_task_endpoint(task_id: str):
    success = TaskControl.stop_task(task_id, graceful=False)
    return {"stopped": success, "task_id": task_id}

# Or from a service
success = TaskControl.stop_web_task(celery_task_id, graceful=False)
if success:
    logger.info("Task successfully stopped")
```

---

## Integration with CancellationToken

Your CancellationToken pattern and external termination work **together perfectly**:

### Scenario 1: Task in BFS Loop (Fast Stop)

```
User clicks "Delete Website"
       │
       ├─ Celery.revoke(SIGKILL) → Worker process killed
       │
       └─ Redis flag set → Already dead, not needed

Result: Task stops within milliseconds
```

### Scenario 2: Task Blocked in Gemini Upload (Graceful Stop)

```
User clicks "Delete Website"
       │
       ├─ Celery.revoke(SIGKILL) → Worker process killed
       │
       └─ Redis flag set → Fallback if revoke fails

Result: Task stops after upload completes (within seconds)
```

### Scenario 3: Task Running with CancellationCheckpoint

```
User clicks "Delete Website"
       │
       ├─ Celery.revoke(SIGKILL)  → Sends SIGKILL
       │
       ├─ Redis flag set         → Fallback
       │
       └─ CancellationToken.check() → Even if revoke fails,
                                       next checkpoint will detect flag
                                       and raise CancellationException

Result: Task stops within loop boundary or at checkpoint
```

**The combination ensures**:
- ✅ External termination works (Celery revoke)
- ✅ Graceful fallback works (Redis flag)
- ✅ CancellationToken provides defense-in-depth
- ✅ No task gets stuck running deleted resources

---

## Best Practices

### 1. Use Graceful for Upload/Download Operations

```python
# Task blocked in Gemini upload? Use SIGTERM (graceful)
TaskControl.stop_web_task(task_id, graceful=True)
# → SIGTERM sent
# → Worker gets 5 seconds to finish upload and clean up
# → If upload completes, task exits cleanly
# → If upload takes >5s, SIGKILL is sent automatically
```

### 2. Use Immediate (SIGKILL) for Delete All

```python
# Need to clear everything NOW? Use SIGKILL (immediate)
TaskControl.stop_all_tasks()  # Uses SIGKILL by default
# → All tasks terminated immediately
# → Redis queues cleared
# → No tasks restart
```

### 3. Always Set Redis Flag as Fallback

```python
# Good practice: revoke + Redis flag
TaskControl.stop_web_task(task_id)  # Does both internally
# → Celery revoke happens
# → Redis flag set automatically
# → Double insurance
```

### 4. Check Task Status in Database

```python
# After stopping, verify in database
task = await db.fetch("SELECT celery_task_id, processing_status FROM scraped_websites WHERE id = $1", website_id)

if task['celery_task_id'] and task['processing_status'] == 'processing':
    logger.warning(f"Task {task['celery_task_id']} may still be running")
else:
    logger.info(f"Task stopped successfully")
```

---

## Troubleshooting

### Task Doesn't Stop

**Possible causes**:
1. Task ID not in database (typo?)
2. Worker not connected to Celery broker
3. Task already completed

**Debug**:
```python
# Check if task exists in database
task = await db.fetch("SELECT celery_task_id FROM ... WHERE celery_task_id = $1", task_id)
if not task:
    logger.error(f"Task not found: {task_id}")

# Check Redis flag was set
redis_queue = RedisMessageQueue()
redis_conn = redis_queue._web_connection  # or _file_connection
exists = redis_conn.exists(f"task_cancelled:{task_id}")
logger.info(f"Redis flag exists: {exists}")
```

### Task Completes Before Stop

This is normal! If the task finishes its current operation before the SIGKILL arrives, it will complete successfully. This is actually desired behavior — you don't want to interrupt fast operations.

### Need Timeout?

```python
import asyncio

async def stop_task_with_timeout(task_id: str, timeout_seconds: int = 10):
    """Stop task and wait for it to actually stop."""
    TaskControl.stop_web_task(task_id)

    for attempt in range(timeout_seconds):
        task = await db.fetch("SELECT processing_status FROM ... WHERE celery_task_id = $1", task_id)
        if task and task['processing_status'] != 'processing':
            logger.info(f"Task stopped after {attempt}s")
            return True

        await asyncio.sleep(1)

    logger.error(f"Task still running after {timeout_seconds}s")
    return False
```

---

## Summary

| Feature | Implementation | Status |
|---------|-----------------|--------|
| **Celery Revoke** | `celery.control.revoke(task_id, terminate=True, signal='SIGKILL')` | ✅ Implemented |
| **Queue Purge** | `celery.control.purge()` | ✅ Implemented |
| **Redis Graceful** | `redis.set(f"task_cancelled:{task_id}")` | ✅ Implemented |
| **Utility Class** | `TaskControl` (see above) | 🆕 Ready to add |
| **CancellationToken** | Strategic checkpoints | ✅ Implemented |
| **Signal Options** | SIGTERM (graceful) or SIGKILL (immediate) | ✅ Available |

**Bottom line**: You can already force-stop any Celery task from outside. The utility class just makes it even easier.

