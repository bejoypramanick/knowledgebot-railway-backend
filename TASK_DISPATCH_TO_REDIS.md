# How Tasks Are Put Into Redis - Complete Code Flow

This document shows the complete code flow for how tasks are dispatched to Redis queues for both web scraping and file processing.

## Architecture Overview

```
API Request → Router → Service → Celery Dispatcher → Redis Queue → Worker
```

## Components

1. **Celery Dispatcher** (`shared/celery_dispatcher.py`) - Creates Celery clients
2. **Router** - Receives API requests
3. **Service** - Business logic and task dispatch
4. **Redis** - Message broker (queue storage)
5. **Worker** - Consumes tasks from queue

---

## 1. Celery Dispatcher Setup

**File**: `shared/celery_dispatcher.py`

This creates two separate Celery dispatcher instances:

```python
import os
from celery import Celery

# File processing: Redis DB 0
file_redis_url = os.getenv('FILE_REDIS_URL')
file_celery = Celery('file_dispatcher', broker=file_redis_url)
file_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_backend=file_redis_url,
)

# Web crawling: Redis DB 1
web_redis_url = os.getenv('WEB_REDIS_URL')
web_celery = Celery('web_dispatcher', broker=web_redis_url)
web_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_backend=web_redis_url,
)
```

**Key Points**:
- Two separate Redis databases (DB 0 for files, DB 1 for web)
- JSON serialization for task data
- Broker and result backend use same Redis URL

---

## 2. Web Scraping Task Dispatch

### 2.1 Router Endpoint

**File**: `knowledgebase_ingestion/routers/webcrawl_router.py`

```python
@router.post("/webcrawl/async")
async def scrape_website_async_endpoint(request: Request = None):
    """Async website scraping endpoint"""
    
    # Extract user info
    user_email, user_id = extract_user_from_request(request)
    
    # Get request data
    request_data = await request.json()
    
    # Validate request
    validation_result = await validate_scraping_request(request_data)
    
    # Queue website for scraping
    result = await queue_website_for_scraping(
        url=validation_result['url'],
        user_role_id=user_id,
        max_depth=validation_result.get('max_depth', 2),
        max_pages=validation_result.get('max_pages', 100),
        max_concurrent=validation_result.get('max_concurrent', 10),
        delay_between_requests=validation_result.get('delay_between_requests', 0.0)
    )
    
    return result
```

### 2.2 Service - Task Dispatch

**File**: `knowledgebase_ingestion/service/webcrawl_service.py`

```python
from shared.celery_dispatcher import web_celery

async def queue_website_for_scraping(
    url: str,
    user_role_id: int = None,
    max_depth: int = 2,
    max_pages: int = 100,
    max_concurrent: int = 10,
    delay_between_requests: float = 0.0
):
    """Queue website for scraping - THIS IS WHERE THE TASK GOES INTO REDIS"""
    
    # Build options dict
    options = {
        'max_depth': max_depth,
        'max_pages': max_pages,
        'max_concurrent': max_concurrent,
        'delay_between_requests': delay_between_requests,
        'user_role_id': user_role_id
    }
    
    # Create DB record first (to get website_id)
    placeholder_task_id = str(uuid.uuid4())
    website_id = await create_website_record(url, user_role_id, placeholder_task_id)
    
    # ⭐ DISPATCH TO REDIS - THIS IS THE KEY LINE ⭐
    result = web_celery.send_task(
        'tasks.scrape_website_task',      # Task name (must match worker)
        args=[website_id, url, options],  # Task arguments
        queue='web_crawling'              # Queue name (must match worker)
    )
    
    # Get the Celery-assigned task ID
    task_id = result.id
    
    # Update DB with real task ID
    await dao.update_celery_task_id(website_id, task_id)
    
    return {
        "success": True,
        "task_id": task_id,
        "website_id": str(website_id),
        "url": url,
        "status": "Queued"
    }
```

**What Happens When `send_task()` is Called**:

1. Celery serializes the task data to JSON:
   ```json
   {
     "task": "tasks.scrape_website_task",
     "args": [123, "https://example.com", {...}],
     "kwargs": {},
     "id": "abc-123-def-456"
   }
   ```

2. Celery pushes this JSON to Redis list `web_crawling`:
   ```bash
   LPUSH web_crawling '{"task": "tasks.scrape_website_task", ...}'
   ```

3. Redis stores it in the queue (DB 1)

4. Worker polls the queue with `BRPOP web_crawling`

5. Worker receives the task and executes it

---

## 3. File Processing Task Dispatch

### 3.1 Router Endpoint

**File**: `knowledgebase_ingestion/routers/fileupload_router.py`

```python
from shared.celery_dispatcher import file_celery

@router.post("/upload/async")
async def upload_file_async(
    file: UploadFile = Form(...),
    file_display_name: Optional[str] = Form(None),
    request: Request = None
):
    """Async file upload endpoint"""
    
    # Extract user info
    user_email, user_id = extract_user_from_request(request)
    
    # Validate file
    validation_result = await validate_file_upload(file, file_size)
    
    # Read file into bytes
    file_bytes = await file.read()
    file_size = len(file_bytes)
    
    # Upload to S3
    success, s3_key = await s3_file_storage.upload_file(
        file_data=file_bytes,
        original_filename=validation_result['filename'],
        file_type="upload"
    )
    
    # ⭐ DISPATCH TO REDIS - THIS IS THE KEY LINE ⭐
    result = file_celery.send_task(
        'tasks.process_file_upload_task',  # Task name (must match worker)
        args=[
            validation_result['original_filename'],
            file_display_name or validation_result['filename'],
            s3_key,
            file_size,
            user_email,
            user_id
        ],
        queue='file_processing'            # Queue name (must match worker)
    )
    
    # Get the Celery-assigned task ID
    celery_task_id = result.id
    
    # Create DB record with task ID
    record_data = {
        'user_id': user_id,
        'original_filename': validation_result['original_filename'],
        'file_display_name': file_display_name,
        'size_bytes': file_size,
        'processing_status': 'pending',
        'celery_task_id': celery_task_id,
        's3_key': s3_key
    }
    file_id = await create_file_record(record_data)
    
    return {
        "success": True,
        "task_id": celery_task_id,
        "file_id": file_id,
        "status": "Queued"
    }
```

