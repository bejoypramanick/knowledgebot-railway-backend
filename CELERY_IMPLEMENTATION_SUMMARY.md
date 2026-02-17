# Feature 1: Celery + Redis Implementation - Summary

## ✅ Complete Implementation for Heavy Async Workloads

This implementation replaces FastAPI BackgroundTasks with **Celery + Redis** to handle heavy file uploads and website scraping workloads with proper job queuing, failure handling, and horizontal scaling.

---

## What's Been Implemented

### 1. Database Schema Updates ✅

**File:** `migrations/001_add_processing_status.sql`

Run this migration on your existing database:
```bash
psql -d your_database_name -f migrations/001_add_processing_status.sql
```

**Changes:**
- Added `processing_status` VARCHAR(20) column to `file_uploads` and `scraped_websites`
- Added `error_message` TEXT column for failure details
- Values: `pending` → `processing` → `completed` or `failed`
- Created optimized indexes for efficient polling

---

### 2. Celery Configuration ✅

#### Knowledgebase Ingestion Service
**Files:**
- `knowledgebase_ingestion/celery_app.py` - Celery app + Redis broker config
- `knowledgebase_ingestion/tasks.py` - Celery tasks for file processing

**Configuration:**
- Queue: `file_processing`
- Concurrency: 2-4 workers (CPU-bound: Docling, Gemini)
- Timeout: 30 minutes soft, 31+ hard
- Retries: 2x with exponential backoff
- Result expiry: 1 hour

#### Website Crawling Service
**Files:**
- `website_crawling/celery_app.py` - Celery app + Redis broker config
- `website_crawling/tasks.py` - Celery tasks for web scraping

**Configuration:**
- Queue: `web_crawling`
- Concurrency: 1-2 workers (I/O-bound: long timeouts)
- Timeout: 2 hours soft, 2+ hours hard
- Retries: 2x with exponential backoff
- Result expiry: 1 hour

---

### 3. Async API Endpoints ✅

#### File Upload Endpoint
```http
POST /api/v1/gateway/knowledgebase/upload/async
```

Request:
```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf" \
  http://localhost:8001/upload/async
```

Response:
```json
{
  "success": true,
  "message": "File upload queued for processing",
  "file": {
    "id": "123",
    "original_filename": "document.pdf",
    "display_name": "document.pdf",
    "size_bytes": "5242880",
    "mime_type": "application/pdf",
    "processing_status": "pending",
    "created_at": "2026-02-17T10:00:00Z"
  },
  "task_id": "abc-def-123"
}
```

#### Website Scraping Endpoint
```http
POST /api/v1/gateway/webcrawl/async
```

Request:
```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/sitemap.xml",
    "max_depth": 2
  }' \
  http://localhost:8002/async
```

Response:
```json
{
  "success": true,
  "message": "Website scraping queued for processing",
  "website": {
    "id": "456",
    "url": "https://example.com/sitemap.xml",
    "processing_status": "pending",
    "created_at": "2026-02-17T10:00:00Z"
  },
  "task_id": "xyz-uvw-456"
}
```

#### Status Polling Endpoints
```http
GET /api/v1/gateway/knowledgebase/status
GET /api/v1/gateway/knowledgebase/status/{id}
```

Response:
```json
{
  "success": true,
  "type": "file",
  "id": "123",
  "name": "document.pdf",
  "processing_status": "processing",
  "error_message": null,
  "created_at": "2026-02-17T10:00:00Z",
  "updated_at": "2026-02-17T10:00:30Z"
}
```

---

## How It Works

### Request Flow

```
1. User uploads file via POST /upload/async
   ↓
2. API creates DB record with status='pending'
   ↓
3. API dispatches Celery task to Redis queue
   ↓
4. API returns immediately with file_id and task_id
   ↓
5. Frontend polls GET /status/{file_id} every 5 seconds
   ↓
6. Celery worker picks up task from queue
   ↓
7. Task processes: HTML extraction → Docling → Gemini upload
   ↓
8. Task updates DB: status='processing' → 'completed' or 'failed'
   ↓
9. Frontend sees status change and updates UI (spinner → checkmark/error)
```

