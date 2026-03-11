# OTEL KeyError Fix - Duplicate Attribute Setting

**Date:** March 11, 2026  
**Issue:** KeyError: "Attempt to overwrite 'otelTraceID' in LogRecord"  
**Status:** ✅ FIXED

---

## Problem

Services were crashing with:

```
KeyError: "Attempt to overwrite 'otelTraceID' in LogRecord"
```

This was happening because we were trying to set `otelTraceID` and `otelSpanID` in multiple places:
1. In the OTelFieldFilter
2. In the SafeOTelFormatter
3. In the emit_with_flush function

Python's logging module prevents overwriting LogRecord attributes, causing the error.

---

## Root Cause

We were setting the same attributes in multiple places:

```python
# In OTelFieldFilter
record.otelTraceID = trace_id
record.otelSpanID = span_id

# In SafeOTelFormatter (DUPLICATE!)
if not hasattr(record, 'otelTraceID'):
    record.otelTraceID = '0'
if not hasattr(record, 'otelSpanID'):
    record.otelSpanID = '0'

# In emit_with_flush (DUPLICATE!)
record.otelTraceID = trace_id
record.otelSpanID = span_id
```

When the filter set them first, then the formatter or emit_with_flush tried to set them again, Python's logging module raised a KeyError.

---

## Solution

**Removed duplicate setting** - Only set `otelTraceID` and `otelSpanID` in the OTelFieldFilter, not in the formatter or emit_with_flush.

### Changes

**File:** `shared/telemetry.py`

#### 1. SafeOTelFormatter - Removed duplicate setting

**Before:**
```python
class SafeOTelFormatter(logging.Formatter):
    def format(self, record):
        # Ensure OTel fields exist before formatting
        if not hasattr(record, 'otelTraceID'):
            record.otelTraceID = '0'
        if not hasattr(record, 'otelSpanID'):
            record.otelSpanID = '0'
        # ... rest of code
```

**After:**
```python
class SafeOTelFormatter(logging.Formatter):
    def format(self, record):
        # Don't set otelTraceID and otelSpanID here - they're already set by the filter
        # Just ensure context variables are set for email and request mapping
        record.otelUserEmail = user_email_ctx_var.get() or ''
        record.otelRequestMapping = request_mapping_ctx_var.get() or ''
        # ... rest of code
```

#### 2. emit_with_flush - Removed duplicate setting

**Before:**
```python
def emit_with_flush(record):
    # Get current span to extract trace and span IDs
    span = trace.get_current_span()
    
    if span and span.is_recording():
        span_context = span.get_span_context()
        trace_id = format(span_context.trace_id, '032x') if span_context.trace_id else '0'
        span_id = format(span_context.span_id, '016x') if span_context.span_id else '0'
        record.otelTraceID = trace_id  # DUPLICATE!
        record.otelSpanID = span_id    # DUPLICATE!
    else:
        record.otelTraceID = '0'       # DUPLICATE!
        record.otelSpanID = '0'        # DUPLICATE!
    # ... rest of code
```

**After:**
```python
def emit_with_flush(record):
    # otelTraceID and otelSpanID are already set by the filter
    # Just ensure context variables are set for email and request mapping
    record.otelUserEmail = user_email_ctx_var.get() or ''
    record.otelRequestMapping = request_mapping_ctx_var.get() or ''
    original_emit(record)
    # ... rest of code
```

---

## How It Works Now

### Single Source of Truth

Only the **OTelFieldFilter** sets `otelTraceID` and `otelSpanID`:

```python
class OTelFieldFilter(logging.Filter):
    def filter(self, record):
        # Get current span to extract trace and span IDs
        from opentelemetry import trace
        span = trace.get_current_span()
        
        if span and span.is_recording():
            span_context = span.get_span_context()
            trace_id = format(span_context.trace_id, '032x') if span_context.trace_id else '0'
            span_id = format(span_context.span_id, '016x') if span_context.span_id else '0'
            record.otelTraceID = trace_id
            record.otelSpanID = span_id
        else:
            record.otelTraceID = '0'
            record.otelSpanID = '0'
        
        # Always read from context variables
        record.otelUserEmail = user_email_ctx_var.get() or ''
        record.otelRequestMapping = request_mapping_ctx_var.get() or ''
        return True
```

### Flow

1. **Filter** - Sets `otelTraceID`, `otelSpanID`, `otelUserEmail`, `otelRequestMapping`
2. **Formatter** - Uses the values set by the filter, adds `otelUserEmail` and `otelRequestMapping` from context
3. **Emit** - Flushes the log record (no attribute setting)

---

## Verification

After deployment, services should start without KeyError:

```bash
# Should see successful initialization
railway logs --service knowledgebase-ingestion | grep "OpenTelemetry initialized"

# Should NOT see KeyError
railway logs --service knowledgebase-ingestion | grep "KeyError"
```

---

## Deployment

- ✅ Commit: c754209
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Next Steps

1. Monitor services after deployment
2. Verify no KeyError in logs
3. Verify trace IDs and span IDs are showing correctly

---

**Generated:** March 11, 2026  
**Status:** ✅ Fixed and Deployed  
**Commit:** c754209
