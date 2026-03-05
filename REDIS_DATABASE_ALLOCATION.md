# Redis Database Allocation

This document describes how Redis databases are allocated across the system.

## Database Allocation

| Database | Purpose | Environment Variable | Used By | Notes |
|----------|---------|---------------------|---------|-------|
| **DB 0** | File Processing (Celery) | `FILE_REDIS_URL` | celery-file-worker, knowledgebase-ingestion | Must include `/0` in URL |
| **DB 1** | Web Crawling (Celery) | `WEB_REDIS_URL` | celery-web-worker, knowledgebase-ingestion | Must include `/1` in URL |
| **DB 2** | *(Reserved/Unused)* | - | - | Available for future use |
| **DB 3** | Session Storage | `REDIS_URL` | api-gateway (session_store) | Auto-appended by code |
| **DB 4** | Pub/Sub (SSE Events) | `REDIS_URL` | configuration service (redis_pubsub_manager) | Auto-appended by code |

## Environment Variable Configuration

### For Services Using DB 0 and DB 1 (Celery Workers)

These services require **explicit database numbers in the URL**:

```bash
# File Processing (DB 0)
FILE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/0

# Web Crawling (DB 1)
WEB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/1
```

**Services that need these:**
- `celery-file-worker` - needs `FILE_REDIS_URL`
- `celery-web-worker` - needs `WEB_REDIS_URL`
- `knowledgebase-ingestion` - needs both `FILE_REDIS_URL` and `WEB_REDIS_URL`

### For Services Using DB 3 and DB 4 (Sessions and Pub/Sub)

These services use a **base URL without database number** - the code automatically appends the correct database:

```bash
# Base Redis URL (no database number)
REDIS_URL=redis://default:<password>@redis.railway.internal:6379
```

**Services that need this:**
- `api-gateway` - uses DB 3 for sessions (auto-appended)
- `configuration` - uses DB 4 for Pub/Sub (auto-appended)

**Important:** The code will strip any database number from `REDIS_URL` and append the correct one:
- `session_store.py` appends `/3` or uses `db=3` parameter
- `redis_pubsub_manager.py` strips existing DB and uses `db=4` parameter

## Code Behavior

### Session Store (DB 3)
```python
# From api_gateway/core/session_store.py
if redis_url.endswith('/3'):
    # Use URL as-is
    redis.from_url(redis_url)
else:
    # Append db=3 parameter
    redis.from_url(redis_url, db=3)
```

### Pub/Sub Manager (DB 4)
```python
# From shared/redis_pubsub_manager.py
if redis_url.endswith(('/0', '/1', '/2', '/3')):
    # Strip existing database number
    redis_url = redis_url.rsplit('/', 1)[0]

# Always use db=4
redis.from_url(redis_url, db=4)
```

### Celery Workers (DB 0 and DB 1)
```python
# From celery-file-worker/celery_app.py
redis_url = os.getenv('FILE_REDIS_URL')  # Must include /0

# From celery-web-worker/celery_app.py
redis_url = os.getenv('WEB_REDIS_URL')  # Must include /1
```

## Railway Setup Instructions

### Step 1: Get Redis URL from Railway

1. Go to your Railway project
2. Find your Redis service
3. Copy the `REDIS_URL` variable (it will look like: `redis://default:password@redis.railway.internal:6379`)

### Step 2: Configure Each Service

#### API Gateway Service
```bash
REDIS_URL=redis://default:<password>@redis.railway.internal:6379
```
(No database number - code appends `/3`)

#### Configuration Service
```bash
REDIS_URL=redis://default:<password>@redis.railway.internal:6379
```
(No database number - code appends `/4`)

#### Knowledgebase Ingestion Service
```bash
FILE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/0
WEB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/1
```
(Must include database numbers)

#### Celery File Worker
```bash
FILE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/0
```

#### Celery Web Worker
```bash
WEB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/1
```

## Why This Design?

1. **Isolation**: Different databases prevent queue/data conflicts between services
2. **Celery Best Practice**: Each Celery worker pool uses its own database
3. **Pub/Sub Separation**: Pub/Sub on DB 4 doesn't interfere with other operations
4. **Session Isolation**: Sessions on DB 3 are separate from Celery queues

## Troubleshooting

### Error: "REDIS_URL environment variable not set"
**Solution**: Add `REDIS_URL` to the service (without database number for API Gateway and Configuration)

### Error: "FILE_REDIS_URL not set"
**Solution**: Add `FILE_REDIS_URL` with `/0` to knowledgebase-ingestion and celery-file-worker

### Error: "WEB_REDIS_URL not set"
**Solution**: Add `WEB_REDIS_URL` with `/1` to knowledgebase-ingestion and celery-web-worker

### Error: "Connection refused" to Redis
**Solution**: 
- Verify Redis service is running in Railway
- Check that the Redis URL uses the internal Railway hostname
- Ensure all services are in the same Railway project

### Tasks not being processed
**Solution**:
- Verify Celery workers are running
- Check that `FILE_REDIS_URL` and `WEB_REDIS_URL` have correct database numbers
- Ensure workers and dispatcher use the same Redis database
