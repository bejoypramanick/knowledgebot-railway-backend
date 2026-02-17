# Celery Web Crawling Worker

This service processes async website scraping tasks for the knowledge base.

## Purpose

Executes `scrape_website_task` from the `web_crawling` queue:
- Crawls website URLs using Crawl4AI
- Handles sitemaps (XML parsing + hierarchical extraction)
- Converts content to markdown using Docling service
- Uploads to Gemini FileSearch
- Updates database with processing status and hierarchy

## Queue Configuration

| Setting | Value |
|---------|-------|
| **Service** | website_crawling |
| **Queue** | web_crawling |
| **Redis DB** | 1 |
| **Concurrency** | 1 worker process |
| **Task Timeout** | 2 hours |
| **Max Tasks/Child** | 100 |

## Why Concurrency = 1?

Website scraping is resource-intensive:
- **Crawl4AI**: Launches browser, renders JavaScript, takes screenshots
- **Large sitemaps**: Can have 1000s of pages, each requiring a request
- **Docling conversion**: ML models for document layout analysis
- **Gemini uploads**: Network I/O intensive

Running 2+ concurrent tasks would:
- Cause memory exhaustion (multiple browser instances)
- Slow down each task significantly
- Increase timeout risks
- Degrade performance unpredictably

**Single concurrency ensures:**
- One website fully completed before next starts
- Predictable resource usage
- No timeouts
- Reliable processing

## Deployment

### Railway

```bash
# Deploy from root directory
cd knowledgebot-railway-backend
railway up --name celery-web-worker
```

### Local Development

```bash
# Terminal 1: Start Redis (DB 1)
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 2: Start worker
celery -A website_crawling.celery_app worker \
  -Q web_crawling \
  -l info \
  -c 1 \
  --max-tasks-per-child=100
```

## Environment Variables

Set these in Railway dashboard for the service:

```
REDIS_URL=redis://redis.railway.internal:6379/1
RAILWAY_POSTGRES_URL=postgresql://...
GEMINI_API_KEY=your-api-key
DOCLING_ENABLED=true
```

## Monitoring

### Check Worker Status

```bash
# From any service container
celery -A website_crawling.celery_app inspect active
celery -A website_crawling.celery_app inspect stats

# Check queue depth
redis-cli -n 1 LLEN celery:web_crawling
```

### View Logs

```
Railway Dashboard → celery-web-worker → Logs
```

**Expected startup logs:**
```
[config]
.> app:         website_crawling:14a91b0e6c
.> transport:   redis://redis.railway.internal:6379/1
.> results:     redis://redis.railway.internal:6379/1
.> concurrency: 1
.> task events: OFF (enable with -E)

[queues]
.> web_crawling exchange=web_crawling(direct) key=web_crawling

[tasks]
  . website_crawling.tasks.scrape_website_task

[2025-02-17 10:00:00,000: WARNING/MainProcess] celery@worker ready.
```

## Task Status Lifecycle

```
User adds website URL
    ↓
Database: status='pending'
    ↓
Worker picks up task
    ↓
Database: status='processing'
    ↓
Crawl → Extract → Convert → Upload to Gemini
    ↓
Database: status='completed' (or 'failed' if error)
```

## Website Processing Pipeline

### Single URL

```
1. Receive task: scrape_website_task(website_id, url, options)
   ↓
2. Crawl website with Crawl4AI:
   └─ Render JavaScript
   └─ Extract main content
   └─ Get markdown
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
   └─ parent_id = null (root level)
   ↓
6. Done! Website is searchable
```

### Sitemap XML

```
1. Receive task: scrape_website_task(website_id, sitemap_url, options)
   ↓
2. Parse sitemap.xml:
   ├─ Extract all URLs
   └─ Build parent-child hierarchy (if nested sitemaps)
   ↓
3. For each URL in sitemap:
   ├─ Crawl with Crawl4AI
   ├─ Convert to markdown
   ├─ Upload to Gemini
   ├─ Store in database with:
   │  ├─ parent_id (parent URL's ID)
   │  ├─ depth (nesting level)
   │  └─ processing_status
   └─ Loop
   ↓
4. Create tree structure:
   ```
   Sitemap Root (ID: 1, depth: 0)
   ├─ /page1 (ID: 2, parent_id: 1, depth: 1)
   ├─ /page2 (ID: 3, parent_id: 1, depth: 1)
   │  ├─ /page2/sub1 (ID: 4, parent_id: 3, depth: 2)
   │  └─ /page2/sub2 (ID: 5, parent_id: 3, depth: 2)
   └─ /page3 (ID: 6, parent_id: 1, depth: 1)
   ```
   ↓
5. Done! All pages searchable with hierarchy preserved
```

## Performance Tuning

### Monitor Completion Time

Each task execution shows in logs:
```
[2025-02-17 10:00:00] Task scrape_website_task[abc123] started
[2025-02-17 10:05:30] Task scrape_website_task[abc123] succeeded
# Took ~5.5 minutes for single page
```