### Task Processing

**File Upload Task:**
1. Set status='processing'
2. Route file based on type:
   - HTML files → Extract content
   - PDF/DOCX → Convert with Docling
   - Text → Process as-is
3. Upload to Gemini FileSearch store
4. Update DB with metadata
5. Set status='completed'
6. If error at any step → status='failed' + error_message

**Website Scraping Task:**
1. Set status='processing'
2. Create parent record for sitemap (if applicable)
3. Scrape URLs with Crawl4AI
4. Convert HTML to markdown (if Docling enabled)
5. Upload to Gemini
6. Create hierarchical DB records
7. Set status='completed'
8. If error → status='failed' + error_message

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- PostgreSQL
- Redis
- Python packages: celery[redis], redis

### Quick Start

**Step 1: Install Dependencies**
```bash
pip install -r knowledgebase_ingestion/requirements.txt
pip install -r website_crawling/requirements.txt
```

**Step 2: Run Database Migration**
```bash
psql -d knowledgebot -f migrations/001_add_processing_status.sql
```

**Step 3: Start Redis**
```bash
# Docker
docker run -p 6379:6379 redis:7-alpine

# Or local Redis
redis-server
```

**Step 4: Start Celery Workers**

Terminal 1 - File Processing Worker:
```bash
cd knowledgebase_ingestion
celery -A knowledgebase_ingestion.celery_app worker \
  -Q file_processing \
  -l info \
  -c 2
```

Terminal 2 - Web Crawling Worker:
```bash
cd website_crawling
celery -A website_crawling.celery_app worker \
  -Q web_crawling \
  -l info \
  -c 1
```

Terminal 3 - Celery Monitoring (Optional):
```bash
celery -A knowledgebase_ingestion.celery_app flower
# Visit http://localhost:5555
```

**Step 5: Start FastAPI Services**

Terminal 4 - Knowledgebase Ingestion:
```bash
cd knowledgebase_ingestion
uvicorn main:app --reload --port 8001
```

Terminal 5 - Website Crawling:
```bash
cd website_crawling
uvicorn main:app --reload --port 8002
```

### Using Docker Compose

```bash
# Start all services
docker-compose -f docker-compose.celery.yml up -d

# View logs
docker-compose -f docker-compose.celery.yml logs -f

# Stop all
docker-compose -f docker-compose.celery.yml down
```

Services will be available at:
- Redis: localhost:6379
- Celery Flower: localhost:5555
- API services: localhost:8001, localhost:8002

---

## Production Deployment (Railway)

### Step 1: Add Redis to Railway

```bash
railway add
# Select "Redis"
# Copy the REDIS_URL from Railway dashboard
```

### Step 2: Create File Processing Worker Service

```bash
railway service add
# Name: knowledgebot-celery-file
# Start Command: celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2
```

Set environment variables:
```
REDIS_URL=<from Railway Redis>
DATABASE_URL=<from Railway Postgres>
GEMINI_API_KEY=<your key>
```

### Step 3: Create Web Crawling Worker Service

```bash
railway service add
# Name: knowledgebot-celery-web
# Start Command: celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 1
```

Set environment variables:
```
REDIS_URL=<from Railway Redis>
DATABASE_URL=<from Railway Postgres>
GEMINI_API_KEY=<your key>
```

### Step 4: Deploy

```bash
git push origin main
# Railway auto-deploys

# Monitor logs
railway logs -s knowledgebot-celery-file
railway logs -s knowledgebot-celery-web
```

---

## Configuration

### Environment Variables

