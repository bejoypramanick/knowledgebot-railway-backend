# Celery Web Worker Not Picking Up Scraping Tasks - Troubleshooting Guide

## Problem
The Celery web worker is not picking up scraping tasks from the `web_crawling` queue.

## Possible Causes

### 1. Worker Not Running
**Check**: Is the celery-web-worker service running on Railway?

**Solution**:
- Go to Railway dashboard
- Check if `celery-web-worker` service is deployed and running
- Check the logs for startup messages

**Expected logs**:
```
🚀 [CELERY_APP] Initializing Celery for Website Crawling Worker
✅ [REDIS] Connection test successful - Redis is reachable
✅ [CELERY_APP] Tasks module loaded successfully
❤️  [HEARTBEAT] Worker alive - Queue depth: X tasks
```

### 2. Redis Connection Issue
**Check**: Is WEB_REDIS_URL configured correctly?

**Solution**:
- Verify `WEB_REDIS_URL` environment variable is set in Railway
- Should point to Redis DB 1 (e.g., `redis://...?db=1`)
- Check logs for Redis connection errors

**Expected logs**:
```
✅ [REDIS] Connection test successful - Redis is reachable
📊 [REDIS] Current queue depth: X tasks
```

**Error logs to look for**:
```
⚠️  [REDIS] Connection test failed
❌ [REDIS] Unexpected error during connection test
```

### 3. Queue Name Mismatch
**Check**: Are tasks being sent to the correct queue?

**Current Configuration**:
- Tasks are sent to queue: `web_crawling`
- Worker listens to queue: `web_crawling`
- Task name: `tasks.scrape_website_task`

**Verify in logs**:
```
📤 [CELERY_DISPATCH] About to dispatch to Celery...
   Task: 'tasks.scrape_website_task'
   Queue: 'web_crawling'
✅ [CELERY_SEND_SUCCESS] Task dispatched successfully!
```

### 4. Worker Not Listening to Correct Queue
**Check**: Is the worker started with the correct queue parameter?

**Solution**:
The worker should be started with:
```bash
celery -A celery_app worker --loglevel=info --queues=web_crawling
```

**Check Railway start command** for celery-web-worker service.

### 5. Task Not Registered
**Check**: Is the task properly registered in the worker?

**Expected logs on worker startup**:
```
✅ [CELERY_APP] Tasks module loaded successfully
```

**If you see**:
```
❌ [CELERY_APP] Failed to load tasks module
```

Then the tasks.py file is not being imported correctly.

### 6. Redis DB Mismatch
**Check**: Are the dispatcher and worker using the same Redis DB?

**Current Setup**:
- File processing: Redis DB 0 (FILE_REDIS_URL)
- Web crawling: Redis DB 1 (WEB_REDIS_URL)

**Verify**:
- Dispatcher (knowledgebase_ingestion): Uses `WEB_REDIS_URL` to send tasks
- Worker (celery-web-worker): Uses `WEB_REDIS_URL` to receive tasks
- Both should point to the same Redis instance and DB number

## Diagnostic Steps

### Step 1: Check Worker Logs
Look for these key messages in celery-web-worker logs:

1. **Worker Started**:
   ```
   🚀 [CELERY_APP] Initializing Celery for Website Crawling Worker
   ```

2. **Redis Connected**:
   ```
   ✅ [REDIS] Connection test successful
   ```

3. **Tasks Loaded**:
   ```
   ✅ [CELERY_APP] Tasks module loaded successfully
   ```

4. **Heartbeat Running**:
   ```
   ❤️  [HEARTBEAT] Worker alive - Queue depth: X tasks
   ```

### Step 2: Check API Gateway Logs
Look for task dispatch messages in knowledgebase_ingestion logs:

1. **Task Dispatched**:
   ```
   📤 [CELERY_DISPATCH] About to dispatch to Celery...
   ✅ [CELERY_SEND_SUCCESS] Task dispatched successfully!
   ```

2. **Task ID Assigned**:
   ```
   ✅ [CELERY_TASK_ID] Celery assigned task ID: xxx-xxx-xxx
   ```

### Step 3: Check Redis Queue
Connect to Redis and check the queue:

```bash
# Connect to Redis
redis-cli -u $WEB_REDIS_URL

# Check queue length
LLEN web_crawling

# View tasks in queue (first 5)
LRANGE web_crawling 0 4

# Check if tasks are being consumed
# Run LLEN multiple times - if number decreases, worker is consuming
```

