# External Task Termination - Usage Examples

## Quick Start

### Example 1: Stop a Single File Upload Task

```python
from shared.task_control import TaskControl

# Stop the task
success = TaskControl.stop_file_task("abc-123-def-456")

if success:
    print("✅ File upload task stopped")
else:
    print("❌ Failed to stop file upload task")
```

### Example 2: Stop a Single Website Scraping Task

```python
from shared.task_control import TaskControl

# Stop the task
success = TaskControl.stop_web_task("xyz-789-ghi-012")

if success:
    print("✅ Website scraping task stopped")
else:
    print("❌ Failed to stop website scraping task")
```

### Example 3: Stop a Task Without Knowing Type

```python
from shared.task_control import TaskControl

# Auto-detect if file or web task
success = TaskControl.stop_task("some-task-id")  # Tries both file and web

if success:
    print("✅ Task stopped (either file or web)")
```

### Example 4: Graceful vs Immediate Stop

```python
from shared.task_control import TaskControl

# Graceful stop (SIGTERM - allows cleanup)
# Use this if task is blocked in a long operation (upload, download)
success = TaskControl.stop_web_task(task_id, graceful=True)
# Task gets 5 seconds to clean up before being killed

# Immediate stop (SIGKILL - no cleanup)
# Use this for emergency shutdown
success = TaskControl.stop_web_task(task_id, graceful=False)
# Task is killed instantly, no cleanup
```

---

## Real-World Scenarios

### Scenario 1: Stop All Knowledge Base Tasks (Delete All)

```python
# This is what delete_all_knowledge() does internally

from shared.task_control import TaskControl
from shared.redis_message_queue import RedisMessageQueue

async def delete_all_knowledge():
    """Clear everything from knowledge base"""

    logger.info("🗑️ [DELETE_ALL] Starting knowledge base deletion...")

    # Step 1: Stop all Celery tasks
    TaskControl.stop_all_tasks()

    # Step 2: Clear Redis queues
    redis_queue = RedisMessageQueue()
    redis_queue.clear_file_task_queue()
    redis_queue.clear_web_task_queue()

    # Step 3: Delete from Gemini
    # ... rest of deletion logic ...

    logger.info("✅ [DELETE_ALL] Knowledge base cleared")
    return {"success": True}
```

### Scenario 2: Stop a Single File When User Deletes It

```python
# This is what delete_file_logic() does internally

from shared.task_control import TaskControl

async def delete_file_logic(file_id: int):
    """Delete a single file and stop its processing task"""

    # Get the file and its task ID
    file_record = await get_file_record(file_id)
    celery_task_id = file_record['celery_task_id']

    # Stop the task
    if celery_task_id:
        TaskControl.stop_file_task(celery_task_id)

    # Delete from Gemini
    delete_from_gemini(file_record)

    # Mark as deleted in database
    await mark_file_as_deleted(file_id)

    logger.info(f"✅ File {file_id} deleted and task stopped")
```

### Scenario 3: Stop a Website and All Its Child Pages

```python
# This is what delete_website_logic() does internally

from shared.task_control import TaskControl

async def delete_website_logic(website_id: int):
    """Delete a website and stop all its scraping tasks"""

    # Get the website and all child pages
    website = await get_website_record(website_id)
    children = await get_child_pages(website_id)

    # Collect all task IDs
    task_ids = [website['celery_task_id']]
    for child in children:
        if child['celery_task_id']:
            task_ids.append(child['celery_task_id'])

    # Stop all tasks
    for task_id in task_ids:
        TaskControl.stop_web_task(task_id)

    # Delete from Gemini
    delete_from_filesearch(website, children)

    # Mark as deleted in database
    await mark_website_as_deleted(website_id)
    await mark_children_as_deleted(website_id)

    logger.info(f"✅ Website {website_id} deleted with {len(task_ids)} tasks stopped")
```

---

## API Endpoints Using TaskControl

### Example: Stop Any Task Endpoint

