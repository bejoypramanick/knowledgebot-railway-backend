# Task Control API Reference

Quick reference for all external task termination endpoints.

---

## Base URL
```
http://localhost:8001/api/v1/tasks
```

Or in production (through API Gateway):
```
http://api-gateway:8000/api/v1/tasks
```

---

## Endpoints

### 1. Stop Any Task

**Endpoint:** `POST /stop/{task_id}`

**Description:** Stop a Celery task (file or web, auto-detected)

**Parameters:**
- `task_id` (path): Celery task ID to stop
- `task_type` (query, optional): `'auto'` | `'file'` | `'web'` (default: `'auto'`)
- `graceful` (query, optional): `true` (SIGTERM) | `false` (SIGKILL) (default: `false`)

**Response:**
```json
{
  "success": true,
  "task_id": "abc-123-def-456",
  "task_type": "auto",
  "graceful": false,
  "signal": "SIGKILL",
  "message": "Task stopped successfully"
}
```

**Examples:**
```bash
# Stop immediately (SIGKILL)
curl -X POST http://localhost:8001/api/v1/tasks/stop/abc-123-def-456

# Stop with cleanup time (SIGTERM, graceful=true)
curl -X POST http://localhost:8001/api/v1/tasks/stop/abc-123-def-456?graceful=true

# Explicitly stop as web task
curl -X POST http://localhost:8001/api/v1/tasks/stop/abc-123-def-456?task_type=web
```

---

### 2. Stop File Task

**Endpoint:** `POST /stop/file/{task_id}`

**Description:** Stop a file processing task specifically

**Parameters:**
- `task_id` (path): File processing task ID
- `graceful` (query, optional): `true` | `false` (default: `false`)

**Response:**
```json
{
  "success": true,
  "task_id": "file-task-123",
  "task_type": "file",
  "signal": "SIGKILL",
  "message": "File task stopped successfully"
}
```

**Examples:**
```bash
# Stop file task immediately
curl -X POST http://localhost:8001/api/v1/tasks/stop/file/task-id-123

# Stop file task gracefully
curl -X POST http://localhost:8001/api/v1/tasks/stop/file/task-id-123?graceful=true
```

---

### 3. Stop Web Task

**Endpoint:** `POST /stop/web/{task_id}`

**Description:** Stop a website scraping task specifically

**Parameters:**
- `task_id` (path): Web scraping task ID
- `graceful` (query, optional): `true` | `false` (default: `false`)

**Response:**
```json
{
  "success": true,
  "task_id": "web-task-789",
  "task_type": "web",
  "signal": "SIGKILL",
  "message": "Web task stopped successfully"
}
```

**Examples:**
```bash
# Stop web task immediately
curl -X POST http://localhost:8001/api/v1/tasks/stop/web/task-id-789

# Stop web task gracefully (let it clean up)
curl -X POST http://localhost:8001/api/v1/tasks/stop/web/task-id-789?graceful=true
```

---

### 4. Stop All Tasks (Emergency)

**Endpoint:** `POST /stop-all`

**Description:** Emergency shutdown - stops ALL queued and in-progress tasks

⚠️ **WARNING**: This terminates everything immediately!

**Parameters:**
- `confirm` (query, required): Must be `true` to execute (safety check)

**Response:**
```json
{
  "success": true,
  "message": "All tasks stopped successfully",
  "file_tasks_stopped": true,
  "web_tasks_stopped": true,
  "warning": "All in-progress and queued tasks have been terminated"
}
```

**Examples:**
```bash
# Stop all tasks (must have confirm=true)
curl -X POST http://localhost:8001/api/v1/tasks/stop-all?confirm=true

# Without confirm parameter (will fail)
curl -X POST http://localhost:8001/api/v1/tasks/stop-all
# Response: 400 error - Must confirm with ?confirm=true
```

---

### 5. Get Task Status

**Endpoint:** `GET /status`

**Description:** Get current task control status and queue information

**Parameters:** None

**Response:**
```json
{
  "file_redis_available": true,
  "web_redis_available": true,
  "file_task_queue_length": 5,
  "web_task_queue_length": 3,
  "message": "Task control is operational"
}
```

**Examples:**
```bash
# Get current status
curl -X GET http://localhost:8001/api/v1/tasks/status
```

---

### 6. Health Check

**Endpoint:** `POST /health-check`

**Description:** Health check for task control system

**Parameters:** None

**Response:**
```json
{
  "healthy": true,
  "file_redis_connected": true,
  "web_redis_connected": true,
  "message": "Task control system is operational"
}
```

**Examples:**
```bash
# Check if task control is healthy
curl -X POST http://localhost:8001/api/v1/tasks/health-check
```

---

## Signal Types

| Signal | Type | Behavior | Cleanup |
|--------|------|----------|---------|
| **SIGKILL** (graceful=false) | Forceful | Task killed immediately | ❌ None |
| **SIGTERM** (graceful=true) | Graceful | Task gets ~5s to clean up | ✅ Allowed |

**When to use:**
- **SIGKILL** (immediate): Emergency shutdown, task hangs, need instant stop
- **SIGTERM** (graceful): Normal cancellation, allow cleanup, task blocked in operation

---

## Error Responses

### Task Not Found / Revoke Failed