Create `.env` file:
```bash
# Redis
REDIS_URL=redis://localhost:6379/0

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/knowledgebot

# Gemini
GEMINI_API_KEY=your_key_here

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

See `.env.celery.example` for all options.

### Task Timeouts

Edit `celery_app.py` to adjust:

```python
celery_app.conf.update(
    # File processing: 30 minutes
    task_soft_time_limit=1800,      # 30 minutes
    task_time_limit=1900,           # 31+ minutes (hard kill)

    # Web crawling: 2 hours
    task_soft_time_limit=7200,      # 2 hours
    task_time_limit=7300,           # 2+ hours (hard kill)
)
```

### Worker Concurrency

```bash
# File processing - can handle more concurrent tasks
celery -A knowledgebase_ingestion.celery_app worker -c 4

# Web crawling - keep low for heavy workloads
celery -A website_crawling.celery_app worker -c 1
```

---

## Monitoring

### Celery Flower UI

Visit http://localhost:5555 to see:
- Active tasks
- Worker status
- Task execution history
- Queue depth
- Worker statistics

### Database Queries

Check processing status:
```sql
-- Pending/processing files
SELECT id, original_filename, processing_status, error_message, updated_at
FROM file_uploads
WHERE processing_status IN ('pending', 'processing')
ORDER BY updated_at DESC;

-- Failed files
SELECT id, original_filename, error_message, updated_at
FROM file_uploads
WHERE processing_status = 'failed'
ORDER BY updated_at DESC;

-- Pending/processing websites
SELECT id, original_url, processing_status, error_message, updated_at
FROM scraped_websites
WHERE processing_status IN ('pending', 'processing')
ORDER BY updated_at DESC;
```

### Command Line

```bash
# Check active workers
celery -A knowledgebase_ingestion.celery_app inspect ping

# Check active tasks
celery -A knowledgebase_ingestion.celery_app inspect active

# Check queue depth
celery -A knowledgebase_ingestion.celery_app inspect active_queues

# Get task result
celery -A knowledgebase_ingestion.celery_app result <task_id>
```

---

## Architecture Benefits

### ✅ Scalability
- Horizontal scaling: Add more workers as load increases
- Separate queues: File and web tasks don't compete
- Task routing: Distribute tasks to optimal workers

### ✅ Reliability
- Job persistence: Tasks survive worker crashes
- Automatic retries: Failed tasks retry 2x with backoff
- Dead-letter handling: Failed tasks logged with error messages
- Status tracking: All progress stored in PostgreSQL

### ✅ Performance
- Non-blocking: API returns immediately
- Load distribution: Workers process tasks in parallel
- Task timeouts: Prevent hung tasks from blocking queue
- Prefetch tuning: Optimized for long-running tasks

### ✅ Observability
- Flower monitoring: Real-time task visibility
- Database tracking: Query processing status anytime
- Detailed logging: Full task execution logs
- Error messages: Capture failure reasons for debugging

---

## Common Operations

### Check if Services Are Running

```bash
# Redis
redis-cli ping
# Response: PONG

# Celery Workers
celery -A knowledgebase_ingestion.celery_app inspect ping
# Response: {worker-name: ok}
```

### Restart a Worker

```bash
# Kill the worker
pkill -f "celery worker"

# Restart
celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2
```

### Clear Failed Tasks

```bash
# WARNING: This purges ALL tasks in the queue
celery -A knowledgebase_ingestion.celery_app purge
```

### Test Celery Connection

```bash
# Send a debug task
celery -A knowledgebase_ingestion.celery_app call knowledgebase_ingestion.celery_app.debug_task
```

---

## Troubleshooting

### Redis Connection Error

```
ConnectionError: Error -2 connecting to localhost:6379
```

**Solution:**
```bash
# Verify Redis is running
redis-cli ping

# If not, start it
redis-server
# Or Docker
docker run -p 6379:6379 redis:7-alpine
```

### Tasks Not Processing

**Solution:**
```bash
# Check if workers are running
celery -A knowledgebase_ingestion.celery_app inspect ping

# Check active tasks
celery -A knowledgebase_ingestion.celery_app inspect active

