# Redis Service for Celery Task Queue

## Overview

Redis serves as the message broker and result backend for Celery async task processing in knowledgebot-railway-backend.

**Used by:**
- `knowledgebase_ingestion` service - File processing tasks
- `website_crawling` service - Website scraping tasks

**Two separate Redis databases:**
- Database 0: File processing queue (`file_processing`)
- Database 1: Website crawling queue (`web_crawling`)

## Deployment on Railway

### 1. Add Redis Service to Railway

Railway uses `railway.toml` for service configuration. The included `railway.toml` configures:

- **Docker image:** redis:7-alpine (lightweight, ~5MB)
- **Memory limit:** 512MB (adjust based on task volume)
- **Persistence:** Enabled (AOF - Append Only File)
- **Eviction policy:** allkeys-lru (remove least-recently-used keys when full)
- **Restart policy:** ON_FAILURE with 5 retries

### 2. Configure Environment Variables

Set these on Railway for services that use Celery:

**knowledgebase_ingestion service:**
```
REDIS_URL=redis://<username>:<password>@<redis-host>:<port>/0
```

**website_crawling service:**
```
REDIS_URL=redis://<username>:<password>@<redis-host>:<port>/1
```

**Format on Railway:**
```
redis://[username]:[password]@redis.railway.internal:6379/0
```

Or if Redis has no auth:
```
redis://redis.railway.internal:6379/0
```

### 3. Internal Service URL

Once deployed, Redis is accessible via Railway's internal network:
```
redis.railway.internal:6379
```

All services (`knowledgebase_ingestion`, `website_crawling`) connect via this internal URL.

## Local Development

### Option A: Use Docker Compose with Celery Workers

```bash
docker-compose -f docker-compose.celery.yml up
```

This includes:
- Redis service (port 6379)
- Celery file processing worker
- Celery web crawling worker
- Flower monitoring UI (port 5555)

### Option B: Run Redis Standalone

```bash
docker run -d \
  -p 6379:6379 \
  -v redis-data:/data \
  --name knowledgebot-redis \
  redis:7-alpine \
  redis-server --appendonly yes
```

Then start services normally:
```bash
# Terminal 1
python -m uvicorn knowledgebase_ingestion.main:app --reload --port 8001

# Terminal 2
python -m uvicorn website_crawling.main:app --reload --port 8002

# Terminal 3 - Celery worker for file processing
celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info

# Terminal 4 - Celery worker for web crawling
celery -A website_crawling.celery_app worker -Q web_crawling -l info
```

## Architecture

### Task Flow

```
1. Request to Service
   ↓
2. Service creates task
   task = process_file_upload_task.delay(file_id, ...)
   ↓
3. Task published to Redis queue
   - Knowledgebase: redis://localhost:6379/0 (file_processing queue)
   - Website Crawling: redis://localhost:6379/1 (web_crawling queue)
   ↓
4. Celery Worker polls Redis
   - Worker picks up task from queue
   - Executes async processing
   - Updates database status (pending → processing → completed/failed)
   ↓
5. Result stored in Redis
   - Key expires after 1 hour (result_expires=3600)
   ↓
6. Service polls database status
   - GET /api/v1/knowledgebase/status/{id}
   - Returns: pending, processing, completed, or failed
```

### Queue Routing

```
knowledgebase_ingestion.tasks.process_file_upload_task
  → Routes to: file_processing queue
  → Redis DB: 0
  → Worker: celery-file-worker
  → Timeout: 30 minutes

website_crawling.tasks.scrape_website_task
  → Routes to: web_crawling queue
  → Redis DB: 1
  → Worker: celery-web-worker
  → Timeout: 2 hours
```

## Configuration Details

### Redis Configuration (from Dockerfile)

```bash
redis-server \
  --appendonly yes              # Enable AOF persistence
  --maxmemory 512mb             # Memory limit
  --maxmemory-policy allkeys-lru # Eviction strategy
```

### Celery Configuration (from service celery_app.py)

| Setting | File Processing | Web Crawling |
|---------|-----------------|--------------|
| Broker | `redis://localhost:6379/0` | `redis://localhost:6379/1` |
| Result Backend | Same Redis | Same Redis |
| Serialization | JSON | JSON |
| Worker Prefetch | 4 tasks | 2 tasks |
| Max Tasks/Child | 1000 | 100 |
| Task Timeout | 1800s (30 min) | 7200s (2 hours) |
| Result Expires | 3600s (1 hour) | 3600s (1 hour) |

## Monitoring

### Flower Dashboard (Local Development)

When running `docker-compose.celery.yml`, Flower is available at:
```
http://localhost:5555
```

Shows:
- Active workers
- Task queues and rates
- Task history and statistics
- Real-time task execution

### Railway Production Monitoring

Check Redis logs in Railway dashboard:
```
Deployments → redis service → Logs
```

### Command Line Health Check

```bash
# Test Redis connection
redis-cli -h redis.railway.internal ping
# Response: PONG

# Check memory usage
redis-cli -h redis.railway.internal info memory

# Check queue length
redis-cli -h redis.railway.internal llen celery

# Get all keys
redis-cli -h redis.railway.internal keys "*"
```

## Troubleshooting

### Issue: Tasks not processing

**Check 1:** Redis connection
```bash
python -c "
import redis
r = redis.from_url('redis://localhost:6379/0')
r.ping()  # Should return True
"
```

**Check 2:** Celery worker running
```bash
# Should show active tasks
celery -A knowledgebase_ingestion.celery_app inspect active
```

**Check 3:** Database status
```sql
SELECT id, processing_status, created_at
FROM file_uploads
ORDER BY created_at DESC
LIMIT 5;
```

### Issue: Out of Memory

Increase Redis memory in:
1. `redis/Dockerfile` - Change `--maxmemory 512mb` to higher value
2. Railway deployment settings - Allocate more memory to Redis service

### Issue: Data Loss

Redis persistence is enabled (AOF mode):
- Data written to `/data/appendonly.aof`
- Restored on restart
- On Railway, ensure volume is mounted

## Performance Tuning

### For High Volume

**Increase worker capacity:**
```bash
# In redis/Dockerfile command line
--maxmemory 2gb  # Increase memory
```

**Increase Celery workers:**
```bash
# Add more worker replicas on Railway
# Or increase concurrency in docker-compose.celery.yml:
celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 4
```

### For Low Latency

**Reduce task timeout:**
```python
# In celery_app.py
task_soft_time_limit = 300  # 5 minutes for faster failure detection
```

## Security

### Railway (Production)

- Redis password should be set (if Railway supports it)
- Internal network only (redis.railway.internal)
- Not exposed to external traffic
- SSL/TLS recommended for production

### Local Development

- No password required
- Accessible only on localhost:6379
- AOF persistence enabled for data safety

## Maintenance

### Clearing Old Tasks

```bash
# Clear all task results
redis-cli -h redis.railway.internal FLUSHDB

# Clear specific key pattern
redis-cli -h redis.railway.internal KEYS "*task*" | xargs redis-cli DEL
```

### Backing Up Data

```bash
# Backup AOF file
docker exec knowledgebot-redis redis-cli BGSAVE
docker cp knowledgebot-redis:/data/dump.rdb ./redis-backup.rdb
```

### Monitoring Task Queues

```bash
# Watch queue depth in real-time
watch -n 1 'redis-cli LLEN celery'

# Monitor memory usage
watch -n 1 'redis-cli INFO memory | grep used'
```
