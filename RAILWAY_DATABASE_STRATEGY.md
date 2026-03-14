# Railway Database Sleep Strategy - Cost Optimized

## Overview
This guide explains how the system handles Railway's automatic database sleep to **minimize costs while ensuring reliability**.

## The Problem
- Railway puts databases to sleep after **15 minutes of inactivity**
- First request after sleep takes **5-10 seconds** (database wakes up)
- Without retry logic, this would timeout and fail
- Traditional solution: Keep-alive pings every 5 minutes (adds continuous cost)

## Our Solution: Smart Retry Without Keep-Alive Costs ✅

**Strategy**: Let database sleep, handle wake-up gracefully via retry logic

| First Request After Sleep | Subsequent Requests | Cost |
|---------------------------|-------------------|------|
| 5-10s (retry until awake) | 50-100ms (fast) | **Zero** keep-alive cost |
| Widget loads, no timeout   | Real-time speed    | Pay only for actual usage |

## How It Works

### 1. Frontend Retry Logic (User-Facing)
**File**: `knowledgebot-bubble/src/services/BubbleConfigService.ts`

When fetching widget configuration:
```
Request 1: TIMEOUT (db sleeping)
Wait 1s → Request 2: TIMEOUT
Wait 2s → Request 3: TIMEOUT
Wait 4s → Request 4: SUCCESS (db awake!)
Total: ~7-10 seconds (database wakes up, widget loads)
```

**Configuration**:
- **Retries**: 4 attempts (configurable)
- **Delays**: 1s → 2s → 4s → 8s → 16s (exponential backoff with jitter)
- **Max Total Wait**: ~31 seconds before giving up
- **Smart Errors**: Fails immediately on 4xx (bad request), retries on 5xx/timeouts

### 2. Backend Connection Pool (Graceful Recovery)
**File**: `shared/sqlalchemy_db.py`

When database is sleeping:
```python
AsyncAdaptedQueuePool:
- pool_pre_ping=True          # Health check before using connection
- pool_recycle=3600           # Recycle stale connections after 1 hour
- pool_size=10, overflow=10   # Enough connections for burst traffic
- Auto-reconnect on failure
```

**Result**: As soon as database wakes up, connection pool automatically reconnects.

### 3. User Experience
1. **Initial Request** (after sleep):
   - User sees: "Loading..." spinner
   - Retries happen silently with loading messages
   - Takes 5-10 seconds (acceptable cold-start delay)

2. **Subsequent Requests** (within 15 min):
   - Database stays warm (actively used)
   - Response time: 50-100ms (normal speed)
   - No noticeable delays

3. **Idle Period** (15+ min):
   - Database goes to sleep (saves cost)
   - No requests = no costs
   - Cycle repeats

## Configuration

### Environment Variables (Optional)

Most settings have good defaults. Only change if needed:

```bash
# Database Timeouts
DB_CONNECT_TIMEOUT=10              # Wait up to 10s for initial connection
DB_COMMAND_TIMEOUT=20              # Command execution timeout
DB_STATEMENT_TIMEOUT=60000         # Query timeout (milliseconds)

# Connection Pool
DB_POOL_SIZE=10                    # Min connections to maintain
DB_POOL_MAX_OVERFLOW=10            # Additional connections for burst
DB_POOL_RECYCLE=3600               # Recycle stale connections after 1 hour

# (REMOVED) KEEPALIVE_INTERVAL_SECONDS
# No longer needed - database sleeps to save costs!
```

### No Railway Configuration Needed
- Default settings handle database sleep perfectly
- Nothing to configure in Railway dashboard for this strategy
- Let Railway's native sleep feature work (it's free!)

## Monitoring

### Health Check Endpoint
```bash
curl https://your-api.railway.app/health | jq .
```

**Response when database is sleeping**:
```json
{
  "status": "unhealthy",
  "message": "Database check failed: Connection timeout",
  "latency_ms": 10000,
  "database": "unhealthy"
}
```

**Response after wake-up** (should see immediately after first request):
```json
{
  "status": "healthy",
  "message": "Database connection healthy",
  "latency_ms": 45,
  "database": "healthy",
  "pool": {
    "size": 10,
    "checked_in": 8,
    "checked_out": 2,
    "total_connections": 10
  }
}
```

