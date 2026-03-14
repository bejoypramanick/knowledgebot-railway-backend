# Railway Keep-Alive Configuration Guide

## Problem
On Railway, services automatically go to sleep after **15 minutes of inactivity**. When PostgreSQL sleeps, the initial connection takes extra time to wake up, causing timeouts when fetching widget configuration.

## Solution Overview
1. **Keep-Alive Service**: Periodic database pings keep the database awake
2. **Increased Retries**: Frontend retries with longer timeouts for initial connections
3. **Connection Pooling**: AsyncAdaptedQueuePool with pre-ping health checks

## Implementation

### Environment Variables (Set in Railway Dashboard)

```bash
# Keep-Alive Service - Pings database to keep it awake
KEEPALIVE_INTERVAL_SECONDS=300  # 5 minutes (default)
# Recommended values:
# - 300 (5 min): Light traffic, saves resources
# - 180 (3 min): Medium traffic
# - 60 (1 min): High traffic or critical services

# Database Pool Configuration
DB_POOL_SIZE=10                  # Min connections to keep alive
DB_POOL_MAX_OVERFLOW=10          # Additional connections for spikes
DB_POOL_RECYCLE=3600             # Recycle stale connections after 1 hour
DB_CONNECT_TIMEOUT=10            # Connection timeout (seconds)
DB_COMMAND_TIMEOUT=20            # Command timeout (seconds)
DB_STATEMENT_TIMEOUT=60000       # Query timeout (milliseconds)
```

### How It Works

1. **Keep-Alive Service** (Backend)
   - Runs as background task in API Gateway
   - Every 300 seconds (5 min), executes: `SELECT 1` on PostgreSQL
   - Prevents service/database from sleeping
   - Graceful error handling - failures don't crash the service
   - Log output: `[WARMING_UP] 🔄 Keep-alive ping: database OK (45ms)`

2. **Connection Pool Management**
   - `pool_pre_ping=True`: Checks connection health before use
   - Automatic recycling after 1 hour
   - Min 10, max 20 connections available
   - Overflow connections for burst traffic

3. **Frontend Retry Logic**
   - Retries up to 4 times with exponential backoff
   - Delays: 1s → 2s → 4s → 8s → 16s
   - Total max wait: ~31 seconds
   - Handles both connection timeouts and 5xx errors
   - Immediately throws on 4xx errors (invalid request)

## Health Checks

### Frontend Bubble Widget
- Endpoint: `GET /api/v1/gateway/configuration/widgetConfig`
- Timeout: 31 seconds max (4 retries with exponential backoff)
- On failure: Shows error message (config won't load)

### Backend Health Endpoints
- Primary: `GET /health` - Database health check
- Legacy: `GET /gateway/health` - Same functionality
- Returns: `{ status, latency_ms, database: { checkedin, checkedout, total_connections } }`

### Check Database Status
```bash
curl https://your-api.railway.app/health -s | jq .
# Response:
# {
#   "status": "healthy",
#   "latency_ms": 45.23,
#   "database": "healthy",
#   "database_latency_ms": 42.15,
#   "pool": {
#     "size": 10,
#     "checked_in": 8,
#     "checked_out": 2,
#     "overflow": 0,
#     "total_connections": 10
#   }
# }
```

## Monitoring

### Logs to Watch For

✅ **Healthy startup**:
```
✅ Keep-alive service started (pings database every 300s)
🔄 Keep-alive ping: database OK (45ms)
```

⚠️ **Database wake-up (initial request)**:
```
Request failed (attempt 1/5): timeout
Retrying in 1000ms (attempt 1/5)
Request failed (attempt 2/5): timeout
Retrying in 2000ms (attempt 2/5)
[WARMING_UP] 🔄 Initializing...
[WARMING_UP] ⏳ Loading models...
✅ Widget config response: {...}
```

❌ **Connection pool exhausted**:
```
⚠️ Connection pool usage high: {
  "size": 10,
  "checked_out": 8,
  "overflow": 5,
  "total_connections": 15
}
```

### Recommended Monitoring
1. **Keep-Alive Ping Rate**: Should see one every 5 minutes in logs
2. **Connection Pool Utilization**: Monitor `checked_out/total` ratio
3. **Database Latency**: Track `latency_ms` from health endpoint
4. **Error Rate**: 404/500 errors on widget config endpoint

## Troubleshooting

### Issue: Widget config still timing out
**Cause**: Keep-alive interval too long, or multiple concurrent requests overwhelm pool

**Fix**:
```bash
# Reduce keep-alive interval
KEEPALIVE_INTERVAL_SECONDS=60  # Every 1 minute instead of 5

# Increase connection pool
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=20
```

### Issue: Database pool exhausted
**Symptom**: Many `[checked_out]` connections in health check

**Fix**:
```bash
# Increase pool size
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=15

# Decrease connection recycling time
DB_POOL_RECYCLE=1800  # 30 minutes instead of 1 hour
```

### Issue: Keep-alive ping fails
**Symptom**: `⚠️ Keep-alive ping failed: ...` in logs

**Cause**: Usually temporary network issue or database maintenance

**Action**: Monitor - should self-recover on next ping. Not a blocker unless persistent.

## Railway-Specific Recommendations

1. **Tier**: Use **Premium Tier** for production (better uptime SLA)
2. **Auto-deploy**: Enable "Auto Deploy" on main branch
3. **Health Checks**: Railway respects `/health` endpoint status
4. **Scale Policy**: Set min replicas=1 (prevents container restart killing connections)

## Performance Expectations

| Scenario | Response Time | Behavior |
|----------|---------------|----------|
| Database awake | 50-100ms | Normal operation |
| Database sleeping | 5-10s | First request takes longer, then fast |
| Multiple concurrent requests | 100-500ms | Connection pool handles burst |
| Network issue | Retry with backoff | Automatic recovery |

## Costs

Keep-alive service overhead:
- **Database**: One `SELECT 1` query every 5 minutes ≈ minimal CPU/storage
- **Network**: ~1KB per ping, negligible bandwidth
- **Billing Impact**: Essentially zero

---

**Last Updated**: March 2026
**Status**: Active in Production
