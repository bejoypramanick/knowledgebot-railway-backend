# Do You Need Separate Celery Workers? YES!

## The Problem

Your current Railway setup:
```
✅ Redis service (to be deployed)
✅ FastAPI services (that dispatch tasks)
❌ MISSING: Celery workers (to execute tasks)
```

**What happens without workers:**

```
1. User uploads file
   ↓
2. API creates task: process_file_upload_task.delay(file_id, ...)
   ↓
3. Task published to Redis (DB 0: file_processing queue)
   ↓
4. Task sits in Redis queue... forever ⏳
   ↓
5. No worker to execute it
   ↓
6. Status stays "pending" indefinitely ❌
```

---

## Task Execution Flow (Currently Broken)

```
┌─────────────────────────────────────────────────────────┐
│  knowledgebase_ingestion (8001)                         │
│                                                          │
│  @router.post("/upload")                                │
│  async def upload_file():                               │
│      task = process_file_upload_task.delay(...)         │
│      └─ Returns immediately ✓                           │
│      └─ Task queued in Redis ✓                          │
│      └─ DB status = "pending" ✓                         │
│      └─ Response sent to client ✓                       │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ↓ (Task published to Redis)
        ┌──────────────────────┐
        │  REDIS (DB 0)        │
        │ file_processing queue│
        │                      │
        │ ┌──────────────────┐ │
        │ │ Task ID: abc123  │ │
        │ │ file_id: 456     │ │
        │ │ status: pending  │ │
        │ └──────────────────┘ │
        │                      │
        │ ❌ WAITING FOR WORKER│
        │    (NONE EXISTS!)    │
        └──────────────────────┘
                   │
                   ⏳ Task never executes
                   │
        ┌──────────────────────────────────────┐
        │  PostgreSQL                          │
        │  file_uploads table                  │
        │                                      │
        │  ID: 456                             │
        │  filename: document.pdf              │
        │  status: pending (FOREVER) ❌        │
        │  updated_at: 2025-02-17 10:00 AM    │
        └──────────────────────────────────────┘
```

---

## Solution: Add Celery Worker Services

You have 3 options:

### **Option 1: Separate Celery Worker Services (RECOMMENDED)**

Deploy dedicated worker services on Railway:

```
Railway Services:
├─ api_gateway (8000)
├─ knowledgebase_ingestion (8001)
├─ website_crawling (8002)
├─ chatbot_orchestration (8003)
├─ docling_service (8004)
├─ configuration (8005)
├─ health_monitoring (8006)
├─ redis (6379)
├─ celery-file-worker (processes file_processing queue)  ✨ NEW
└─ celery-web-worker (processes web_crawling queue)      ✨ NEW
```

**Pros:**
- ✅ Dedicated workers scale independently
- ✅ Can adjust concurrency per worker
- ✅ Easy to monitor (separate services)
- ✅ Can restart without affecting APIs

**Cons:**
- Additional Railway services (cost)
- More services to manage

---

### **Option 2: Workers in Same Service Containers**

Run workers alongside FastAPI in same container:

```
Container Image (knowledgebase_ingestion):
├─ FastAPI app (port 8001)
└─ Celery worker process (background)
```

**Pros:**
- ✅ Single container per service
- ✅ Simpler deployment
- ✅ Lower cost (fewer services)

**Cons:**
- ❌ CPU contention (API + worker on same process)
- ❌ Hard to scale workers independently
- ❌ Restart API = restart worker
- ❌ Not recommended for production

---

### **Option 3: Use Shared Worker Pool**

Single Celery worker service for all queues:

```
celery-worker-pool:
├─ Listens to: file_processing queue
├─ Listens to: web_crawling queue
├─ Worker processes: 4-8 concurrent tasks
└─ Scales all queues together
```

**Pros:**
- ✅ Single worker service
- ✅ Simpler than separate workers

**Cons:**
- ❌ One queue slow = all queues slow
- ❌ Can't tune per-queue performance
- ❌ Large sitemaps block file uploads

---