### Key Logs to Watch

✅ **Database waking up** (after ~5-10s sleep):
```
[2026-03-13 10:15:45] Request failed (attempt 1/5): Connect timeout
[2026-03-13 10:15:46] Retrying in 1000ms
[2026-03-13 10:15:46] Request failed (attempt 2/5): Connect timeout
[2026-03-13 10:15:47] Retrying in 2000ms
[2026-03-13 10:15:49] Request failed (attempt 3/5): Connect timeout
[2026-03-13 10:15:51] Retrying in 4000ms
[2026-03-13 10:15:55] ✅ Widget config loaded successfully
```

⚠️ **Persistent connection issues**:
```
[2026-03-13 10:20:00] Request failed (attempt 4/5): Connect refused
[2026-03-13 10:20:16] Request failed (attempt 5/5): Connect refused
[2026-03-13 10:20:16] Error: Max retries exceeded
```
Action: Check Railway PostgreSQL service status

## Cost Analysis

### Keep-Alive Approach (NOT USED)
```
Ping every 5 minutes = 288 pings/day = continuous DB load
Cost: ~$50-100/month extra
```

### Smart Retry Approach (USED) ✅
```
Only database queries on actual requests
Cold-start: 1 request takes 5-10s (rare, < 1x/15min)
Steady-state: 50-100ms responses
Cost: Zero keep-alive overhead - pay only for usage
```

## Troubleshooting

### Issue: Widget config fails after 30 seconds
**Symptom**: "Failed to fetch widget configuration" error

**Likely Cause**: Database didn't wake up in time (very rare)

**Fix**:
1. Check Railway PostgreSQL status dashboard
2. Verify database is running (not crashed)
3. Try again - should work on next attempt
4. If persistent, contact Railway support

### Issue: First request always takes 10+ seconds
**This is expected behavior!**

The first request after the 15-minute idle period will:
1. Hit sleeping database (initial timeout)
2. Retry with backoff (1s, 2s, 4s delays)
3. Database wakes up (usually by 4th-5th request)
4. Widget loads successfully

This is the trade-off: **minimal cost vs. occasional 10s cold-start**.

### Issue: Rapid requests showing timeouts
**Cause**: Multiple requests hit sleeping database simultaneously, overwhelming retry backoff

**Not a bug**: This is very rare. Each request independently retries, so they should succeed eventually.

**If persistent**: Increase retry count in `BubbleConfigService.ts`:
```typescript
async getWidgetConfig(retries = 5): Promise<WidgetConfiguration> {  // Was 4
  // ...
  retries,
  1000,   // baseDelay: 1s
  16000   // maxDelay: 16s
);
```

## Performance Expectations

### Typical Usage Pattern
```
10:00 AM - User loads chat widget
         → First request: 5-10s (db wakes)
         → Widget appears: ✅ Working

10:01 AM - User sends message
         → Request: 80ms (db warm)
         → Reply: ✅ Fast

10:14 AM - Last user activity
         → Database is warm from recent requests

10:15 AM - No activity for 15 min
         → Railway puts database to sleep (cost saved!)

10:31 AM - New user loads chat
         → First request: 5-10s (db wakes)
         → Widget appears: ✅ Working
```

## Comparison with Competitors

| Service | Sleep Handling | Cost | Wake-Time |
|---------|---|---|---|
| Railway (Smart Retry) | Retries + wait | Minimal ✅ | 5-10s |
| Railway (Keep-Alive) | Always awake | High ❌ | Instant |
| AWS RDS | Auto-scaling | High | Instant |
| PlanetScale | Always awake | Medium | Instant |

**Best for**: Cost-conscious projects, non-critical services, low traffic

---

## Summary

✅ **What We Avoid**: Continuous keep-alive pings (costs money)
✅ **What We Use**: Smart retry logic with exponential backoff (graceful)
✅ **Result**: Minimal cost + occasional 5-10s cold-start

**Default Railway sleep = Free optimization** 🚀

---

**Last Updated**: March 2026
**Status**: Production-Ready, Cost-Optimized
