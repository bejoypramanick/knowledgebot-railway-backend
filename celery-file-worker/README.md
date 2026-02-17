# Celery File Processing Worker

This service processes async file upload tasks for the knowledgebase.

## Purpose

Executes `process_file_upload_task` from the `file_processing` queue:
- Extracts content from uploaded files (HTML, PDF, DOCX, etc.)
- Converts to markdown using Docling service
- Uploads to Gemini FileSearch
- Updates database with processing status

## Queue Configuration

| Setting | Value |
|---------|-------|
| **Service** | knowledgebase_ingestion |
| **Queue** | file_processing |
| **Redis DB** | 0 |
| **Concurrency** | 2 worker processes |
| **Task Timeout** | 30 minutes |
| **Max Tasks/Child** | 1000 |

## Deployment

### Railway

```bash
# Deploy from root directory
cd knowledgebot-railway-backend
railway up --name celery-file-worker
```

### Local Development

```bash
# Terminal 1: Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 2: Start worker
celery -A knowledgebase_ingestion.celery_app worker \
  -Q file_processing \
  -l info \
  -c 2 \
  --max-tasks-per-child=1000
```

## Environment Variables

Set these in Railway dashboard for the service:

```
REDIS_URL=redis://redis.railway.internal:6379/0
RAILWAY_POSTGRES_URL=postgresql://...
GEMINI_API_KEY=your-api-key
DOCLING_ENABLED=true
```

## Monitoring

### Check Worker Status

```bash
# From any service container
celery -A knowledgebase_ingestion.celery_app inspect active
celery -A knowledgebase_ingestion.celery_app inspect stats

# Check queue depth
redis-cli LLEN celery:file_processing
```

### View Logs

```
Railway Dashboard → celery-file-worker → Logs
```

**Expected startup logs:**
```
[config]
.> app:         knowledgebase_ingestion:14a91b0e6c
.> transport:   redis://redis.railway.internal:6379/0
.> results:     redis://redis.railway.internal:6379/0
.> concurrency: 2
.> task events: OFF (enable with -E)

[queues]
.> file_processing exchange=file_processing(direct) key=file_processing

[tasks]
  . knowledgebase_ingestion.tasks.process_file_upload_task

[2025-02-17 10:00:00,000: WARNING/MainProcess] celery@worker ready.
```

## Task Status Lifecycle

```
User uploads file
    ↓
Database: status='pending'
    ↓
Worker picks up task
    ↓
Database: status='processing'
    ↓
Extract content → Convert → Upload to Gemini
    ↓
Database: status='completed' (or 'failed' if error)
```

## Performance Tuning

### Increase Concurrency (if CPU available)

```
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 4"
#                                                                                                    ^ increase
```

**Trade-off:** More concurrent tasks = higher CPU/memory usage

### Decrease Concurrency (if memory/CPU constrained)

```
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 1"
#                                                                                                    ^ decrease
```

### Restart Worker More Frequently

```
--max-tasks-per-child=500
#                        ^ decrease (restart after 500 tasks instead of 1000)
```

**Why:** Prevents memory leaks from long-running tasks

## Troubleshooting

### Worker Won't Start

**Check 1: Redis connection**
```bash
redis-cli -h redis.railway.internal ping
# Should return: PONG
```

**Check 2: Database connection**
```bash
psql $RAILWAY_POSTGRES_URL -c "SELECT 1"
# Should return: 1
```

**Check 3: Gemini API key**
```bash
echo $GEMINI_API_KEY
# Should show: (API key value)
```

### Tasks Not Processing

**Check 1: Worker alive**
```bash
celery -A knowledgebase_ingestion.celery_app inspect active
# Should show: "OK" and list of active tasks
```

**Check 2: Queue depth**
```bash
redis-cli LLEN celery:file_processing
# Should be decreasing if worker is processing
```

**Check 3: Worker logs**
```
Railway → celery-file-worker → Logs
# Look for: [ERROR] or [FAILED] messages
```

### High Memory Usage

**Solution:** Reduce concurrency and max-tasks-per-child

```
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 1 --max-tasks-per-child=500"
```

### Tasks Timing Out (30 minute limit)

**Check:** File size and network

Large files or slow networks may hit 30-minute timeout.

**Solution:** Optimize Docling or increase timeout in `knowledgebase_ingestion/celery_app.py`:

```python
task_soft_time_limit = 3600  # 60 minutes
task_time_limit = 3700       # 61.67 minutes
```

## File Processing Pipeline

```
1. Receive task: process_file_upload_task(file_id, tmp_path, ...)
   ↓
2. Determine file type:
   ├─ HTML → extract_content_from_html()
   ├─ PDF/DOCX → docling_integration.process_with_docling()
   └─ Other → treat as text
   ↓
3. Convert to markdown (if needed)
   ↓
4. Upload to Gemini FileSearch:
   └─ genai_client.files.upload()
   └─ Store in knowledgebot-search-store
   ↓
5. Update database:
   ├─ gemini_file_name
   ├─ gemini_file_uri
   ├─ gemini_state = "ACTIVE"
   ├─ processing_status = "completed"
   └─ metadata (FileSearch store info)
   ↓
6. Done! File is now searchable
```

## Related Services

- **knowledgebase_ingestion** (8001): Dispatches file upload tasks
- **redis** (6379): Message broker (DB 0: file_processing queue)
- **PostgreSQL**: Stores task status and metadata
- **Docling Service** (8004): Converts documents to markdown
- **Gemini FileSearch**: Stores and indexes file content

## Scaling

### Add More Workers

Deploy multiple instances:
```bash
railway up --name celery-file-worker-2
railway up --name celery-file-worker-3
```

All workers listen to same queue, so tasks are distributed.

### Monitor All Workers

```bash
celery -A knowledgebase_ingestion.celery_app inspect active_queues
# Shows all connected workers and their queues
```

## Maintenance

### Clear Stuck Tasks

```bash
# Purge entire queue (use carefully!)
redis-cli DEL celery:file_processing

# Or clear specific task
redis-cli LRANGE celery:file_processing 0 -1  # list tasks
redis-cli LREM celery:file_processing 1 "task_id"  # remove task
```

### Restart Worker

```
Railway → celery-file-worker → Redeploy
```

This restarts the service gracefully (tries to finish current task before shutting down).

## Cost & Performance

| Metric | Value |
|--------|-------|
| **Memory** | ~256-512MB per concurrency |
| **CPU** | Variable (intensive during processing) |
| **Network** | Depends on file size (uploads to Gemini) |
| **Cost Impact** | ~$5-10/month per worker instance |

## Next Steps

1. Configure `REDIS_URL` environment variable
2. Deploy to Railway: `railway up --name celery-file-worker`
3. Monitor logs for successful startup
4. Test by uploading a file
5. Verify database status changes: `pending` → `processing` → `completed`
