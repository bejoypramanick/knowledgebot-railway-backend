# Production Database Configuration Guide

## Overview

This document outlines the production-grade SQLAlchemy async database configuration used across all microservices. Uses `AsyncAdaptedQueuePool` for robust connection management in Railway/cloud environments.

## Architecture

```
┌─────────────────┐
│  Microservice   │
├─────────────────┤
│ AsyncAdaptedQueuePool (10-20 min connections)
│ + max_overflow (5-10 burst connections)
│ + pool_pre_ping (automatic health checks)
│ + pool_recycle (stale connection cleanup)
└─────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   PostgreSQL Database           │
│   (Railway or self-hosted)      │
└─────────────────────────────────┘
```

## Environment Variables

### Required
```bash
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

### Production Configuration (Recommended)

```bash
# Connection Pool (AsyncAdaptedQueuePool)
DB_POOL_SIZE=15              # Minimum connections kept alive (increase for high concurrency)
DB_POOL_MAX_OVERFLOW=10      # Additional connections for burst traffic
DB_POOL_RECYCLE=3600         # Recycle connections after 1 hour (prevents stale connections)

# Timeouts (milliseconds and seconds)
DB_STATEMENT_TIMEOUT=60000   # Query execution timeout: 60 seconds
DB_CONNECT_TIMEOUT=15        # Connection establishment timeout: 15 seconds
DB_COMMAND_TIMEOUT=30        # Command execution timeout: 30 seconds
```

### Scaling Guide

**Low Traffic (< 100 concurrent users):**
```bash
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=3
DB_STATEMENT_TIMEOUT=60000
```

**Medium Traffic (100-1000 concurrent users):**
```bash
DB_POOL_SIZE=10
DB_POOL_MAX_OVERFLOW=5
DB_STATEMENT_TIMEOUT=60000
```

**High Traffic (1000+ concurrent users):**
```bash
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=10
DB_STATEMENT_TIMEOUT=30000  # Reduce timeout to fail fast
```

**Very High Traffic (Railway database scaling limits):**
```bash
DB_POOL_SIZE=25
DB_POOL_MAX_OVERFLOW=15
DB_STATEMENT_TIMEOUT=30000
# Consider: Database connection pooler (PgBouncer), read replicas, or sharding
```

## Pool Configuration Explained

### AsyncAdaptedQueuePool
- **Production-grade**: Maintains a queue of connections for reuse
- **Async-compatible**: Works seamlessly with Python's asyncio
- **Connection reuse**: Reduces connection establishment overhead
- **Burst handling**: max_overflow provides additional capacity for traffic spikes

### Key Features

1. **pool_pre_ping=True**
   - Tests each connection before use
   - Automatically discards dead connections
   - Critical for production reliability
   ```python
   # Automatically handles:
   # - PostgreSQL server restart
   # - Network interruptions
   # - Idle connection timeout
   ```

2. **pool_recycle=3600**
   - Recycles connections after 1 hour
   - Prevents "connections left idle too long" errors
   - Matches Railway's typical idle timeout
   ```
   Connection lifecycle:
   Created → Used → Returned to pool → Idle → After 3600s → Recycled
   ```

3. **Connection Timeout Handling**
   ```
   User Request
         │
         ▼
   Acquire from pool (timeout: 10s) ─── Fail → Return 503 Service Unavailable
         │
         ▼
   Execute query (timeout: 60s) ─── Fail → Return 504 Gateway Timeout
         │
         ▼
   Return to pool
   ```

## Performance Characteristics

### Comparison Table

| Aspect | NullPool | AsyncAdaptedQueuePool |
|--------|----------|----------------------|
| Connection reuse | ❌ No | ✅ Yes |
| Latency per request | High (new connection each time) | Low (reused connections) |
| Database resource usage | High | Medium |
| Burst traffic handling | Limited | Excellent |
| Production readiness | ⚠️ Acceptable | ✅ Recommended |
| Max concurrent connections | Unlimited | pool_size + max_overflow |

### Example Performance Impact

**1000 concurrent requests, 100ms query time:**

- **NullPool**: 1000 connections × setup overhead (50-100ms each) = High resource usage
- **AsyncAdaptedQueuePool**: 20 connections × 50 reuses each = Efficient resource usage

## Monitoring

### Key Metrics to Monitor

```python
# Pool exhaustion warning
"ERROR: Pool size exhausted (pool_size={size}, max_overflow={overflow})"