## Recommendation: Option 1 (Separate Workers)

Here's why:

1. **File Processing** (30 min timeout)
   - May need 2-4 concurrent processes
   - Concurrency: 2-4

2. **Web Crawling** (2 hour timeout)
   - Large sitemaps consume CPU/memory
   - Concurrency: 1-2

**If they share workers:**
- One large sitemap blocks all file uploads
- Unpredictable performance

**With separate workers:**
- Timeout uploading a file? Just restart file worker
- Scraping slow? Increase web worker concurrency
- Independent scaling

---

## What to Deploy

### New Files Needed:

1. **`celery-worker/railway.toml`** - Configuration
2. **`celery-worker/Dockerfile`** - Uses existing `Dockerfile.celery`
3. **Two separate `railway.toml` files** (one per worker type)

OR simpler approach:

Use existing `Dockerfile.celery` + create two `railway.toml` files:
- `celery-file-worker/railway.toml`
- `celery-web-worker/railway.toml`

---

## Current Task Execution Flow (Broken)

```
File Upload
├─ Create DB record: status='pending'
├─ Dispatch task: task.delay(file_id, ...)
├─ Task → Redis queue
├─ Return response to client: "queued"
│
└─ Wait for worker to execute...
   ❌ NO WORKER = TASK NEVER EXECUTES
   ❌ Status stuck on "pending"
   ❌ File never uploaded to Gemini
   ❌ File never searchable
```

**With Celery Worker:**

```
File Upload
├─ Create DB record: status='pending'
├─ Dispatch task: task.delay(file_id, ...)
├─ Task → Redis queue
├─ Return response to client: "queued"
│
└─ Celery Worker
   ├─ Polls Redis queue
   ├─ Picks up task
   ├─ Update DB: status='processing'
   ├─ Extract content (HTML/Docling)
   ├─ Upload to Gemini
   ├─ Update DB: status='completed'
   └─ Task done ✅
```

---

## Celery Worker Architecture

### How Workers Connect

```
celery-file-worker
├─ Connects to Redis (redis.railway.internal:6379/0)
├─ Listens to: file_processing queue
├─ Concurrency: 2 workers (processes 2 tasks in parallel)
├─ Max tasks per child: 1000 (restart after 1000 tasks)
└─ Task timeout: 30 minutes (soft + hard limits)

celery-web-worker
├─ Connects to Redis (redis.railway.internal:6379/1)
├─ Listens to: web_crawling queue
├─ Concurrency: 1 worker (large sitemaps consume resources)
├─ Max tasks per child: 100 (restart after 100 tasks)
└─ Task timeout: 2 hours (soft + hard limits)
```

### Task Pickup Logic

```
Worker startup:
1. Connect to Redis
2. Subscribe to assigned queue
3. Poll for new tasks every 1 second
4. When task arrives:
   ├─ Execute task function
   ├─ Update database status
   ├─ Store result in Redis
5. Loop back to step 3
```

---

## What Happens with Different Scenarios

### Scenario A: No Workers (Current)

```
File uploaded
└─ Task.delay() → Redis
   └─ Status: pending
      └─ 🔴 STUCK FOREVER (no worker)
      └─ UI shows "Uploading..." indefinitely
      └─ File never appears in search
```

### Scenario B: One Shared Worker

```
File uploaded            Website URL added
└─ Task A → Queue 0      └─ Task B → Queue 1
   ├─ Worker picks up Task A
   ├─ Processing (30 min)
   │
   └─ During this time:
      └─ Task B sits in Queue 1 (waiting)
      └─ User sees "uploading..." for website
      └─ Performance unpredictable
```

### Scenario C: Separate Workers (RECOMMENDED)

```
File uploaded            Website URL added
└─ Task A → Queue 0      └─ Task B → Queue 1
   ├─ File Worker        ├─ Web Worker
   ├─ Processing (30 min) ├─ Processing (2 hours)
   ├─ Independent        ├─ Independent
   └─ Concurrent ✅      └─ No blocking ✅
```

---

## Implementation Steps

