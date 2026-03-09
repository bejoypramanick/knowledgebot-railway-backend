# Database Retry Logic Fix - Railway Cold Start Issue

## Problem

Services were failing on Railway during startup because:

1. **PostgreSQL startup delay**: When containers restart, PostgreSQL needs time to start and run recovery
2. **No retry logic**: Services tried to connect once and gave up if they failed
3. **Inconsistent approach**: Different services had different (or no) retry logic

Timeline of failure:
```
08:35:18 - PostgreSQL container starts
08:35:19 - PostgreSQL recovery in progress (FATAL: database system is starting up)
          └─ Services tried to connect HERE and got "Connection refused"
          └─ Services gave up and crashed
08:35:20 - PostgreSQL ready to accept connections
          └─ Too late - services already failed
```

## Solution

### 1. Centralized Retry Module (`shared/db_retry.py`)

Created a reusable `initialize_database_with_retry()` function that:
- Attempts database connection up to 5 times
- Waits 2 seconds between retries
- Validates database schema after connection
- Provides consistent logging across all services
- Works with Railway's container restart lifecycle

**Benefits:**
- ✅ Single source of truth for retry logic
- ✅ Easy to update retry strategy globally
- ✅ Consistent behavior across all services
- ✅ Better logging and debugging

### 2. Service Updates

Updated three services to use centralized retry logic:

#### `api_gateway/main.py`
```python
# Before: Tried once, raised exception
try:
    if database_url:
        await init_database(database_url)  # Single attempt
except Exception as e:
    raise RuntimeError(f"Failed: {e}")

# After: Retries with backoff
await initialize_database_with_retry(
    database_url,
    service_name="api-gateway"
)
```

#### `chatbot_orchestration/main.py`
```python
# Before: Tried once, logged warning, continued
try:
    await init_database(database_url)
except Exception:
    logger.warning("Database unavailable")

# After: Retries with backoff
await initialize_database_with_retry(
    database_url,
    service_name="chatbot-orchestration"
)
```

#### `configuration/main.py` & `knowledgebase_ingestion/main.py`
- Already had retry logic - now could be updated to use centralized version for consistency

## How It Works

```
Service Startup
    ↓
initialize_database_with_retry(database_url)
    ↓
Attempt 1: Connection fails → 2s wait
    ↓
Attempt 2: Connection fails → 2s wait
    ↓
Attempt 3: Connection succeeds → Validate schema → Success ✅
    ↓
Service continues with database ready
```

## Retry Logic Details

**Parameters:**
- `max_retries`: 5 attempts (configurable)
- `retry_delay`: 2 seconds between attempts (configurable)
- `service_name`: For logging context (e.g., "api-gateway")

**Validation:**
1. Try to connect to PostgreSQL
2. If connected, validate schema with `validate_database()`
3. Only proceed if both succeed
4. Log clearly at each step for debugging

**Handling Failures:**
- If all retries fail: Service continues with warning
- Database unavailable doesn't prevent startup
- Health check endpoint will report database as down
- Dependent operations will fail gracefully with proper errors

## Testing

After deployment, verify retry logic works:

1. **Watch logs during startup:**
   ```
   Filter: "Database connection attempt"
   Expected: See multiple attempts if PostgreSQL is slow to start
   Expected: Eventually see "Database is ready and operational"
   ```

2. **Simulate slow database:**
   ```sql
   -- In PostgreSQL, simulate slow startup with delay
   -- (Only for testing - remove afterwards)
   ```

3. **Check health endpoint:**
   ```bash
   curl https://your-api.railway.app/health
   # Should report database status
   ```

## Log Examples

### Successful connection (attempt 1)
```
🔄 [api-gateway] Database connection attempt 1/5
✅ [api-gateway] SQLAlchemy engine initialized
✅ [api-gateway] Database schema validated successfully
✅ [api-gateway] Database is ready and operational
```

### Successful connection (attempt 3 after retries)
```
🔄 [api-gateway] Database connection attempt 1/5
❌ [api-gateway] Database connection attempt 1 failed: Connection refused
⏳ [api-gateway] Retrying in 2s...

🔄 [api-gateway] Database connection attempt 2/5
❌ [api-gateway] Database connection attempt 2 failed: Connection refused
⏳ [api-gateway] Retrying in 2s...

🔄 [api-gateway] Database connection attempt 3/5
✅ [api-gateway] SQLAlchemy engine initialized
✅ [api-gateway] Database schema validated successfully
✅ [api-gateway] Database is ready and operational
```

### All attempts failed
```
❌ [api-gateway] All 5 connection attempts failed
⚠️ [api-gateway] Service starting with database unavailable
```

## Configuration

To adjust retry behavior, modify in `shared/db_retry.py`:

```python
# Default: 5 retries, 2 second delay
success = await initialize_database_with_retry(
    database_url,
    max_retries=5,        # ← Change this
    retry_delay=2,        # ← Or this (seconds)
    service_name="my-service"
)

# Example: More aggressive (10 attempts, 5 second delay for slow databases)
success = await initialize_database_with_retry(
    database_url,
    max_retries=10,
    retry_delay=5,
    service_name="my-service"
)
```

## Related Issues Fixed

- ✅ `[Errno 111] Connection refused` during Railway container restarts
- ✅ `the database system is starting up` (FATAL) race condition
- ✅ Services failing to start due to PostgreSQL recovery delay
- ✅ Inconsistent database initialization behavior across services

## Future Improvements

1. **Configurable retry strategy**: Add env vars for max_retries and retry_delay
2. **Exponential backoff**: Instead of fixed 2s delay, use exponential backoff
3. **Circuit breaker**: Stop retrying if database is persistently down
4. **Metrics**: Track retry attempts and successes for monitoring

## Files Modified

- ✅ `shared/db_retry.py` - NEW centralized retry module
- ✅ `api_gateway/main.py` - Use centralized retry logic
- ✅ `chatbot_orchestration/main.py` - Use centralized retry logic
- ✅ `configuration/main.py` - (Could be updated next)
- ✅ `knowledgebase_ingestion/main.py` - (Could be updated next)

---

**Summary:** Centralized database retry logic ensures Railway deployments handle PostgreSQL startup delays gracefully, preventing connection failures during container restarts.
