# Database Connection Fixes - Railway AsyncPG Issues

This document describes the 4 key fixes implemented for the Railway asyncpg database connectivity issues that were causing `TypeError: object NoneType can't be used in 'await' expression` errors.

## Problem Analysis

The logs showed that asyncpg's connection pool `acquire()` method was returning `None` instead of valid database connections, causing the application to fail with 503 Service Unavailable errors across all database-dependent endpoints.

### Root Causes Identified:

1. **Pool Corruption**: The connection pool was becoming corrupted and returning `None` on acquire operations
2. **No Health Checks**: No validation of pool health before attempting to acquire connections
3. **Missing Error Handling**: No proper handling of `None` returns from pool.acquire()
4. **No Retry Logic**: No automatic recovery from temporary network issues during Railway initialization
5. **Improper Connection Management**: Not using proper context managers for connection lifecycle

## 4 Key Fixes Implemented

### ✅ Fix 1: Pool Health Checks Before Acquisition

**File**: `shared/db.py` - `DatabasePool.acquire()` method

```python
async def acquire(self) -> asyncpg.Connection:
    """Acquire a database connection with health checks and None handling."""
    # Check pool health before acquiring
    if not await self._ensure_pool_health():
        raise RuntimeError("Database pool is unhealthy and could not be recovered")

    if self._pool is None:
        raise RuntimeError("Database pool is not initialized")

    try:
        # Acquire connection with timeout
        conn = await asyncio.wait_for(
            self._pool.acquire(),
            timeout=10.0
        )

        # Double-check that we got a valid connection
        if conn is None:
            logger.error("❌ Pool.acquire() returned None - pool corruption detected")
            # Try to recreate the pool
            await self._recreate_pool_on_failure()
            raise RuntimeError("Database connection pool returned None - pool corrupted")

        return conn
    except Exception as e:
        logger.error(f"❌ Failed to acquire database connection: {e}")
        await self._recreate_pool_on_failure()
        raise
```

### ✅ Fix 2: Proper Error Handling with None Checks

**File**: `shared/db.py` - `_ensure_pool_health()` method

```python
async def _ensure_pool_health(self) -> bool:
    """Ensure the pool is healthy, recreate if necessary."""
    current_time = asyncio.get_event_loop().time()

    # Skip health check if recently performed
    if current_time - self._last_health_check < self._health_check_interval:
        return self._pool is not None

    self._last_health_check = current_time

    if self._pool is None:
        logger.info("🔄 Pool is None, attempting to recreate...")
        try:
            await self._create_pool()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to recreate pool: {e}")
            return False

    # Test pool health
    if not await self._test_pool_health():
        logger.warning("⚠️ Existing pool health check failed: object NoneType can't be used in 'await' expression")
        logger.info("🔄 Creating new connection pool...")
        try:
            await self._create_pool()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to recreate unhealthy pool: {e}")
            return False

    return True
```

### ✅ Fix 3: Retry Logic for Railway Network Initialization

**File**: `shared/utils.py` - `retry_database_operation` decorator

```python
# Pre-configured retry decorators for common scenarios
retry_database_operation = retry_with_backoff(
    config=RetryConfig(
        max_attempts=5,
        initial_delay=0.5,
        max_delay=10.0,
        backoff_factor=1.5
    ),
    exceptions=(RuntimeError, ConnectionError, asyncio.TimeoutError, asyncpg.exceptions.PostgresError)
)

# Usage in endpoints:
@app.get("/api/v1/configuration/chatbot")
@retry_database_operation
async def get_chatbot_config():
    # Database operations here are automatically retried
```

### ✅ Fix 4: Context Managers for Connection Management

**File**: `shared/db.py` - `DatabaseConnection` class