### Step 1: Create Worker Service Structure

```
celery-file-worker/
├─ railway.toml
├─ Dockerfile (symlink to ../Dockerfile.celery)
└─ entrypoint.sh (optional)

celery-web-worker/
├─ railway.toml
├─ Dockerfile (symlink to ../Dockerfile.celery)
└─ entrypoint.sh (optional)
```

### Step 2: Configure railway.toml for File Worker

```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."

[deploy]
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5

# Start command for file processing queue
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2"

healthcheckPath = "/health"
healthcheckTimeout = 300
```

### Step 3: Configure railway.toml for Web Worker

```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."

[deploy]
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5

# Start command for web crawling queue
startCommand = "celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 1"

healthcheckPath = "/health"
healthcheckTimeout = 300
```

### Step 4: Deploy to Railway

```bash
railway up --name celery-file-worker
railway up --name celery-web-worker
```

### Step 5: Set Environment Variables

Both workers need:
- `REDIS_URL` - Connection to Redis
- `DATABASE_URL` or `RAILWAY_POSTGRES_URL` - Connection to PostgreSQL
- `GEMINI_API_KEY` - For Gemini integration

---

## Monitoring Workers

### Via Flower (Development)

```
docker-compose -f docker-compose.celery.yml up

# Visit http://localhost:5555
# Shows:
# - Active workers
# - Task queues and depth
# - Task history and stats
# - Real-time execution
```

### Via Railway Logs

```
Services → celery-file-worker → Logs
Services → celery-web-worker → Logs

# Look for:
[2025-02-17 10:00:00] Ready to accept tasks!
[2025-02-17 10:00:05] Received task: process_file_upload_task[abc123]
[2025-02-17 10:00:35] Task process_file_upload_task[abc123] succeeded
```

### Via Redis CLI

```bash
# Check queue depth
redis-cli LLEN celery:file_processing
redis-cli LLEN celery:web_crawling

# Monitor in real-time
watch -n 1 'redis-cli LLEN celery:file_processing && redis-cli LLEN celery:web_crawling'
```

---

## Cost Implications (Railway)

| Component | Cost | Notes |
|-----------|------|-------|
| API services (7) | Baseline | Already deployed |
| Redis | + Small | ~512MB memory |
| Celery file-worker | + Medium | 2 concurrency, always running |
| Celery web-worker | + Medium | 1 concurrency, always running |

**Total:** +2 worker services for dedicated queue processing

---

## Troubleshooting

### Tasks Still Not Executing

Check:
1. ✅ Redis running: `redis-cli ping`
2. ✅ Redis connection in worker: `celery inspect active`
3. ✅ Worker process alive: `ps aux | grep celery`
4. ✅ Queue depth: `redis-cli LLEN celery:file_processing`

### Worker Crashes

Check logs:
```
railway logs celery-file-worker
# Look for: ImportError, connection refused, missing env vars
```

### Tasks Slow

Increase worker concurrency:
```
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -c 4"
#                                                                                        ^ increase
```

### Out of Memory

Worker consuming too much RAM:
```
# Restart worker after fewer tasks
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -c 2 --max-tasks-per-child=500"
#                                                                                                                    ^ decrease
```

---

## Summary

| Aspect | Answer |
|--------|--------|
| **Do you need Celery workers?** | ✅ YES - essential |
| **Can you run without them?** | ❌ NO - tasks will never execute |
| **Recommended setup** | Separate workers per queue |
| **For file uploads** | celery-file-worker (concurrency: 2) |
| **For websites** | celery-web-worker (concurrency: 1) |
| **Why separate?** | Independent scaling, performance isolation |
| **Deployment method** | Create railway.toml for each worker |
| **Infrastructure needed** | Redis + 2 worker services |

**Next steps:**
1. Deploy Redis (see REDIS_SETUP_GUIDE.md)
2. Create worker service configurations
3. Deploy workers to Railway
4. Set environment variables
5. Verify task execution via logs

Without workers, your async tasks are broken. With workers, everything works as designed!
