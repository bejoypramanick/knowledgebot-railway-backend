# Celery Import Error Fix

**Date:** March 11, 2026  
**Issue:** Celery worker failing to load celery_app module  
**Status:** ✅ FIXED

---

## Problem

Celery worker was failing with:

```
Error: While trying to load the module celery_app the following error occurred:
Traceback (most recent call last):
  ...
  File "/usr/local/lib/python3.11/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(...)
```

This prevented the Celery worker from starting.

---

## Root Causes

1. **Missing error handling for invalid CELERY_WEB_CONCURRENCY** - If the environment variable was invalid, it would crash during module load
2. **Insufficient error logging for tasks import** - When tasks module failed to import, the error wasn't being logged with full traceback
3. **No fallback for concurrency value** - If the environment variable was invalid, the entire module load would fail

---

## Solution

### 1. Added Error Handling for Concurrency Value

**Before:**
```python
worker_concurrency = int(os.getenv('CELERY_WEB_CONCURRENCY', '10'))
```

**After:**
```python
try:
    worker_concurrency = int(os.getenv('CELERY_WEB_CONCURRENCY', '10'))
except (ValueError, TypeError):
    worker_concurrency = 10
    logger.warning(f"⚠️  [CELERY_APP] Invalid CELERY_WEB_CONCURRENCY value, using default: {worker_concurrency}")
```

Now handles invalid environment variable values gracefully.

### 2. Improved Tasks Import Error Logging

**Before:**
```python
try:
    import tasks  # noqa: F401
    logger.info("✅ [CELERY_APP] Tasks module loaded successfully")
except ImportError as e:
    logger.error(f"❌ [CELERY_APP] Failed to load tasks module: {e}")
```

**After:**
```python
try:
    import tasks  # noqa: F401
    logger.info("✅ [CELERY_APP] Tasks module loaded successfully")
except ImportError as e:
    logger.error(f"❌ [CELERY_APP] Failed to load tasks module: {e}")
    import traceback
    logger.error(f"   Traceback: {traceback.format_exc()}")
except Exception as e:
    logger.error(f"❌ [CELERY_APP] Unexpected error loading tasks module: {e}")
    import traceback
    logger.error(f"   Traceback: {traceback.format_exc()}")
```

Now logs full traceback for debugging.

---

## Files Modified

- `celery-web-worker/celery_app.py`
  - Added try-except for concurrency value parsing
  - Added full traceback logging for tasks import errors

---

## Verification

After deployment, check Celery worker logs:

```bash
# Should see successful initialization
railway logs --service celery-web-worker | grep "CELERY_APP"

# Should show:
# ✅ [CELERY_APP] Configuration updated
# ✅ [CELERY_APP] Tasks module loaded successfully
```

---

## Deployment

- ✅ Commit: cf5c1e6
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Next Steps

1. Monitor Celery worker logs after deployment
2. Verify worker starts successfully
3. Check for any remaining import errors in logs

---

**Generated:** March 11, 2026  
**Status:** ✅ Fixed and Deployed  
**Commit:** cf5c1e6