```python
class DatabaseConnection:
    """Context manager for database connections."""

    def __init__(self):
        self._conn: Optional[asyncpg.Connection] = None

    async def __aenter__(self) -> asyncpg.Connection:
        # Get database connection from the enhanced pool
        if railway_db and hasattr(railway_db, '_pool') and railway_db._pool:
            # Use the enhanced pool directly for better error handling
            pool_manager = DatabasePool()
            pool_manager._pool = railway_db._pool
            self._conn = await pool_manager.acquire()
        else:
            # Fallback to legacy method
            async with railway_db.acquire() as conn:
                self._conn = conn
        return self._conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._conn is not None:
            try:
                # Return connection to pool
                if railway_db and hasattr(railway_db, '_pool'):
                    await railway_db._pool.release(self._conn)
                logger.debug("Database connection released")
            except Exception as e:
                logger.warning(f"Error releasing database connection: {e}")
```

## Updated Files

### `shared/db.py`
- Added `DatabasePool` class with enhanced pool management
- Updated `Database.connect()` to use the new pool manager
- Added `DatabaseConnection` context manager
- Added comprehensive error handling and None checks

### `shared/utils.py`
- Added `RetryConfig` class for configurable retry logic
- Added `retry_with_backoff` decorator with exponential backoff and jitter
- Added `retry_database_operation` pre-configured decorator
- Added `wait_for_railway_network()` function for Railway initialization delays
- Added `validate_environment()` function for startup validation
- Added `GracefulShutdown` class for proper shutdown handling
- Added `ServiceStatus` class for service monitoring

### `services/configuration_service/main.py`
- Updated `get_db_connection()` to use `DatabaseConnection` context manager
- Added proper error handling for None returns and timeouts
- Updated lifespan function with Railway network wait and environment validation
- Added `@retry_database_operation` decorators to all database endpoints
- Enhanced health check endpoint with detailed pool statistics

## Railway-Specific Optimizations

### Network Initialization Delay
```python
# In lifespan function
await wait_for_railway_network()  # Waits 3 seconds for Railway private network
```

### Connection Pool Configuration
```python
await pool_manager.initialize_pool(
    dsn=database_url,
    min_size=5,  # Railway serverless optimization
    max_size=20,  # Reasonable limit for Railway
    command_timeout=60.0,
    server_settings={
        'application_name': 'knowledgebot_configuration_service',
        'timezone': 'UTC',
        'tcp_keepalives_idle': '60',
        'tcp_keepalives_interval': '10',
        'tcp_keepalives_count': '3'
    }
)
```

## Expected Behavior After Fixes

1. **No more 503 errors** due to `object NoneType can't be used in 'await' expression`
2. **Automatic recovery** from temporary database connectivity issues
3. **Proper connection lifecycle management** preventing leaks
4. **Graceful handling** of Railway network initialization delays
5. **Detailed logging** for troubleshooting any remaining issues

## Monitoring and Troubleshooting

### Health Check Endpoint
```
GET /health
```
Returns comprehensive service status including:
- Database connection status
- Pool statistics (min/max/current/available connections)
- Service uptime and status
- Error details if any

### Key Log Messages to Monitor

**Success**:
```
✅ Database connection pool created successfully
🚀 KnowledgeBot Configuration Service started successfully
```

**Issues** (should be automatically resolved):
```
⚠️ Existing pool health check failed: object NoneType can't be used in 'await' expression
🔄 Creating new connection pool...
```

**Fatal Errors** (require manual intervention):
```
❌ Failed to create database connection pool
❌ DATABASE_URL environment variable is required
```

## Deployment Instructions

1. **The fixes are already applied** to the backend code in this repository
2. **Deploy the updated service** to Railway
3. **Monitor the logs** - you should see successful startup messages instead of the asyncpg errors
4. **Check the `/health` endpoint** for service status and database connection statistics

## Testing

To verify the fixes work correctly:

1. **Check the health endpoint**: Should return `"database": "healthy"`
2. **Test database operations**: All endpoints should work without 503 errors
3. **Monitor logs**: No more `object NoneType can't be used in 'await' expression` errors
4. **Load testing**: Service should handle concurrent requests without pool exhaustion

The fixes directly address the core issue where asyncpg's connection pool was returning `None` instead of connections, which was causing your entire configuration service to fail.