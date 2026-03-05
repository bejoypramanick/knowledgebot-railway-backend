# Railway Environment Variables to Set

## Quick Setup Guide

After deploying the latest code, you need to set these environment variables in Railway:

### 1. API Gateway Service

Add this variable:
```
SESSION_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/2
```

**How to get the password:**
1. Go to your Redis service in Railway
2. Copy the `REDIS_URL` value
3. Extract the password from it (the part after `default:` and before `@`)
4. Use that password in the `SESSION_REDIS_URL` above

### 2. Configuration Service

Add this variable:
```
PUBSUB_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/3
```

Use the same password from your Redis service.

## Summary of Changes

| Service | Old Variable | New Variable | Database |
|---------|-------------|--------------|----------|
| API Gateway | `REDIS_URL` (auto DB 3) | `SESSION_REDIS_URL` | DB 2 |
| Configuration | `REDIS_URL` (auto DB 4) | `PUBSUB_REDIS_URL` | DB 3 |

## Why This Change?

1. **Explicit is better than implicit** - No more dynamic database calculation
2. **Clearer configuration** - Each service has its own named variable
3. **Better isolation** - Sessions on DB 2, Pub/Sub on DB 3
4. **Consistent pattern** - All services now use explicit database numbers in URLs

## Complete Redis Database Allocation

| DB | Purpose | Variable | Services |
|----|---------|----------|----------|
| 0 | File Processing | `FILE_REDIS_URL` | celery-file-worker, knowledgebase-ingestion |
| 1 | Web Crawling | `WEB_REDIS_URL` | celery-web-worker, knowledgebase-ingestion |
| 2 | Sessions | `SESSION_REDIS_URL` | api-gateway |
| 3 | Pub/Sub (SSE) | `PUBSUB_REDIS_URL` | configuration |
| 4 | Reserved | - | Available for future use |

## After Setting Variables

1. Railway will automatically redeploy the affected services
2. Check the logs for:
   - API Gateway: `✅ Redis connected successfully for session storage (database 2)`
   - Configuration: `✅ Redis Pub/Sub client initialized successfully (db=3)`

## If You See Errors

### "SESSION_REDIS_URL environment variable not set"
- Add `SESSION_REDIS_URL` to API Gateway service with `/2`

### "PUBSUB_REDIS_URL environment variable not set"
- Add `PUBSUB_REDIS_URL` to Configuration service with `/3`

### "Connection refused"
- Verify Redis service is running
- Check the password is correct
- Ensure using `redis.railway.internal` hostname
