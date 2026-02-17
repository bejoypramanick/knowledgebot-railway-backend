# Celery Workers Deployment Guide - Step by Step

Complete guide to deploy two separate Celery worker services to Railway.

---

## Overview

You now have everything needed to deploy two dedicated Celery workers:

```
celery-file-worker/
├─ railway.toml       ✅ File processing worker config
└─ README.md          ✅ Documentation

celery-web-worker/
├─ railway.toml       ✅ Web crawling worker config
└─ README.md          ✅ Documentation

Both reuse: Dockerfile.celery (existing)
```

---

## Deployment Steps

### Step 1: Commit Changes

First, commit all the new worker configurations:

```bash
cd knowledgebot-railway-backend

git add celery-file-worker/ celery-web-worker/

git commit -m "Add separate Celery worker services configuration

- celery-file-worker: Processes file upload tasks (concurrency: 2)
  * Queue: file_processing (Redis DB 0)
  * Timeout: 30 minutes
  * Reuses: Dockerfile.celery

- celery-web-worker: Processes website scraping tasks (concurrency: 1)
  * Queue: web_crawling (Redis DB 1)
  * Timeout: 2 hours
  * Reuses: Dockerfile.celery

Both workers:
- Connect to shared Redis and PostgreSQL
- Auto-restart on failure (max 10 retries)
- Log all task execution
- Health checked every 5 minutes

See celery-file-worker/README.md and celery-web-worker/README.md for details."

git push
```

### Step 2: Verify Redis is Deployed

Before deploying workers, ensure Redis is running:

```bash
# In Railway dashboard:
Services → redis → Check status (should be "Success")
```

**If Redis not deployed yet:**
1. Follow `REDIS_SETUP_GUIDE.md` to deploy Redis first
2. Wait for Redis service to show "Success"
3. Then proceed to deploy workers

### Step 3: Deploy File Processing Worker

```bash
cd celery-file-worker

# Deploy to Railway
railway up --name celery-file-worker
```

Or via Railway Dashboard:
1. New Service → GitHub Repo
2. Repository: knowledgebot-railway-backend
3. Root Directory: `celery-file-worker`
4. Name: `celery-file-worker`
5. Deploy

### Step 4: Deploy Web Crawling Worker

```bash
cd ../celery-web-worker

# Deploy to Railway
railway up --name celery-web-worker
```

Or via Railway Dashboard (same process, different settings):
1. New Service → GitHub Repo
2. Root Directory: `celery-web-worker`
3. Name: `celery-web-worker`

### Step 5: Configure Environment Variables

For each worker service on Railway dashboard:

#### celery-file-worker Variables:

```
REDIS_URL=redis://redis.railway.internal:6379/0
DATABASE_URL=<same as other services>
GEMINI_API_KEY=<your-api-key>
```

#### celery-web-worker Variables:

```
REDIS_URL=redis://redis.railway.internal:6379/1
DATABASE_URL=<same as other services>
GEMINI_API_KEY=<your-api-key>
```

**How to set:**
1. Railway Dashboard
2. Services → [worker-name]
3. Variables tab
4. Add each key=value
5. Save

### Step 6: Verify Deployment

Wait 2-3 minutes for both services to build and start.

Check Railway dashboard:
- ✅ celery-file-worker: Status should be "Success"
- ✅ celery-web-worker: Status should be "Success"

### Step 7: Verify Worker Startup Logs

#### Check File Worker Logs:

```
Railway Dashboard → celery-file-worker → Logs
```

Look for:
```
[config]
.> app:         knowledgebase_ingestion
.> transport:   redis://redis.railway.internal:6379/0
.> concurrency: 2

[queues]
.> file_processing exchange=file_processing(direct) key=file_processing

[2025-02-17 10:00:00,000: WARNING/MainProcess] celery@worker ready.
```

#### Check Web Worker Logs:

```
Railway Dashboard → celery-web-worker → Logs
```

Look for:
```
[config]
.> app:         website_crawling
.> transport:   redis://redis.railway.internal:6379/1
.> concurrency: 1

[queues]
.> web_crawling exchange=web_crawling(direct) key=web_crawling

[2025-02-17 10:00:00,000: WARNING/MainProcess] celery@worker ready.
```

If you see `celery@worker ready.` message, ✅ workers are running!

### Step 8: Test File Upload

1. Go to your knowledgebot UI
2. Upload a file
3. Check Railway logs for `celery-file-worker`:
   ```
   Received task: process_file_upload_task[abc123def456]
   [knowledgebase_ingestion.tasks.process_file_upload_task[abc123def456]] completed
   ```