**Status:** 500

```json
{
  "detail": "Failed to stop task {task_id}"
}
```

### Missing Confirmation (stop-all)

**Status:** 400

```json
{
  "detail": "Must confirm with ?confirm=true to stop all tasks"
}
```

### Redis Unavailable

**Status:** 500

```json
{
  "detail": "Error stopping task: Redis connection failed"
}
```

---

## Python Examples

### Using requests library

```python
import requests

BASE_URL = "http://localhost:8001/api/v1/tasks"

# Stop a single task
def stop_task(task_id):
    response = requests.post(f"{BASE_URL}/stop/{task_id}")
    return response.json()

# Stop all tasks
def stop_all_tasks():
    response = requests.post(f"{BASE_URL}/stop-all?confirm=true")
    return response.json()

# Get status
def get_task_status():
    response = requests.get(f"{BASE_URL}/status")
    return response.json()

# Examples
result = stop_task("abc-123-def-456")
print(f"Stopped: {result['success']}")

status = get_task_status()
print(f"File queue length: {status['file_task_queue_length']}")
```

### Using httpx (async)

```python
import httpx

BASE_URL = "http://localhost:8001/api/v1/tasks"

async def stop_task(task_id):
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/stop/{task_id}")
        return response.json()

async def stop_all_tasks():
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/stop-all?confirm=true")
        return response.json()

# Usage
result = await stop_task("abc-123-def-456")
```

---

## Integration Examples

### Delete File and Stop Its Task

```python
from fastapi import APIRouter
import httpx

router = APIRouter()

@router.delete("/files/{file_id}")
async def delete_file(file_id: int):
    # Get file record
    file_record = await db.fetch("SELECT * FROM file_uploads WHERE id = $1", file_id)

    if not file_record:
        return {"error": "File not found"}

    # Stop the Celery task
    if file_record['celery_task_id']:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"http://localhost:8001/api/v1/tasks/stop/{file_record['celery_task_id']}"
            )

    # Delete from Gemini
    # ... deletion logic ...

    # Mark as deleted in DB
    await db.execute("UPDATE file_uploads SET status = 'deleted' WHERE id = $1", file_id)

    return {"success": True, "file_id": file_id}
```

### Monitoring Task Queue

```python
import httpx
import asyncio

async def monitor_queues():
    """Monitor task queue lengths periodically"""
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get("http://localhost:8001/api/v1/tasks/status")
            status = response.json()

            print(f"File tasks: {status['file_task_queue_length']}")
            print(f"Web tasks: {status['web_task_queue_length']}")

            await asyncio.sleep(5)

# Run in background
asyncio.create_task(monitor_queues())
```

---

## Testing

### Using curl

```bash
# 1. Check initial status
curl -X GET http://localhost:8001/api/v1/tasks/status

# 2. Start a task (from another endpoint)
# ... start file upload or web crawl ...

# 3. Get status again
curl -X GET http://localhost:8001/api/v1/tasks/status

# 4. Stop the task
curl -X POST http://localhost:8001/api/v1/tasks/stop/TASK_ID_HERE

# 5. Verify it stopped
curl -X GET http://localhost:8001/api/v1/tasks/status
```

### Using pytest

```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_stop_task():
    async with httpx.AsyncClient() as client:
        # Stop a non-existent task (should fail gracefully)
        response = await client.post(
            "http://localhost:8001/api/v1/tasks/stop/fake-task-id"
        )
        # Response depends on whether worker is running
        assert response.status_code in [200, 500]

@pytest.mark.asyncio
async def test_stop_all_requires_confirmation():
    async with httpx.AsyncClient() as client:
        # Without confirmation
        response = await client.post(
            "http://localhost:8001/api/v1/tasks/stop-all"
        )
        assert response.status_code == 400
        assert "confirm=true" in response.text

@pytest.mark.asyncio
async def test_get_status():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8001/api/v1/tasks/status"
        )
        assert response.status_code == 200
        data = response.json()
        assert "file_redis_available" in data
        assert "web_redis_available" in data
```

---

## FAQ

**Q: Can I stop a task that's already completed?**
A: Yes, revoke will succeed but have no effect. The task is already done.

**Q: Will graceful shutdown always complete cleanup?**
A: Not guaranteed. If cleanup takes >5 seconds, SIGKILL is sent automatically.

**Q: What's the difference between stop/file and stop/web?**
A: Nothing functionally, except stop/file only targets file tasks and stop/web only targets web tasks. Use /stop/{task_id} to let it auto-detect.

**Q: Can I see which tasks are running?**
A: No, but you can see queue lengths with /status. For specific running tasks, check the database directly.

**Q: What happens if I stop a task mid-upload?**
A: The upload may complete (if it's nearly done), or it will be killed. Redis flag catches it at the next checkpoint.

**Q: Is stop-all reversible?**
A: No. It terminates all tasks immediately. You'd need to restart everything.

---

## Integration Points

The API is automatically available at:
- Development: `http://localhost:8001/api/v1/tasks`
- Railway (via API Gateway): `http://api-gateway:8000/api/v1/tasks`
- Direct (on Railway): `http://knowledgebase-ingestion.railway.internal:8001/api/v1/tasks`

All endpoints require no authentication (open to internal network).