```python
# knowledgebase_ingestion/routers/task_router.py (NEW FILE)

from fastapi import APIRouter, HTTPException
from shared.task_control import TaskControl
from shared.otel_logger import get_otel_logger

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = get_otel_logger("task_router", "knowledgebase-ingestion")


@router.post("/stop/{task_id}")
async def stop_task_endpoint(
    task_id: str,
    task_type: str = "auto",
    graceful: bool = False
):
    """
    Stop a Celery task externally.

    Args:
        task_id: Celery task ID to stop
        task_type: 'file', 'web', or 'auto'
        graceful: True for SIGTERM, False for SIGKILL

    Example:
        POST /api/v1/tasks/stop/abc-123-def-456

    Response:
        {
            "success": true,
            "task_id": "abc-123-def-456",
            "task_type": "auto",
            "graceful": false,
            "message": "Task stopped successfully"
        }
    """
    try:
        logger.info(f"🔪 Stopping task: {task_id}")

        success = TaskControl.stop_task(
            task_id=task_id,
            task_type=task_type,
            graceful=graceful
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop task {task_id}"
            )

        return {
            "success": True,
            "task_id": task_id,
            "task_type": task_type,
            "graceful": graceful,
            "message": "Task stopped successfully"
        }

    except Exception as e:
        logger.error(f"❌ Error stopping task {task_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.post("/stop-all")
async def stop_all_tasks_endpoint():
    """
    Stop all Celery tasks immediately (emergency shutdown).

    Example:
        POST /api/v1/tasks/stop-all

    Response:
        {
            "success": true,
            "message": "All tasks stopped successfully",
            "details": {
                "file_tasks_stopped": true,
                "web_tasks_stopped": true
            }
        }
    """
    try:
        logger.warning("🔴 STOPPING ALL TASKS - EMERGENCY SHUTDOWN")

        success = TaskControl.stop_all_tasks()

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to stop all tasks"
            )

        return {
            "success": True,
            "message": "All tasks stopped successfully",
            "details": {
                "file_tasks_stopped": True,
                "web_tasks_stopped": True
            }
        }

    except Exception as e:
        logger.error(f"❌ Error stopping all tasks: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/status")
async def task_control_status():
    """
    Get current task control status and queue information.

    Example:
        GET /api/v1/tasks/status

    Response:
        {
            "file_redis_available": true,
            "web_redis_available": true,
            "file_task_queue_length": 5,
            "web_task_queue_length": 3,
            "message": "Task control is operational"
        }
    """
    try:
        status = TaskControl.status_summary()
        return status
    except Exception as e:
        logger.error(f"❌ Error getting task status: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
```

**Register the router in main FastAPI app**:

```python
# knowledgebase_ingestion/main.py

from knowledgebase_ingestion.routers.task_router import router as task_router

app.include_router(task_router)
```

---

## CLI Usage (For Server Debugging)

If you have command-line access to the server, you can stop tasks directly:

```bash
# Connect to Python REPL on the server
python3

# Then in Python:
from shared.task_control import TaskControl

# Stop a specific task
TaskControl.stop_web_task("abc-123-def-456")

# Stop all tasks
TaskControl.stop_all_tasks()

# Check status
status = TaskControl.status_summary()
print(status)
```

---

## Integration with Existing Delete Endpoints

### Current file deletion already uses TaskControl pattern:

```python
# knowledgebase_ingestion/service/file_service.py (existing code)

if file_record['celery_task_id']:
    try:
        # This is exactly what TaskControl does internally
        file_celery.control.revoke(
            file_record['celery_task_id'],
            terminate=True,
            signal='SIGKILL'
        )
        celery_task_revoked = True
    except Exception as e:
        logger.warning(f"Could not revoke task: {e}")
```

### Simplified with TaskControl:

```python
# knowledgebase_ingestion/service/file_service.py (refactored)

if file_record['celery_task_id']:
    TaskControl.stop_file_task(file_record['celery_task_id'])
    # That's it! Two-tier termination + logging handled automatically
```

---

## Testing Task Termination

### Unit Test Example

