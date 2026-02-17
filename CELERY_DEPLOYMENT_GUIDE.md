# Celery + Redis Deployment Guide

This guide covers deploying the Celery-based async task queue for handling heavy file upload and website scraping workloads.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Services                          │
│  (File Upload / Website Scraping API Endpoints)             │
└────────────┬────────────────────────────────────────────────┘
             │
             │ 1. Creates DB record (status='pending')
             │ 2. Dispatches Celery task to Redis
             │
┌────────────▼────────────────────────────────────────────────┐
│                   Redis Message Broker                       │
│  (Queues: file_processing, web_crawling)                    │
└────────────┬────────────────────────────────────────────────┘
             │
    ┌────────┴─────────────────────────────────────────┐
    │                                                  │
┌───▼──────────────────────┐        ┌──────────────────▼──┐
│ Celery Worker Pool:      │        │ Celery Flower:      │
│ - File Processing        │        │ (Monitoring)        │
│ - Web Crawling           │        │ Port: 5555          │
│ (2 workers each)         │        │                     │
└───────────────────────────┘        └─────────────────────┘
    │
    │ 3. Process task
    │ 4. Update DB (status='completed' or 'failed')
    │
┌───▼──────────────────────────────────────────────────────────┐
│            PostgreSQL Database                               │
│  (Tracks processing_status for all uploads/scrapes)         │
└────────────────────────────────────────────────────────────────┘
```

## Local Development Setup

### 1. Install Requirements

```bash
# Navigate to knowledgebase_ingestion directory
pip install -r knowledgebase_ingestion/requirements.txt

# Navigate to website_crawling directory
pip install -r website_crawling/requirements.txt
```

### 2. Start Redis Locally

**Option A: Docker**
```bash
docker run -d \
  --name knowledgebot-redis \
  -p 6379:6379 \
  redis:7-alpine
```

**Option B: Homebrew (macOS)**
```bash
brew install redis
redis-server
```

**Option C: APT (Linux)**
```bash
sudo apt-get install redis-server
redis-server
```

### 3. Run Database Migrations

```bash
# Apply the migration to add processing_status columns
psql -d your_database_name -f migrations/001_add_processing_status.sql
```

### 4. Start Celery Workers

**Terminal 1: File Processing Worker**
```bash
cd knowledgebase_ingestion
celery -A knowledgebase_ingestion.celery_app worker \
  -Q file_processing \
  -l info \
  -c 2 \
  --max-tasks-per-child=1000
```

**Terminal 2: Web Crawling Worker**
```bash
cd website_crawling
celery -A website_crawling.celery_app worker \
  -Q web_crawling \
  -l info \
  -c 1 \
  --max-tasks-per-child=100
```

**Terminal 3: Celery Flower (Monitoring UI)**
```bash
celery -A knowledgebase_ingestion.celery_app flower \
  --broker=redis://localhost:6379/0 \
  --port=5555
```

Visit http://localhost:5555 to see task monitoring dashboard.

### 5. Start FastAPI Services

**Terminal 4: API Gateway**
```bash
cd api_gateway
uvicorn main:app --reload --port 8000
```

**Terminal 5: Knowledgebase Ingestion**
```bash
cd knowledgebase_ingestion
uvicorn main:app --reload --port 8001
```

**Terminal 6: Website Crawling**
```bash
cd website_crawling
uvicorn main:app --reload --port 8002
```

## Docker Compose Setup

### Quick Start

```bash
# Start all services with one command
docker-compose -f docker-compose.celery.yml up -d

# Check logs
docker-compose -f docker-compose.celery.yml logs -f

# Stop all services
docker-compose -f docker-compose.celery.yml down
```

### Services Started

- **Redis** (localhost:6379)
- **Celery File Worker** (Processes file_uploads)
- **Celery Web Worker** (Processes website_crawling)
- **Celery Flower** (Monitoring at localhost:5555)

## Railway.app Deployment

### 1. Create Redis Add-on

```bash
railway add
# Select Redis
```

### 2. Create Workers as Separate Services

**File Processing Worker:**
```bash
railway service add
# Name: knowledgebot-celery-file
# Start Command: celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2
```

**Web Crawling Worker:**
```bash
railway service add
# Name: knowledgebot-celery-web
# Start Command: celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 1
```

### 3. Set Environment Variables

For both worker services, set:
```
REDIS_URL=<from Railway Redis>
DATABASE_URL=<from Railway Postgres>
GEMINI_API_KEY=<your key>
```

### 4. Deploy

```bash
git push origin main
# Railway auto-deploys changes

# Monitor logs
railway logs -s knowledgebot-celery-file
railway logs -s knowledgebot-celery-web
```

### 5. View Task Status

Visit Railway's dashboard to see:
- Worker uptime and health
- Task execution metrics
- Error logs

Optional: Use Celery Flower monitoring (deploy as separate service)

## Environment Configuration

### Redis Connection

Set `REDIS_URL` environment variable:
```bash
# Local development
export REDIS_URL=redis://localhost:6379/0  # File processing
export REDIS_URL=redis://localhost:6379/1  # Web crawling

# Railway
REDIS_URL=redis://<user>:<password>@<host>:<port>/<db>
```

### Database Connection

Set `DATABASE_URL` environment variable:
```bash
# PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/knowledgebot
```

### Task Timeouts

**File Processing:**
- Soft timeout: 30 minutes (1800 seconds)
- Hard timeout: 31.67 minutes (1900 seconds)
- Max retries: 2

**Web Crawling:**
- Soft timeout: 2 hours (7200 seconds)
- Hard timeout: 2 hours 5 minutes (7300 seconds)
- Max retries: 2

Adjust in `celery_app.py` if needed:
```python
celery_app.conf.update(
    task_soft_time_limit=1800,
    task_time_limit=1900,
)
```

## Database Migration

### Run Migration Script

```bash
# Single database
psql -d knowledgebot -f migrations/001_add_processing_status.sql