# Restart worker if not responding
pkill -f "celery worker"
celery -A knowledgebase_ingestion.celery_app worker -l info
```

### Task Timeout

```
Task timed out after 1800 seconds
```

**Solution:**
1. Increase timeout in `celery_app.py`
2. Optimize task logic to reduce execution time
3. Increase worker concurrency to distribute load

### Database Constraint Error

```
constraint "valid_file_processing_status" is violated
```

**Solution:**
```bash
# Run the migration
psql -f migrations/001_add_processing_status.sql

# Verify constraint exists
psql -c "\\d file_uploads"
```

---

## Frontend Integration

### Update File Upload

```typescript
// OLD: Blocking upload
const response = await fetch('/upload', { method: 'POST', body: formData });

// NEW: Async upload with Celery
const response = await fetch('/upload/async', { method: 'POST', body: formData });
const data = await response.json();
const fileId = data.file.id;

// Start polling
const interval = setInterval(async () => {
  const statusResponse = await fetch(`/status/${fileId}`);
  const statusData = await statusResponse.json();

  if (statusData.processing_status === 'completed') {
    clearInterval(interval);
    showSuccess('File uploaded!');
  } else if (statusData.processing_status === 'failed') {
    clearInterval(interval);
    showError(`Upload failed: ${statusData.error_message}`);
  }
}, 5000); // Poll every 5 seconds
```

### UI Status Icons

- 🟡 **Pending/Processing:** Animated spinner (Loader2 from Lucide)
- 🟢 **Completed:** Green checkmark (CheckCircle2)
- 🔴 **Failed:** Red X with error tooltip (XCircle)

See `CELERY_DEPLOYMENT_GUIDE.md` for complete frontend guide.

---

## Performance Tuning

### Worker Concurrency
- File processing: 2-4 (CPU-bound: Docling)
- Web crawling: 1-2 (I/O-bound: long timeouts)

### Prefetch Multiplier
Lower = workers wait for tasks to finish (good for long-running)
```bash
celery -A knowledgebase_ingestion.celery_app worker --prefetch-multiplier=1
```

### Task Timeouts
- File processing: 30 minutes
- Web crawling: 2 hours
Adjust in `celery_app.py` based on your workload

### Task Retry Strategy
- Max retries: 2
- Backoff: 60 seconds × 2^retry_count
Adjust in `tasks.py` as needed

---

## Files Created/Modified

### New Files ✅
- `migrations/001_add_processing_status.sql` - DB migration
- `knowledgebase_ingestion/celery_app.py` - Celery config
- `knowledgebase_ingestion/tasks.py` - File processing tasks
- `website_crawling/celery_app.py` - Celery config
- `website_crawling/tasks.py` - Web scraping tasks
- `docker-compose.celery.yml` - Docker Compose setup
- `Dockerfile.celery` - Celery worker Docker image
- `CELERY_DEPLOYMENT_GUIDE.md` - Deployment guide
- `.env.celery.example` - Environment template

### Modified Files ✅
- `knowledgebase_ingestion/requirements.txt` - Added celery[redis], redis
- `knowledgebase_ingestion/service/ingestion_service.py` - Celery dispatch
- `knowledgebase_ingestion/routers/router.py` - Updated endpoints
- `website_crawling/requirements.txt` - Added celery[redis], redis
- `website_crawling/service/website_service.py` - Celery dispatch
- `website_crawling/routers/router.py` - Updated endpoints

---

## Next Steps

1. **Run database migration:**
   ```bash
   psql -d knowledgebot -f migrations/001_add_processing_status.sql
   ```

2. **Test locally with Docker Compose:**
   ```bash
   docker-compose -f docker-compose.celery.yml up -d
   ```

3. **Deploy to Railway:**
   - Add Redis add-on
   - Create worker services
   - Set REDIS_URL environment variable

4. **Update frontend** to use async endpoints and poll for status

5. **Monitor** with Flower UI or Railway logs

---

## Additional Resources

- [Celery Documentation](https://docs.celeryproject.io/)
- [Flower Monitoring](https://flower.readthedocs.io/)
- [Redis Documentation](https://redis.io/docs/)
- [Railway Deployment](https://docs.railway.app/)
- Complete guide: `CELERY_DEPLOYMENT_GUIDE.md`