4. Database should update: `pending` → `processing` → `completed`

### Step 9: Test Website Scraping

1. Go to your knowledgebot UI
2. Add a website URL to crawl
3. Check Railway logs for `celery-web-worker`:
   ```
   Received task: scrape_website_task[xyz789]
   [website_crawling.tasks.scrape_website_task[xyz789]] completed
   ```
4. Database should update: `pending` → `processing` → `completed`

### Step 10: Monitor Queue Depth

To see how many tasks are queued:

```bash
# From any container with redis-cli
redis-cli LLEN celery:file_processing      # File queue
redis-cli LLEN celery:web_crawling         # Web queue
```

Or via web worker logs, watch task pickup rate.

---

## Complete Architecture After Deployment

```
┌──────────────────────────── RAILWAY ──────────────────────────┐
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ PostgreSQL (Managed)                                    │  │
│  │ - file_uploads (processing_status, metadata)            │  │
│  │ - scraped_websites (processing_status, parent_id)       │  │
│  └─────────────────────┬───────────────────────────────────┘  │
│                        │                                       │
│  ┌──────────────────────▼───────────────────────────────────┐ │
│  │ Redis (6379) - Message Broker                           │ │
│  │ - DB 0: file_processing queue ←→ celery-file-worker     │ │
│  │ - DB 1: web_crawling queue ←→ celery-web-worker         │ │
│  └──────────────────────────────────────────────────────────┘ │
│                        ▲                    ▲                  │
│                        │                    │                  │
│  ┌─────────────────────┴──┐  ┌─────────────┴──────────────┐  │
│  │ knowledgebase_ingestion │  │ website_crawling           │  │
│  │ (8001)                  │  │ (8002)                     │  │
│  │                         │  │                            │  │
│  │ @router.post("/upload") │  │ @router.post("/crawl")     │  │
│  │ task.delay() ───┐       │  │ task.delay() ───┐          │  │
│  └─────────────────┼───────┘  └──────────────────┼──────────┘  │
│                    │                             │              │
│                    └─────────────┬───────────────┘              │
│                                  │                              │
│  ┌──────────────────────────────▼─────────────────────────┐   │
│  │ ┌────────────────────┐    ┌──────────────────────────┐ │   │
│  │ │ celery-file-worker │    │ celery-web-worker        │ │   │
│  │ │ (processes tasks)  │    │ (processes tasks)        │ │   │
│  │ │ concurrency: 2     │    │ concurrency: 1           │ │   │
│  │ │ timeout: 30 min    │    │ timeout: 2 hours         │ │   │
│  │ └────────────────────┘    └──────────────────────────┘ │   │
│  │          ↓                              ↓               │   │
│  │   Extract & Upload              Crawl & Upload         │   │
│  │   to Gemini                      to Gemini             │   │
│  └───────────────────────────────────────────────────────┘   │
│                        ▼                    ▼                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Gemini FileSearch                                      │  │
│  │ - knowledgebot-search-store                            │  │
│  │ - Files with embeddings searchable                     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Verification Checklist

After all services deployed, verify:

### ✅ Redis Running
- [ ] Railway dashboard shows redis service: "Success"
- [ ] Check redis logs: No errors

### ✅ File Worker Running
- [ ] Railway dashboard shows celery-file-worker: "Success"
- [ ] Logs show: "celery@worker ready"
- [ ] Environment variables set: REDIS_URL (DB 0)

### ✅ Web Worker Running
- [ ] Railway dashboard shows celery-web-worker: "Success"
- [ ] Logs show: "celery@worker ready"
- [ ] Environment variables set: REDIS_URL (DB 1)

### ✅ Services Can Reach Redis
- [ ] knowledgebase_ingestion logs show: `✅ [REDIS] Connection test successful`
- [ ] website_crawling logs show: `✅ [REDIS] Connection test successful`

### ✅ File Upload Working
- [ ] Upload file via UI
- [ ] File worker logs show: `Received task: process_file_upload_task`
- [ ] Database shows: status='pending' → 'processing' → 'completed'
- [ ] File appears in search results

### ✅ Website Scraping Working
- [ ] Add website URL via UI
- [ ] Web worker logs show: `Received task: scrape_website_task`
- [ ] Database shows: status='pending' → 'processing' → 'completed'
- [ ] Website appears in search results

---

## Monitoring Commands

### Check Worker Status

```bash
# From any container with Celery installed
celery -A knowledgebase_ingestion.celery_app inspect active
# Returns: {worker: [list of active tasks]}

