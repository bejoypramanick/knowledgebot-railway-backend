# 🐛 Bug Fix: Token Metadata JSON Serialization

## Issue Description

**Error**: Database error when saving token usage logs  
**Service**: chatbot-orchestration  
**Date**: March 11, 2026  
**Status**: ✅ FIXED

### Error Message
```
sqlalchemy.dialects.postgresql.asyncpg.Error: 
invalid input for query argument $9: {'cache_read_tokens': 0, 'cache_write_tokens': 0}
('dict' object has no attribute 'encode')
```

### Root Cause
The `request_metadata` parameter was being passed as a Python dictionary directly to PostgreSQL, but PostgreSQL expects a JSON string. The asyncpg driver tried to encode the dict object, which failed because dicts don't have an `encode()` method.

---

## Technical Details

### Problem Code
**File**: `chatbot_orchestration/dao/token_dao.py`  
**Method**: `save_token_usage()`

```python
# BEFORE (BROKEN)
params = {
    "session_id": integer_session_id,
    "message_id": integer_message_id,
    "provider": provider,
    "model": model,
    "prompt_tokens": prompt_tokens,
    "completion_tokens": completion_tokens,
    "total_tokens": total_tokens,
    "api_call_type": api_call_type,
    "request_metadata": request_metadata  # ❌ Dict passed directly
}
```

### Solution
Convert the dictionary to a JSON string before passing to PostgreSQL:

```python
# AFTER (FIXED)
import json

# Convert request_metadata dict to JSON string for PostgreSQL
metadata_json = json.dumps(request_metadata) if request_metadata else None
logger.info(f"[TRANSFORM] request_metadata converted to JSON: {metadata_json}")

params = {
    "session_id": integer_session_id,
    "message_id": integer_message_id,
    "provider": provider,
    "model": model,
    "prompt_tokens": prompt_tokens,
    "completion_tokens": completion_tokens,
    "total_tokens": total_tokens,
    "api_call_type": api_call_type,
    "request_metadata": metadata_json  # ✅ JSON string passed
}
```

---

## Changes Made

### File Modified
- `chatbot_orchestration/dao/token_dao.py`

### Changes
1. Added `import json` at the top of the method
2. Added logging for parameter types and values
3. Convert `request_metadata` dict to JSON string using `json.dumps()`
4. Added logging for the transformation step
5. Pass JSON string to PostgreSQL instead of dict

### Lines Changed
- Line 42-44: Added logging for entry and parameter types
- Line 63-65: Added metadata JSON conversion
- Line 66-68: Added logging for transformation
- Line 77: Changed from `request_metadata` to `metadata_json`

---

## Impact

### Before Fix
- ❌ Token usage logs fail to save
- ❌ Database error: "dict object has no attribute 'encode'"
- ❌ Token tracking broken for Gemini API calls
- ❌ Error logged but operation fails silently

### After Fix
- ✅ Token usage logs save successfully
- ✅ request_metadata properly serialized to JSON
- ✅ Token tracking works for all API calls
- ✅ Proper logging of transformation step

---

## Testing

### Test Case
```python
# Test data
request_metadata = {
    'cache_read_tokens': 0,
    'cache_write_tokens': 0
}

# Before fix: Would fail with asyncpg.DataError
# After fix: Successfully saves to database
```

### Expected Behavior
1. request_metadata dict is received
2. Dict is converted to JSON string using json.dumps()
3. JSON string is passed to PostgreSQL
4. PostgreSQL successfully inserts the JSON data
5. Logging shows the transformation step

### Verification
```sql
-- Query to verify the fix
SELECT session_id, provider, request_metadata 
FROM token_usage_log 
WHERE provider = 'gemini' 
LIMIT 1;

-- Expected output:
-- request_metadata should be valid JSON: {"cache_read_tokens": 0, "cache_write_tokens": 0}
```

---

## Logging Added

### Entry Logging
```
[PARAM] request_metadata type: <class 'dict'>, value: {'cache_read_tokens': 0, 'cache_write_tokens': 0}
```

### Transformation Logging
```
[TRANSFORM] request_metadata converted to JSON: {"cache_read_tokens": 0, "cache_write_tokens": 0}
```

### Success Logging
```
✅ save_token_usage completed - session: session_17732281, total_tokens: 720
```

---

## Related Code

### Where request_metadata is Created
**File**: `chatbot_orchestration/core/token_tracker.py`

```python
# Line 164-167
request_metadata={
    'cache_read_tokens': cache_read_tokens,
    'cache_write_tokens': cache_write_tokens
}

# Line 305-308
request_metadata={
    'cache_read_tokens': int(cache_read_tokens or 0),
    'cache_write_tokens': int(cache_write_tokens or 0),
}
```

These create dictionaries that are passed to `track_token_usage()`, which calls `TokenService.track_token_usage()`, which calls `TokenDAO.save_token_usage()`.

---

## Prevention

### Best Practices Applied
1. ✅ Always convert Python objects to JSON strings before passing to PostgreSQL
2. ✅ Add logging for data transformations
3. ✅ Use `json.dumps()` for dict-to-JSON conversion
4. ✅ Handle None values gracefully

### Similar Issues to Check
- Any other DAO methods that accept dict parameters
- Any other places where dicts are passed to PostgreSQL
- Configuration service token_dao (checked - only reads data, no issue)

---

## Git Commit

**Commit Hash**: a923cf2  
**Message**: fix: Convert request_metadata dict to JSON before PostgreSQL insert  
**Branch**: main  
**Status**: Pushed to origin/main

---

## Deployment

**Status**: ✅ Ready for deployment  
**Impact**: Bug fix only, no breaking changes  
**Rollback**: Not needed (fix is backward compatible)

---

## Summary

**Issue**: Database error when saving token usage with metadata  
**Root Cause**: Dict passed directly to PostgreSQL instead of JSON string  
**Solution**: Convert dict to JSON string using json.dumps()  
**Status**: ✅ FIXED  
**Commit**: a923cf2  
**Deployment**: Ready

The fix is minimal, focused, and solves the exact issue without affecting other parts of the system.