# Specific host/port
psql -h localhost -p 5432 -d knowledgebot -U postgres -f migrations/001_add_processing_status.sql

# Railway database
psql postgresql://user:password@host:port/database -f migrations/001_add_processing_status.sql
```

### Manual Migration (if needed)

Connect to database and run:
```sql
-- Add columns to file_uploads
ALTER TABLE file_uploads
ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN IF NOT EXISTS error_message TEXT,
ADD CONSTRAINT valid_file_processing_status CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'));

-- Add indexes to file_uploads
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_status
ON file_uploads(processing_status);

CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_pending
ON file_uploads(processing_status)
WHERE processing_status IN ('pending', 'processing');

-- Add columns to scraped_websites
ALTER TABLE scraped_websites
ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN IF NOT EXISTS error_message TEXT,
ADD CONSTRAINT valid_website_processing_status CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'));

-- Add indexes to scraped_websites
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_status
ON scraped_websites(processing_status);

CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_pending
ON scraped_websites(processing_status)
WHERE processing_status IN ('pending', 'processing');
```

## Monitoring and Troubleshooting

### Check Task Queue Status

```bash
# Using Celery inspect
celery -A knowledgebase_ingestion.celery_app inspect active

celery -A knowledgebase_ingestion.celery_app inspect stats

celery -A knowledgebase_ingestion.celery_app inspect active_queues
```

### View Task Results

```bash
# Get task result
celery -A knowledgebase_ingestion.celery_app result <task_id>
```

### Clear Failed Tasks

```bash
# WARNING: Purges all tasks in queue
celery -A knowledgebase_ingestion.celery_app purge
```

### Monitor Processing Status in Database

```sql
-- Check pending/processing files
SELECT id, original_filename, processing_status, error_message, updated_at
FROM file_uploads
WHERE processing_status IN ('pending', 'processing')
ORDER BY updated_at DESC;

-- Check failed files
SELECT id, original_filename, error_message, updated_at
FROM file_uploads
WHERE processing_status = 'failed'
ORDER BY updated_at DESC;

-- Check pending/processing websites
SELECT id, original_url, processing_status, error_message, updated_at
FROM scraped_websites
WHERE processing_status IN ('pending', 'processing')
ORDER BY updated_at DESC;
```

## Performance Tuning

### Worker Concurrency

```bash
# File processing (can handle more concurrent tasks)
celery -A knowledgebase_ingestion.celery_app worker -c 4

# Web crawling (reduce for heavy workloads)
celery -A website_crawling.celery_app worker -c 1
```

### Prefetch Multiplier

Lower = workers wait for tasks to finish before accepting new ones (good for long-running tasks)

```bash
celery -A knowledgebase_ingestion.celery_app worker --prefetch-multiplier=1
```

### Time Limits

Adjust soft/hard timeouts in `celery_app.py`:
```python
celery_app.conf.update(
    task_soft_time_limit=1800,   # Soft timeout (warning)
    task_time_limit=1900,        # Hard timeout (kill task)
)
```

## Health Checks

### Redis Health

```bash
redis-cli ping
# Should return: PONG
```

### Worker Health

```bash
celery -A knowledgebase_ingestion.celery_app inspect ping
# Should list all active workers
```

### Database Health

```bash
psql -c "SELECT 1"
# Should return: 1
```

## Common Issues

### Redis Connection Refused

**Problem:** `ConnectionError: Error -2 connecting to localhost:6379`

**Solution:**
```bash
# Check if Redis is running
redis-cli ping

# If not, start Redis
redis-server

# Or via Docker
docker run -p 6379:6379 redis:7-alpine
```

### Celery Worker Not Picking Up Tasks

**Problem:** Tasks stuck in queue

**Solution:**
```bash
# Verify Redis connection
celery -A knowledgebase_ingestion.celery_app inspect ping

# Check active workers
celery -A knowledgebase_ingestion.celery_app inspect active

# Restart worker
# Kill process and restart
pkill -f "celery worker"
celery -A knowledgebase_ingestion.celery_app worker -l info
```

### Task Timeout

**Problem:** `Task timed out after X seconds`

**Solution:**
- Increase `task_soft_time_limit` and `task_time_limit` in `celery_app.py`
- Optimize task logic (reduce processing time)
- Increase worker concurrency for load distribution

### Database Constraint Violation

**Problem:** `constraint "valid_file_processing_status" is violated`

**Solution:**
- Run migration script: `psql -f migrations/001_add_processing_status.sql`
- Verify constraint exists: `\d file_uploads`

## Next Steps

1. **Test locally** - Run full stack locally to verify setup
2. **Deploy to Railway** - Follow Railway deployment steps above
3. **Monitor in production** - Use Flower or Railway logs
4. **Optimize** - Adjust worker concurrency and timeouts based on load
5. **Scale** - Add more workers if needed

## API Usage

### Start File Upload

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
    "processing_status": "pending",
    "task_id": "abc-def-123"
  }
}
```

### Poll Status

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8001/status/123
```

Response:
```json
{
  "processing_status": "processing",
  "error_message": null,
  "updated_at": "2026-02-17T10:05:30Z"
}
```

## Further Reading

- [Celery Documentation](https://docs.celeryproject.io/)
- [Flower Monitoring](https://flower.readthedocs.io/)
- [Redis Docker](https://hub.docker.com/_/redis)
- [Railway Docs](https://docs.railway.app/)