Large sitemaps may take full 2 hours (task timeout).

### If Tasks Timeout (Hit 2-hour limit)

**Likely causes:**
- Sitemap has 1000s+ of pages
- Slow website (server delays)
- Network issues

**Solutions:**

1. **Increase timeout** (in `website_crawling/celery_app.py`):
```python
task_soft_time_limit = 10800  # 3 hours
task_time_limit = 10900       # 3 hours 1.67 min
```

2. **Increase concurrency** (only if resources available):
```
startCommand = "celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 2"
#                                                                                      ^ increase
```

⚠️ **WARNING:** Increasing concurrency above 1 risks:
- Memory exhaustion (browser instances)
- Network saturation
- Resource timeouts
- Only do if you have tested locally

### Reduce Max Tasks Per Child

```
--max-tasks-per-child=50
#                       ^ restart after 50 tasks instead of 100
```

More frequent restarts = cleaner process, prevents memory leaks

## Troubleshooting

### Worker Won't Start

**Check 1: Redis connection (DB 1)**
```bash
redis-cli -n 1 ping
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
celery -A website_crawling.celery_app inspect active
# Should show: "OK" and list of active tasks
```

**Check 2: Queue depth**
```bash
redis-cli -n 1 LLEN celery:web_crawling
# Should be decreasing if worker is processing
```

**Check 3: Worker logs**
```
Railway → celery-web-worker → Logs
# Look for: [ERROR] or [FAILED] messages
```

### Memory Usage Growing

**Cause:** Browser instances not cleaning up

**Solution:** Restart worker

```
Railway → celery-web-worker → Redeploy
```

This gracefully shuts down current task, restarts process.

### Timeouts on Large Sitemaps

**Check:** Sitemap size

```bash
# Count pages in sitemap
curl -s https://example.com/sitemap.xml | grep -o '<loc>' | wc -l
# If > 500, may take 1+ hours
```

**Solution:** Increase timeout as shown in "Performance Tuning" section

## Crawl4AI Configuration

The worker uses Crawl4AI with these settings:

```python
async_crawl4ai = AsyncWebCrawler(
    browser_type="chromium",
    headless=True,
    viewport_height=1080,
    viewport_width=1920
)

result = await async_crawl4ai.arun(
    url=url,
    bypass_cache=True,
    fit_markdown=True,
    extraction_strategy=strategy
)
```

This:
- Uses Chromium headless browser
- Renders JavaScript (dynamic content)
- Extracts structured markdown
- Caches disabled (always fresh content)

## Related Services

- **website_crawling** (8002): Dispatches website scraping tasks
- **redis** (6379): Message broker (DB 1: web_crawling queue)
- **PostgreSQL**: Stores task status, URLs, and hierarchy
- **Docling Service** (8004): Converts content to markdown
- **Gemini FileSearch**: Stores and indexes website content
- **Crawl4AI**: Browser automation and content extraction

## Scaling

### Add More Workers

Deploy multiple instances:
```bash
railway up --name celery-web-worker-2
```

All workers listen to same queue, so tasks are distributed.

⚠️ **WARNING:** Only increase if you:
1. Have tested locally with multiple workers
2. Verified memory doesn't run out
3. Verified network doesn't get saturated

### Monitor All Workers

```bash
celery -A website_crawling.celery_app inspect active_queues
# Shows all connected workers and their queues
```

## Maintenance

### Clear Stuck Tasks

```bash
# Purge entire queue (use carefully!)
redis-cli -n 1 DEL celery:web_crawling

# Or clear specific task
redis-cli -n 1 LRANGE celery:web_crawling 0 -1  # list tasks
redis-cli -n 1 LREM celery:web_crawling 1 "task_id"  # remove task
```

### Restart Worker

```
Railway → celery-web-worker → Redeploy
```

This restarts the service gracefully (tries to finish current task before shutting down).

### Monitor Resource Usage

```
Railway → celery-web-worker → Metrics
# Watch CPU and Memory during large sitemap crawls
```

## Cost & Performance

| Metric | Value |
|--------|-------|
| **Memory** | ~512MB-1GB (browser instances) |
| **CPU** | Variable (intensive during crawling) |
| **Network** | Depends on sitemap size (each URL = HTTP request + Gemini upload) |
| **Cost Impact** | ~$10-15/month per worker instance |

## Expected Performance

| Task Type | Typical Duration | Examples |
|-----------|-----------------|----------|
| Single page | 2-5 minutes | Blog post, landing page |
| 10-page sitemap | 15-30 minutes | Small documentation site |
| 50-page sitemap | 1-1.5 hours | Medium site |
| 200+ page sitemap | 1.5-2 hours | Large documentation (hits timeout) |

## Next Steps

1. Configure `REDIS_URL` environment variable (DB 1)
2. Deploy to Railway: `railway up --name celery-web-worker`
3. Monitor logs for successful startup
4. Test by adding a website URL
5. Verify database status changes: `pending` → `processing` → `completed`
6. For sitemaps, verify hierarchy created (parent_id, depth columns)
