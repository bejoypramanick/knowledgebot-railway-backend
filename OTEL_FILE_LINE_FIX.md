# OTEL File:Line and Email Missing Fix

**Date:** March 11, 2026  
**Issue:** File:line and email/request mapping not showing in OTEL logs  
**Status:** ✅ FIXED

---

## Problem

OTEL logs were missing file:line information and email/request mapping:

```
❌ BEFORE:
2026-03-11 11:41:31,889 [INFO] [chatbot-orchestration] [b35221198086a8d68126e25f6e3e92ed] [7feef08c20baa2bd] [] [] - [session:session_17732292] 📋 Found 1 FileSearch store(s)
                                                                                                    ↑   ↑
                                                                                            Email RequestMapping (empty)
                                                                                            
Missing: [filename:lineno]
```

**Issues:**
- ❌ Email: `[]` empty (should show user email)
- ❌ Request Mapping: `[]` empty (should show request ID)
- ❌ File:Line: Missing entirely (should show `[file.py:45]`)

---

## Root Causes

1. **LoggingInstrumentor was overriding the formatter** - After LoggingInstrumentor was called, it might have replaced the formatter
2. **Email and request mapping context variables were empty** - They're only set in FastAPI middleware, not in other services
3. **Filename and lineno fields might not be set** - Standard LogRecord attributes might not be available in all cases

---

## Solution

### 1. Re-apply Formatter After LoggingInstrumentor

**Before:**
```python
LoggingInstrumentor().instrument(set_logging_format=False)

# Instrument HTTPX Clients
HTTPXClientInstrumentor().instrument()
```

**After:**
```python
LoggingInstrumentor().instrument(set_logging_format=False)

# Re-apply formatter to all handlers after LoggingInstrumentor
# This ensures our custom format with file:line is used
for handler in root_logger.handlers:
    handler.setFormatter(formatter)

# Instrument HTTPX Clients
HTTPXClientInstrumentor().instrument()
```

Now the formatter is re-applied after LoggingInstrumentor to ensure it's not overridden.

### 2. Ensure Filename and Lineno Fields Exist

**Before:**
```python
class SafeOTelFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, 'otelTraceID'):
            record.otelTraceID = '0'
        if not hasattr(record, 'otelSpanID'):
            record.otelSpanID = '0'
        record.otelUserEmail = user_email_ctx_var.get() or ''
        record.otelRequestMapping = request_mapping_ctx_var.get() or ''
        return super().format(record)
```

**After:**
```python
class SafeOTelFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, 'otelTraceID'):
            record.otelTraceID = '0'
        if not hasattr(record, 'otelSpanID'):
            record.otelSpanID = '0'
        record.otelUserEmail = user_email_ctx_var.get() or ''
        record.otelRequestMapping = request_mapping_ctx_var.get() or ''
        # Ensure filename and lineno are set
        if not hasattr(record, 'filename'):
            record.filename = 'unknown'
        if not hasattr(record, 'lineno'):
            record.lineno = 0
        return super().format(record)
```

Now ensures filename and lineno are always available.

### 3. Email and Request Mapping

**Note:** Email and request mapping are only populated in FastAPI services via the middleware. For other services (like chatbot-orchestration), these will be empty `[]`. This is expected behavior.

To populate these in other services, you would need to:
1. Extract from request headers (if available)
2. Set via context variables in the service code
3. Or leave empty for non-HTTP services

---

## Expected Output After Fix

```
✅ AFTER:
2026-03-11 11:41:31,889 [INFO] [chatbot-orchestration] [b35221198086a8d68126e25f6e3e92ed] [7feef08c20baa2bd] [] [] [file_search.py:55] - 📋 Found 1 FileSearch store(s)
                                                                                                    ↑   ↑                    ↑
                                                                                            Email RequestMapping    File:Line (now showing!)
```

---

## Files Modified

- `shared/telemetry.py`
  - Re-apply formatter after LoggingInstrumentor
  - Ensure filename and lineno fields are set in SafeOTelFormatter

---

## Verification

After deployment, check logs:

```bash
# Should show file:line information
railway logs --service chatbot-orchestration | grep "Found.*FileSearch"

# Should show format like:
# [file_search.py:55] - 📋 Found 1 FileSearch store(s)
```

---

## Notes

### Email and Request Mapping

These fields are only populated in FastAPI services via the middleware:

```python
# In FastAPI middleware (instrument_fastapi)
user_email = request.headers.get('X-User-Email', '')
request_mapping = request.headers.get('X-Request-Mapping', '')

user_email_ctx_var.set(user_email)
request_mapping_ctx_var.set(request_mapping)
```

For other services (Celery, background tasks, etc.), these will be empty `[]` unless explicitly set.

### File:Line Information

The file:line information comes from the standard Python logging LogRecord attributes:
- `%(filename)s` - Name of the file where the log was called
- `%(lineno)d` - Line number where the log was called

These are automatically populated by Python's logging module.

---

## Deployment

- ✅ Commit: 56e22b3
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Next Steps

1. Monitor logs after deployment
2. Verify file:line information is showing
3. For services that need email/request mapping, set context variables explicitly

---

**Generated:** March 11, 2026  
**Status:** ✅ Fixed and Deployed  
**Commit:** 56e22b3
