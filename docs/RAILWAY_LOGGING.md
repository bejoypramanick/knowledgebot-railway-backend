# Railway Logging Configuration Guide

This guide explains how logging is configured for Railway deployment and how to troubleshoot logging issues.

## Problem: Logs Not Visible in Railway

Railway captures logs from `stdout` and `stderr`, but the default Python logging configuration may not output to the correct streams or use compatible formats.

## Solution: Railway-Compatible Logging

### 1. Automatic Configuration

The system now automatically detects Railway environment and configures logging appropriately:

```python
from shared.logging_config import auto_configure_logging

# Automatically configures based on environment
logger = auto_configure_logging("your_service_name")
```

### 2. Manual Configuration

For manual control over logging:

```python
from shared.logging_config import setup_railway_logging

# Configure for Railway deployment
logger = setup_railway_logging("your_service_name", level="INFO")
```

### 3. Individual Loggers

Get Railway-compatible loggers for specific modules:

```python
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)
logger.info("This will be visible in Railway logs")
```

## Key Features

### Railway Environment Detection
The system automatically detects Railway by checking:
- `RAILWAY_ENVIRONMENT` environment variable
- `RAILWAY_SERVICE_NAME` environment variable  
- `RAILWAY_PROJECT_NAME` environment variable

### Log Format
Railway-compatible format:
```
2024-01-28 12:00:00 [INFO] api_gateway: Starting up service
2024-01-28 12:00:01 [ERROR] token_tracker: Database connection failed
```

### Output Stream
- **Railway**: Forces output to `stdout` (captured by Railway)
- **Local**: Uses standard logging configuration

### Log Levels
Configure via environment variable:
```bash
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Troubleshooting

### 1. Check Environment Variables
Ensure these are set in Railway:
```bash
LOG_LEVEL=INFO
RAILWAY_ENVIRONMENT=production
```

### 2. Verify Logger Configuration
Add this test to verify logging works:
```python
from shared.logging_config import get_railway_logger

logger = get_railway_logger("test")
logger.info("🧪 Test log message - this should appear in Railway")
```

### 3. Check for Multiple Handlers
The new logging system removes conflicting handlers and ensures single output to stdout.

### 4. Verify Propagation
All loggers now propagate to root logger to ensure consistent output.

## Migration Guide

### Before (Old Configuration)
```python
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
```

### After (New Configuration)
```python
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)
```

## Files Updated

The following files have been updated with Railway-compatible logging:

### Core Logging
- `shared/logging_config.py` - New Railway logging configuration

### Services
- `api_gateway/main.py` - Updated to use Railway logging
- `shared/utils.py` - Updated exception handling
- `shared/token_tracker.py` - Updated token tracking logs
- `shared/token_metrics.py` - Updated metrics logging
- `shared/token_alerting.py` - Updated alerting logs
- `shared/rate_limiter.py` - Updated rate limiting logs

## Testing in Railway

1. Deploy to Railway
2. Check the logs tab
3. Look for messages like:
   ```
   🚀 Railway logging initialized for service: api_gateway
   📊 Log level set to: INFO
   🚂 Railway environment detected - logging configured for deployment
   ```

4. Test with API calls to verify runtime logging

## Best Practices

### 1. Use Structured Logging
```python
logger.info("User action completed", extra={
    "user_id": user_id,
    "action": "token_track",
    "tokens": token_count
})
```

### 2. Include Context
```python
logger.info(f"Processing request for session {session_id}")
logger.error(f"Database error in {operation_name}", exc_info=True)
```

### 3. Use Appropriate Levels
- `DEBUG`: Detailed debugging information
- `INFO`: General information about service operation
- `WARNING`: Something unexpected but not critical
- `ERROR`: Error conditions that should be investigated
- `CRITICAL`: Serious errors that may cause service failure

### 4. Avoid Print Statements
Use `logger.info()` instead of `print()` for Railway compatibility.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `RAILWAY_ENVIRONMENT` | - | Set automatically by Railway |
| `RAILWAY_SERVICE_NAME` | - | Set automatically by Railway |
| `RAILWAY_PROJECT_NAME` | - | Set automatically by Railway |

## Monitoring

With the new logging configuration, you should see:

1. **Startup logs**: Service initialization messages
2. **Request logs**: API request processing
3. **Error logs**: Detailed error information with tracebacks
4. **Metrics logs**: Token tracking and performance metrics
5. **Alert logs**: System alerts and notifications

All logs will now be properly formatted and visible in the Railway logs tab.
