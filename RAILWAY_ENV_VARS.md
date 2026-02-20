# Railway Environment Variables Configuration

This document describes the environment variables needed to configure worker concurrency and database connection pooling for optimal performance.

## Database Connection Pool Configuration

These variables control the connection pool size per worker process. With Celery's prefork pool, each worker process maintains its own connection pool.

### `DB_POOL_MIN_SIZE`
- **Description**: Minimum number of database connections per worker process
- **Default**: `1`
- **Recommended**: `1` (keeps idle connections low)
- **Example**: `DB_POOL_MIN_SIZE=1`

### `DB_POOL_MAX_SIZE`
- **Description**: Maximum number of database connections per worker process
- **Default**: `3`
- **Recommended**: `3` (allows 2 concurrent operations + 1 for health checks)
- **Example**: `DB_POOL_MAX_SIZE=3`

### Total Connection Calculation
```
Total Max Connections = (Web Workers + File Workers) × DB_POOL_MAX_SIZE
                      = (5 + 5) × 3
                      = 30 connections
```

## Celery Worker Concurrency Configuration

These variables control how many parallel tasks each Celery worker can handle.

### `CELERY_WEB_CONCURRENCY`
- **Description**: Number of parallel worker processes for web crawling tasks
- **Default**: `5`
- **Recommended**: `5` (balances throughput with memory usage)
- **Example**: `CELERY_WEB_CONCURRENCY=5`

### `CELERY_FILE_CONCURRENCY`
- **Description**: Number of parallel worker processes for file processing tasks
- **Default**: `5`
- **Recommended**: `5` (balances throughput with memory usage)
- **Example**: `CELERY_FILE_CONCURRENCY=5`

## Current Configuration Summary

With the default/recommended values:

| Component | Setting | Value |
|-----------|---------|-------|
| Web Worker Concurrency | `CELERY_WEB_CONCURRENCY` | 5 |
| File Worker Concurrency | `CELERY_FILE_CONCURRENCY` | 5 |
| DB Pool Min Size | `DB_POOL_MIN_SIZE` | 1 |
| DB Pool Max Size | `DB_POOL_MAX_SIZE` | 3 |
| **Total Parallel Tasks** | - | **10** |
| **Total Max DB Connections** | - | **30** |

## How to Set in Railway

1. Go to your Railway project dashboard
2. Navigate to the service (e.g., `celery-web-worker` or `celery-file-worker`)
3. Click on "Variables" tab
4. Add the environment variables with your desired values
5. Railway will automatically restart the service with new configuration

### Shared Variables (Set in Common/Shared Variables)
These should be set at the project level so all services use the same values:
- `DB_POOL_MIN_SIZE=1`
- `DB_POOL_MAX_SIZE=3`

### Service-Specific Variables
Set these individually for each service:

**celery-web-worker:**
- `CELERY_WEB_CONCURRENCY=5`

**celery-file-worker:**
- `CELERY_FILE_CONCURRENCY=5`

## Performance Tuning Guidelines

### Increase Concurrency
If you want more parallel tasks:
1. Increase `CELERY_WEB_CONCURRENCY` and/or `CELERY_FILE_CONCURRENCY`
2. Increase `DB_POOL_MAX_SIZE` proportionally
3. Monitor memory usage (each worker uses ~200-500MB)

Example for 10 web workers + 10 file workers:
```
CELERY_WEB_CONCURRENCY=10
CELERY_FILE_CONCURRENCY=10
DB_POOL_MAX_SIZE=3
Total connections: 20 × 3 = 60
```

### Reduce Memory Usage
If hitting memory limits:
1. Decrease `CELERY_WEB_CONCURRENCY` and/or `CELERY_FILE_CONCURRENCY`
2. Keep `DB_POOL_MAX_SIZE=3` (already optimized)

Example for 3 web workers + 3 file workers:
```
CELERY_WEB_CONCURRENCY=3
CELERY_FILE_CONCURRENCY=3
DB_POOL_MAX_SIZE=3
Total connections: 6 × 3 = 18
```

## Troubleshooting

### "pool is closed" errors
- Increase `DB_POOL_MAX_SIZE` if workers are competing for connections
- Check if database has connection limits (Railway Postgres typically allows 100+ connections)

### High memory usage
- Decrease `CELERY_WEB_CONCURRENCY` and `CELERY_FILE_CONCURRENCY`
- Monitor with Railway metrics dashboard

### Slow task processing
- Increase `CELERY_WEB_CONCURRENCY` and `CELERY_FILE_CONCURRENCY`
- Ensure `DB_POOL_MAX_SIZE` is sufficient for the concurrency level

## Monitoring

Check Railway logs for these indicators:

✅ **Healthy Configuration:**
```
📊 [DB_POOL_CONFIG] Pool size: min=1, max=3
✅ [CELERY_APP] Configuration updated
   Concurrency: 5 parallel workers
```

⚠️ **Connection Issues:**
```
❌ Failed to acquire DB connection: pool is closed
⚠️ DB pool health check failed
```

If you see connection issues, increase `DB_POOL_MAX_SIZE` or decrease concurrency.