celery -A website_crawling.celery_app inspect stats
# Returns: {worker: concurrency, pool, etc.}
```

### Check Queue Depth

```bash
redis-cli LLEN celery:file_processing
redis-cli LLEN celery:web_crawling

# Should see:
# (integer) 0   <- Queue empty, all tasks processed
# (integer) 5   <- 5 tasks waiting
```

### Monitor in Real-time

```bash
# Watch file queue
watch -n 1 'redis-cli LLEN celery:file_processing'

# Watch web queue
watch -n 1 'redis-cli LLEN celery:web_crawling'
```

### View Worker Logs

**File Worker:**
```
Railway → celery-file-worker → Logs
# Filter for: [INFO], [ERROR], [FAILED]
```

**Web Worker:**
```
Railway → celery-web-worker → Logs
# Filter for: [INFO], [ERROR], [FAILED]
```

---

## Performance Tuning

### If File Upload is Slow

Check file worker logs:
```
[knowledgebase_ingestion.tasks.process_file_upload_task] started
[knowledgebase_ingestion.tasks.process_file_upload_task] succeeded
# Compare timestamps to see duration
```

**Solutions:**
1. Increase concurrency (in celery-file-worker/railway.toml):
   ```
   startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 4"
   ```

2. Check Docling service is running
   ```
   Railway → docling_service → status should be "Success"
   ```

3. Check Gemini API availability (may be rate-limited)

### If Website Scraping is Slow

Web worker concurrency is intentionally 1 (single concurrent task).

**Solutions:**
1. Monitor queue depth - if many sites queued, add second worker:
   ```
   railway up --name celery-web-worker-2
   ```

2. Increase task timeout if hitting 2-hour limit:
   In `website_crawling/celery_app.py`:
   ```python
   task_time_limit = 14400  # 4 hours instead of 2 hours
   ```

3. Check if sitemaps are too large (1000+ pages)

### If Workers Consuming Too Much Memory

Reduce max-tasks-per-child (restart worker process more frequently):

**File worker:**
```
--max-tasks-per-child=500
```

**Web worker:**
```
--max-tasks-per-child=50
```

More frequent restarts = cleaner memory.

---

## Troubleshooting

### Workers Won't Start

**Check logs:**
```
Railway → celery-[file|web]-worker → Logs
# Look for: ImportError, ModuleNotFoundError, connection errors
```

**Common causes:**
- Missing environment variables (REDIS_URL, GEMINI_API_KEY)
- Redis not deployed yet
- Wrong Redis URL format
- Database not initialized

**Fix:**
1. Verify all env vars set
2. Verify Redis service running
3. Verify REDIS_URL format is correct
4. Restart worker service

### Tasks Not Processing

**Check 1: Worker alive**
```bash
celery -A knowledgebase_ingestion.celery_app inspect active
# Should return worker details, not empty
```

**Check 2: Queue has tasks**
```bash
redis-cli LLEN celery:file_processing
# Should be > 0 if tasks queued
```

**Check 3: Worker logs**
```
Railway → celery-file-worker → Logs
# Look for error messages
```

**Fix:**
- Restart worker: Railway → Service → Redeploy
- Check environment variables
- Verify Redis connection

### Timeouts

**For file uploads:**
- Increase timeout in `knowledgebase_ingestion/celery_app.py`
- Check file size (very large files may take > 30 min)

**For website scraping:**
- Increase timeout in `website_crawling/celery_app.py`
- Check sitemap size (1000+ pages may take > 2 hours)

### High Memory Usage

- Reduce max-tasks-per-child (restart more frequently)
- Reduce concurrency (less simultaneous processing)
- Check if large files/sitemaps are causing memory spikes

---

## Rollback

If workers have issues, you can temporarily disable async processing:

In `knowledgebase_ingestion/service/ingestion_service.py`, comment out:
```python
# task = process_file_upload_task.delay(...)  # Disable worker dispatch
```

This will process files synchronously (slower, but works without workers).

Then fix worker issues and re-enable.

---

## Next Steps

1. ✅ Commit changes
2. ✅ Deploy Redis (if not done)
3. ✅ Deploy celery-file-worker
4. ✅ Deploy celery-web-worker
5. ✅ Set environment variables
6. ✅ Verify logs show "celery@worker ready"
7. ✅ Test file upload
8. ✅ Test website scraping
9. Monitor performance

Everything is configured and ready to deploy! 🚀
