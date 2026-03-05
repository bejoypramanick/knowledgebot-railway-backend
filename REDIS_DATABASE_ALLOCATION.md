# Redis Database Allocation

This document describes how Redis databases are allocated across the system.

## Database Allocation

| Database | Purpose | Environment Variable | Used By |
|----------|---------|---------------------|---------|
| **DB 0** | File Processing (Celery) | `FILE_REDIS_URL` | celery-file-worker, knowledgebase-ingestion |
| **DB 1** | Web Crawling (Celery) | `WEB_REDIS_URL` | celery-web-worker, knowledgebase-ingestion |
| **DB 2** | Session Storage | `SESSION_REDIS_URL` | api-gateway (session_store) |
| **DB 3** | Pub/Sub (SSE Events) | `PUBSUB_REDIS_URL` | configuration service (redis_pubsub_manager) |
| **DB 4** | *(Reserved/Unused)* | - | Available for future use |

## Environment Variable Configuration

All services require **explicit database numbers in the URL**:

```bash
# File Processing (DB 0)
FILE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/0

# Web Crawling (DB 1)
WEB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/1

# Session Storage (DB 2)
SESSION_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/2

# Pub/Sub for SSE Events (DB 3)
PUBSUB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/3
```

## Code Behavior

All Redis connections now use explicit environment variables with database numbers in the URL.

### Session Store (DB 2)
```python
# From api_gateway/core/session_store.py
redis_url = os.getenv('SESSION_REDIS_URL')  # Must include /2
redis.from_url(redis_url)
```

### Pub/Sub Manager (DB 3)
```python
# From shared/redis_pubsub_manager.py
redis_url = os.getenv('PUBSUB_REDIS_URL')  # Must include /3
redis.from_url(redis_url)
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
SESSION_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/2
```

#### Configuration Service
```bash
PUBSUB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/3
```

#### Knowledgebase Ingestion Service
```bash
FILE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/0
WEB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/1
```

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

### Error: "SESSION_REDIS_URL environment variable not set"
**Solution**: Add `SESSION_REDIS_URL` with `/2` to API Gateway service

### Error: "PUBSUB_REDIS_URL environment variable not set"
**Solution**: Add `PUBSUB_REDIS_URL` with `/3` to Configuration service

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