**What Happens When `send_task()` is Called**:

1. Celery serializes the task data to JSON:
   ```json
   {
     "task": "tasks.process_file_upload_task",
     "args": ["document.pdf", "My Document", "s3://...", 1024000, "user@example.com", 123],
     "kwargs": {},
     "id": "xyz-789-abc-012"
   }
   ```

2. Celery pushes this JSON to Redis list `file_processing`:
   ```bash
   LPUSH file_processing '{"task": "tasks.process_file_upload_task", ...}'
   ```

3. Redis stores it in the queue (DB 0)

4. Worker polls the queue with `BRPOP file_processing`

5. Worker receives the task and executes it

---

## 4. Redis Queue Structure

### Web Crawling Queue (DB 1)

```bash
# Queue name
web_crawling

# Check queue length
LLEN web_crawling

# View tasks in queue
LRANGE web_crawling 0 -1

# Task structure in Redis
{
  "body": "base64_encoded_task_data",
  "content-encoding": "utf-8",
  "content-type": "application/json",
  "headers": {
    "id": "task-id-here",
    "task": "tasks.scrape_website_task",
    "argsrepr": "[123, 'https://example.com', {...}]"
  },
  "properties": {
    "correlation_id": "task-id-here",
    "delivery_mode": 2
  }
}
```

### File Processing Queue (DB 0)

```bash
# Queue name
file_processing

# Check queue length
LLEN file_processing

# View tasks in queue
LRANGE file_processing 0 -1

# Task structure (same format as web crawling)
```

---

## 5. Worker Configuration

### Web Worker

**File**: `celery-web-worker/celery_app.py`

```python
celery_app.conf.update(
    broker_url=redis_url,              # WEB_REDIS_URL (DB 1)
    result_backend=redis_url,
    task_routes={
        'tasks.scrape_website_task': {'queue': 'web_crawling'},
    },
)
```

**Start Command**:
```bash
celery -A celery_app worker --loglevel=info --queues=web_crawling
```

### File Worker

**File**: `celery-file-worker/celery_app.py`

```python
celery_app.conf.update(
    broker_url=redis_url,              # FILE_REDIS_URL (DB 0)
    result_backend=redis_url,
    task_routes={
        'tasks.process_file_upload_task': {'queue': 'file_processing'},
    },
)
```

**Start Command**:
```bash
celery -A celery_app worker --loglevel=info --queues=file_processing
```

---

## 6. Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         API REQUEST                              │
│  POST /api/v1/gateway/knowledgebase/webcrawl/async              │
│  POST /api/v1/gateway/knowledgebase/upload/async                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         ROUTER                                   │
│  - Extract user info                                             │
│  - Validate request                                              │
│  - Call service function                                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SERVICE                                  │
│  - Create DB record                                              │
│  - Build task arguments                                          │
│  - Call web_celery.send_task() or file_celery.send_task()      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CELERY DISPATCHER                             │
│  - Serialize task to JSON                                        │
│  - Connect to Redis                                              │
│  - LPUSH task to queue                                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         REDIS                                    │
│  DB 0: file_processing queue                                     │
│  DB 1: web_crawling queue                                        │
│  - Stores tasks as JSON in list                                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         WORKER                                   │
│  - BRPOP from queue (blocking pop)                               │
│  - Deserialize JSON                                              │
│  - Execute task function                                         │
│  - Update DB with results                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Key Environment Variables

### API Gateway (knowledgebase_ingestion)
```bash
FILE_REDIS_URL=redis://default:password@host:port?db=0
WEB_REDIS_URL=redis://default:password@host:port?db=1
```

### File Worker (celery-file-worker)
```bash
FILE_REDIS_URL=redis://default:password@host:port?db=0
```

### Web Worker (celery-web-worker)
```bash
WEB_REDIS_URL=redis://default:password@host:port?db=1
```

---

## 8. Debugging Commands

### Check if task was added to Redis

```bash
# Connect to Redis
redis-cli -u $WEB_REDIS_URL

# Check web crawling queue
LLEN web_crawling
LRANGE web_crawling 0 4

# Check file processing queue (switch to DB 0)
SELECT 0
LLEN file_processing
LRANGE file_processing 0 4
```

### Monitor queue in real-time

```bash
# Watch queue length change
watch -n 1 'redis-cli -u $WEB_REDIS_URL LLEN web_crawling'
```

### Check Celery task status

```python
from shared.celery_dispatcher import web_celery

result = web_celery.AsyncResult('task-id-here')
print(f"State: {result.state}")
print(f"Status: {result.status}")
print(f"Result: {result.result}")
```

---

## Summary

**The key line where tasks go into Redis**:

```python
# For web scraping
result = web_celery.send_task(
    'tasks.scrape_website_task',
    args=[website_id, url, options],
    queue='web_crawling'
)

# For file processing
result = file_celery.send_task(
    'tasks.process_file_upload_task',
    args=[filename, display_name, s3_key, size, email, user_id],
    queue='file_processing'
)
```

This `send_task()` call:
1. Serializes the task data to JSON
2. Connects to Redis using the broker URL
3. Pushes the task to the specified queue using `LPUSH`
4. Returns immediately with a task ID
5. Worker picks it up with `BRPOP` (blocking pop from right side of list)
