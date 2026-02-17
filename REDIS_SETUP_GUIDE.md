# Redis Setup Guide for Railway

## Problem Statement

Your current Railway deployment is **missing Redis**, which is required for Celery task queue:

```
knowledgebase_ingestion → process_file_upload_task.delay()
                          ↓ (tries to publish to Redis)
                          ❌ CONNECTION REFUSED (Redis not found)

website_crawling → scrape_website_task.delay()
                   ↓ (tries to publish to Redis)
                   ❌ CONNECTION REFUSED (Redis not found)
```

**Impact:** Async tasks never execute. Files remain stuck in "pending" status forever.

---

## Solution: Add Redis Service to Railway

### Step 1: Review the New Redis Files

Created three new files:
1. **`redis/Dockerfile`** - Redis 7 Alpine image with persistence
2. **`redis/railway.toml`** - Railway service configuration
3. **`redis/README.md`** - Complete Redis documentation

### Step 2: Commit the Redis Service Configuration

```bash
cd /path/to/knowledgebot-railway-backend
git add redis/
git commit -m "Add Redis service configuration for Celery task queue

- Redis 7 Alpine image (lightweight, ~5MB)
- AOF persistence for data durability
- 512MB memory with LRU eviction
- Database 0: file processing tasks
- Database 1: web crawling tasks
- Health checks enabled
- ON_FAILURE restart policy

Fixes: Async tasks now have message broker on Railway"
git push
```

### Step 3: Deploy Redis on Railway

**Option A: Using Railway CLI**
```bash
# Install Railway CLI if needed
npm i -g @railway/cli

# Login to Railway
railway login

# Link to your project
railway link

# Add new service from current directory
railway up --name redis
```

**Option B: Using Railway Dashboard**

1. Go to your Railway project dashboard
2. Click "New Service"
3. Select "GitHub Repo" → Choose this repo
4. Configure:
   - Name: `redis`
   - Root Directory: `redis`
   - Dockerfile Path: `redis/Dockerfile`
5. Click "Deploy"

**Option C: Using railway.toml**

Railway will automatically detect and deploy `redis/railway.toml` when pushing to main branch.

### Step 4: Configure Environment Variables

Once Redis deploys on Railway:

1. **Get Redis URL from Railway:**
   - Go to Redis service details
   - Look for "DATABASE_URL" or similar connection string
   - Format: `redis://[username]:[password]@redis.railway.internal:6379/0`

2. **Add to knowledgebase_ingestion service:**
   - Variables tab
   - Add: `REDIS_URL=redis://redis.railway.internal:6379/0`

3. **Add to website_crawling service:**
   - Variables tab
   - Add: `REDIS_URL=redis://redis.railway.internal:6379/1`

### Step 5: Restart Services

After Redis is running and env vars are set:

1. Restart `knowledgebase_ingestion` service
2. Restart `website_crawling` service

Watch logs for:
```
✅ [CELERY_APP] Initializing Celery
✅ [REDIS] Connection test successful
```

---

## Verification Checklist

After deployment, verify everything works:

### ✅ Redis Service Running
- [ ] Redis service shows "Success" in Railway dashboard
- [ ] No memory/CPU warnings
- [ ] Health checks passing

### ✅ Services Connected
- [ ] Knowledgebase service logs show: `✅ [REDIS] Connection test successful`
- [ ] Website crawling service logs show: `✅ [REDIS] Connection test successful`
- [ ] No "Connection refused" errors in logs

### ✅ Tasks Processing
- [ ] Upload a file to knowledgebase
- [ ] Check database: `SELECT * FROM file_uploads ORDER BY id DESC LIMIT 1;`
- [ ] Status should change: `pending` → `processing` → `completed`
- [ ] File should appear in Gemini FileSearch store

### ✅ Website Scraping
- [ ] Add a website URL to crawl
- [ ] Check database: `SELECT * FROM scraped_websites ORDER BY id DESC LIMIT 1;`
- [ ] Status should cycle: `pending` → `processing` → `completed`
- [ ] Website should be indexed and searchable

---

## Architecture After Setup