# Connection timeout
"ERROR: Timeout acquiring connection from pool"

# Stale connection
"WARNING: Detected stale connection, discarding"

# Query timeout
"ERROR: Statement timeout: query exceeded {timeout}ms"
```

### Health Checks

The database layer includes automatic health checks:
```bash
GET /health/database
# Returns:
{
  "status": "healthy",
  "response_time_ms": 45,
  "connections_active": 8,
  "pool_size": 15
}
```

## Railway-Specific Configuration

### Connection Limits

Railway PostgreSQL has connection limits based on plan:

- **Hobby**: ~20 connections
- **Pro**: ~100 connections
- **Premium**: Up to 500+ connections

**Calculate your pool needs:**
```
Required connections = (Services × DB_POOL_SIZE) + (Services × DB_POOL_MAX_OVERFLOW)

Example (3 services):
= (3 × 15) + (3 × 10)
= 45 + 30
= 75 total connections (fits in Pro plan)
```

### Recommended Railway Settings

1. **Enable backup** - Critical for production
2. **Use private network** - Services communicate via Railway internal IPs
3. **Monitor connection usage** - Set alerts at 70% of limit
4. **Rotate credentials** - Periodically update database password

## Troubleshooting

### Issue: "Pool size exhausted"
```
Solution:
1. Increase DB_POOL_SIZE (production: 15-25)
2. Increase DB_POOL_MAX_OVERFLOW (production: 5-10)
3. Reduce long-running queries (optimize slow queries)
4. Check for connection leaks (sessions not closed properly)
```

### Issue: "Connection timeout"
```
Solution:
1. Increase DB_CONNECT_TIMEOUT (default: 10s → try 15-20s)
2. Check database load/CPU
3. Verify network connectivity
4. Review Railway status page for incidents
```

### Issue: "Connections left idle too long"
```
Solution:
1. Connections are automatically recycled (DB_POOL_RECYCLE=3600)
2. pool_pre_ping=True handles stale connections automatically
3. If still occurring, reduce DB_POOL_RECYCLE to 1800s
```

### Issue: "Too many connections"
```
Solution:
1. Reduce DB_POOL_SIZE and DB_POOL_MAX_OVERFLOW
2. Implement connection pooler (PgBouncer)
3. Scale horizontally with read replicas
4. Upgrade Railway database plan
```

## Security Best Practices

1. **Credentials**
   - Use Railway environment variables (DATABASE_URL)
   - Never commit credentials to Git
   - Rotate credentials quarterly

2. **Connection Security**
   - Connections use SSL/TLS by default on Railway
   - Verify certificate validation is enabled
   - Use private network when possible

3. **Query Safety**
   - Always use parameterized queries (text() with :params)
   - Never concatenate user input into SQL
   - SQLAlchemy prevents SQL injection by default

## Code Example

```python
# Import
from shared.sqlalchemy_db import init_database, get_db_session, close_database

# Startup
@app.on_event("startup")
async def startup():
    await init_database()  # Uses env vars for configuration

# Usage in endpoints
@app.get("/users")
async def get_users():
    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT * FROM users WHERE active = :active"),
            {"active": True}
        )
        return result.fetchall()

# Shutdown
@app.on_event("shutdown")
async def shutdown():
    await close_database()
```

## Production Checklist

- [ ] Set `DB_POOL_SIZE` based on expected concurrency
- [ ] Set `DB_POOL_MAX_OVERFLOW` for burst capacity
- [ ] Verify `DB_STATEMENT_TIMEOUT` matches query complexity
- [ ] Monitor connection pool usage (target: 50-70% utilization)
- [ ] Set up alerts for pool exhaustion
- [ ] Test failover/recovery procedures
- [ ] Enable database backups
- [ ] Document runbook for connection issues
- [ ] Regular load testing before peak traffic periods

## References

- [SQLAlchemy AsyncAdaptedQueuePool](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [Railway Database Documentation](https://docs.railway.app/databases/postgresql)
- [PostgreSQL Connection Management](https://www.postgresql.org/docs/current/runtime-config-connection.html)