```python
# tests/test_task_control.py

import pytest
from shared.task_control import TaskControl
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_stop_web_task():
    """Test stopping a web task"""
    task_id = "test-task-123"

    with patch('shared.task_control.web_celery') as mock_celery:
        with patch('shared.task_control.RedisMessageQueue') as mock_redis:
            mock_celery.control.revoke = MagicMock()
            mock_redis_instance = MagicMock()
            mock_redis.return_value = mock_redis_instance

            # Stop the task
            result = TaskControl.stop_web_task(task_id)

            # Verify Celery revoke was called
            mock_celery.control.revoke.assert_called_once_with(
                task_id,
                terminate=True,
                signal='SIGKILL'
            )

            # Verify Redis flag was set
            mock_redis_instance.set_task_cancelled.assert_called_once_with(task_id)

            # Verify success
            assert result is True


@pytest.mark.asyncio
async def test_stop_all_tasks():
    """Test stopping all tasks"""
    with patch('shared.task_control.file_celery') as mock_file_celery:
        with patch('shared.task_control.web_celery') as mock_web_celery:
            mock_file_celery.control.purge = MagicMock()
            mock_web_celery.control.purge = MagicMock()

            # Stop all tasks
            result = TaskControl.stop_all_tasks()

            # Verify both purges were called
            mock_file_celery.control.purge.assert_called_once()
            mock_web_celery.control.purge.assert_called_once()

            # Verify success
            assert result is True
```

### Integration Test Example

```python
@pytest.mark.asyncio
async def test_delete_file_stops_task():
    """Test that deleting a file actually stops its Celery task"""

    # Create a file
    file_id = await upload_test_file()
    file_record = await get_file_record(file_id)
    celery_task_id = file_record['celery_task_id']

    # Verify task is processing
    assert file_record['processing_status'] == 'processing'

    # Delete the file
    result = await delete_file_logic(file_id)

    # Verify file was deleted
    assert result['success'] is True

    # Verify task was stopped
    # (Task ID in Redis cancellation flags)
    redis_queue = RedisMessageQueue()
    flag_exists = redis_queue._web_connection.exists(f"task_cancelled:{celery_task_id}")
    assert flag_exists is True  # Flag was set
```

---

## Best Practices Summary

| Scenario | Method | Graceful | Notes |
|----------|--------|----------|-------|
| Delete single file | `stop_file_task()` | ❌ No | Immediate kill |
| Delete single website | `stop_web_task()` | ❌ No | Immediate kill |
| Delete All | `stop_all_tasks()` | ❌ No | Clear everything |
| Pause task | `stop_web_task()` | ✅ Yes | Allow cleanup |
| Emergency stop | `stop_web_task()` | ❌ No | SIGKILL |
| Queue check | `status_summary()` | N/A | Read-only |

---

## Troubleshooting

### Task Doesn't Stop

Check logs:
```python
from shared.task_control import TaskControl
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("debug", "knowledgebase-ingestion")

# Try to stop
success = TaskControl.stop_web_task(task_id)

# Check Redis flag was set
from shared.redis_message_queue import RedisMessageQueue
redis_queue = RedisMessageQueue()
flag = redis_queue._web_connection.get(f"task_cancelled:{task_id}")
logger.info(f"Redis flag set: {flag}")

# Check Celery connection
status = TaskControl.status_summary()
logger.info(f"Status: {status}")
```

### Task Already Completed

This is normal! If the task finishes before the revoke signal arrives, it completes successfully.

Check database:
```python
task = await db.fetch(
    "SELECT processing_status FROM ... WHERE celery_task_id = $1",
    task_id
)
print(f"Task status: {task['processing_status']}")
# If not 'processing', task already finished
```

---

## Summary

With `TaskControl`, you can:

✅ Stop any Celery task externally
✅ Choose graceful (SIGTERM) or immediate (SIGKILL) stop
✅ Stop all tasks at once
✅ Check task queue status
✅ Two-tier termination (Celery + Redis fallback)
✅ Full logging and error handling

Just import and use:
```python
from shared.task_control import TaskControl

TaskControl.stop_web_task(task_id)  # That's it!
```