### Step 4: Check Environment Variables
Verify these are set in Railway:

**celery-web-worker service**:
- `WEB_REDIS_URL` - Should be set (e.g., `redis://...?db=1`)
- `CELERY_WEB_CONCURRENCY` - Optional (default: 5)
- `DB_POOL_MIN_SIZE` - Optional (default: 1)
- `DB_POOL_MAX_SIZE` - Optional (default: 3)

**knowledgebase_ingestion service**:
- `WEB_REDIS_URL` - Should match the worker's URL

### Step 5: Manual Task Test
Try sending a test task manually:

```python
from shared.celery_dispatcher import web_celery

# Send a test task
result = web_celery.send_task(
    'tasks.scrape_website_task',
    args=[1, 'https://example.com', {}],
    queue='web_crawling'
)

print(f"Task ID: {result.id}")
print(f"Task State: {result.state}")
```

## Common Solutions

### Solution 1: Restart Worker
Sometimes the worker needs a restart to pick up configuration changes:
1. Go to Railway dashboard
2. Find celery-web-worker service
3. Click "Restart"
4. Monitor logs for startup messages

### Solution 2: Verify Redis URL
Ensure WEB_REDIS_URL is correctly set:
1. Should include `?db=1` at the end
2. Should be accessible from both services
3. Format: `redis://default:password@host:port?db=1`

### Solution 3: Check Worker Start Command
Verify the start command in Railway:
```bash
celery -A celery_app worker --loglevel=info --queues=web_crawling
```

If missing `--queues=web_crawling`, the worker might be listening to the default queue.

### Solution 4: Increase Logging
Temporarily increase log level to debug:
```bash
celery -A celery_app worker --loglevel=debug --queues=web_crawling
```

### Solution 5: Check for Errors in Worker Logs
Look for these error patterns:
- `ImportError` - Tasks module not found
- `ConnectionError` - Redis connection failed
- `KeyError` - Missing configuration
- `AttributeError` - Task not registered

## Verification Checklist

- [ ] celery-web-worker service is running on Railway
- [ ] WEB_REDIS_URL is set in both services
- [ ] Worker logs show successful Redis connection
- [ ] Worker logs show tasks module loaded
- [ ] Heartbeat logs appear every 30 seconds
- [ ] API gateway logs show task dispatched successfully
- [ ] Redis queue (web_crawling) has tasks (LLEN > 0)
- [ ] Worker start command includes `--queues=web_crawling`
- [ ] No errors in worker logs during startup

## Expected Behavior

When everything is working correctly:

1. **API Gateway** dispatches task:
   ```
   📤 [CELERY_DISPATCH] About to dispatch to Celery...
   ✅ [CELERY_SEND_SUCCESS] Task dispatched successfully!
   ✅ [CELERY_TASK_ID] Celery assigned task ID: abc-123
   ```

2. **Worker** receives and processes task:
   ```
   🚀 [CELERY_TASK_RECEIVED] Website scraping task RECEIVED by worker
   📋 [TASK_ID] Celery Task ID: abc-123
   📦 [PROCESSING_START] Beginning website scraping process
   ✅ [CELERY_TASK_COMPLETE] Website scraping completed successfully
   ```

3. **Database** is updated:
   - Status changes from `pending` → `processing` → `completed`
   - Task ID is recorded in `celery_task_id` column

## Next Steps

If the issue persists after checking all the above:

1. **Collect logs**:
   - celery-web-worker startup logs
   - celery-web-worker runtime logs (last 100 lines)
   - knowledgebase_ingestion logs when dispatching task
   - Redis connection test results

2. **Check Railway service configuration**:
   - Service name: celery-web-worker
   - Start command
   - Environment variables
   - Health check status

3. **Verify task in database**:
   ```sql
   SELECT id, original_url, processing_status, celery_task_id, created_at, updated_at
   FROM scraped_websites
   WHERE processing_status = 'pending'
   ORDER BY created_at DESC
   LIMIT 5;
   ```

4. **Check if tasks are stuck in Redis**:
   - If LLEN keeps increasing but worker doesn't process
   - Worker might be crashed or not listening to the queue

## Contact Information

If you need further assistance, provide:
1. celery-web-worker logs (startup + last 100 lines)
2. knowledgebase_ingestion logs (task dispatch section)
3. Output of `LLEN web_crawling` from Redis
4. Railway service configuration screenshot