```
┌─────────────────────── RAILWAY ───────────────────────┐
│                                                         │
│  ┌─────────────────┐      ┌──────────────────────┐   │
│  │ knowledgebase   │      │ website_crawling     │   │
│  │ ingestion       │──┐   │                      │   │
│  │ (port 8001)     │  │   │ (port 8002)          │   │
│  │                 │  │   │                      │   │
│  │ .delay()───────┐│   │ .delay()────────┐      │   │
│  └─────────────────┘│   │                │      │   │
│                     │   └──────────────────────┘   │
│                     │                               │
│                     ├──→ ┌─────────────────────┐   │
│                     │    │     REDIS           │   │
│                     │    │ (port 6379)         │   │
│                     └────│ DB 0: file_proc.    │   │
│                          │ DB 1: web_crawl     │   │
│                          └─────────────────────┘   │
│                                  ↓                  │
│                          ┌─────────────────────┐   │
│                          │   PostgreSQL        │   │
│                          │ (shared database)   │   │
│                          │                     │   │
│                          │ - file_uploads      │   │
│                          │ - scraped_websites  │   │
│                          │ - task status       │   │
│                          └─────────────────────┘   │
│                                                     │
│  Celery Workers (optional, for Railway):           │
│  ┌────────────────────────────────────────────┐  │
│  │ Celery Worker 1: file_processing queue     │  │
│  │ Celery Worker 2: web_crawling queue        │  │
│  │                                             │  │
│  │ (Or let Railway auto-scale based on queue) │  │
│  └────────────────────────────────────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Alternative: Managed Redis (Railway Add-on)

If Railway offers a managed Redis add-on:

1. In Railway dashboard → Marketplace
2. Search for "Redis" or "Cache"
3. Add to project
4. Auto-inject connection string to services

This would be simpler than managing your own Redis container.

---

## Monitoring Redis

### View Redis Logs
```bash
# In Railway dashboard
Services → redis → Logs
```

### Check Celery Workers
```bash
# In Railway dashboard
Services → knowledgebase-ingestion → Logs
# Look for: "📋 [TASK] Starting Celery task"

Services → website-crawling → Logs
# Look for: "📋 [TASK] Starting Celery task"
```

### Local Testing (Before Railway)

```bash
# Start full stack locally
docker-compose -f docker-compose.celery.yml up

# In another terminal, upload a file
curl -X POST http://localhost:8001/api/v1/knowledgebase/upload \
  -F "file=@test.pdf" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Watch Celery logs
docker-compose -f docker-compose.celery.yml logs -f celery-file-worker

# Watch Flower dashboard
open http://localhost:5555
```

---

## Troubleshooting

### Redis Service Won't Start
- Check Docker image: Should be `redis:7-alpine`
- Check port conflicts: 6379 should be available
- Check memory allocation: 512MB minimum

### Services Can't Connect to Redis
- Verify env var: `REDIS_URL` set correctly
- Check format: `redis://redis.railway.internal:6379/0` (for knowledgebase)
- Check Redis service status: Should show "Success"
- Restart services after changing env vars

### Tasks Still Showing "Pending"
- Check Redis connection in service logs
- Verify Celery workers are running
- Check worker logs: `docker logs celery-file-worker`
- Look for errors: `[ERROR]` in logs

### Memory Growing
- Check task failures: May be accumulating in queue
- Check Redis memory: `redis-cli INFO memory`
- Clear old tasks: `redis-cli FLUSHDB` (use with caution)

---

## Next Steps

1. **Commit and push** the `redis/` directory
2. **Deploy** Redis service on Railway
3. **Set environment variables** on both services
4. **Restart** services
5. **Verify** tasks process correctly
6. **(Optional) Add Celery workers** if tasks queue up

---

## Performance Notes

### Current Setup
- Async tasks dispatch immediately (milliseconds)
- Processing happens asynchronously (minutes/hours depending on file size)
- Database updated with status changes
- UI can poll status endpoint

### With Celery Workers
- If not running workers, tasks **queue up in Redis** waiting for execution
- Add workers to execute queued tasks
- Monitor queue depth in Flower or Redis

### Scaling
```
More files uploaded → More tasks queued → Need more workers
More websites crawled → More tasks queued → Need more workers

Solution: Add multiple Celery worker replicas on Railway
```
