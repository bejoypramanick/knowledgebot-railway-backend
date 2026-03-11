# Task 12: Clear Agent Cache When Response Policy/Timeout Change

**Date:** March 11, 2026  
**Status:** ✅ COMPLETED  
**Commit:** caed76b

---

## Overview

When Response Policy or Response Timeout settings are changed from the UI, the agent cache is now cleared to ensure the next message uses the updated settings.

---

## Problem

Previously, when you changed Response Policy or Response Timeout settings in the UI, the cached agent still had the old settings. The next message would use the old configuration instead of the new one.

---

## Solution

### 1. Updated `clear_agent_cache()` Method

**File:** `chatbot_orchestration/service/agent_manager.py`

**Before:**
```python
def clear_agent_cache(self, session_id: str):
    """Clear cached agent for a session."""
    if session_id in self.agent_cache:
        del self.agent_cache[session_id]
        logger.info(f"🗑️ Cleared cached agent for session: {session_id}")
```

**After:**
```python
def clear_agent_cache(self, session_id: str = None):
    """Clear cached agent for a session or all sessions.
    
    Args:
        session_id: If provided, clear only this session's cache. If None, clear all caches.
    """
    if session_id:
        if session_id in self.agent_cache:
            del self.agent_cache[session_id]
            logger.info(f"🗑️ Cleared cached agent for session: {session_id}")
    else:
        # Clear all cached agents
        cache_size = len(self.agent_cache)
        self.agent_cache.clear()
        logger.info(f"🗑️ Cleared all cached agents ({cache_size} sessions)")
```

Now supports clearing all caches when `session_id=None`.

### 2. Added `/internal/clear-agent-cache` Endpoint

**File:** `chatbot_orchestration/routers/router.py`

```python
@router.post("/internal/clear-agent-cache")
async def clear_agent_cache(request: Request):
    """Clear agent cache when configuration changes.

    Called by configuration service when chatbot config is saved.
    This ensures the next message will use the updated configuration.
    """
    try:
        from ..service.agent_manager import agent_manager

        # Get optional session_id from query params
        session_id = request.query_params.get("session_id", None)

        if session_id:
            logger.info(f"🔄 Clearing agent cache for session: {session_id}")
            agent_manager.clear_agent_cache(session_id)
            return {
                "success": True,
                "message": f"Agent cache cleared for session: {session_id}"
            }
        else:
            logger.info("🔄 Clearing all agent caches")
            agent_manager.clear_agent_cache()  # Clear all
            return {
                "success": True,
                "message": "All agent caches cleared"
            }
    except Exception as e:
        logger.error(f"❌ Error clearing agent cache: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing agent cache: {str(e)}")
```

### 3. Configuration Service Calls Cache Clearing

**File:** `configuration/routers/router.py` (already implemented in previous commit)

```python
# Clear agent cache in chatbot-orchestration service
# This ensures the next message will use the updated configuration
try:
    logger.info("🔄 Clearing agent cache in chatbot-orchestration service...")
    import httpx
    import os
    
    chatbot_service_url = os.getenv('CHATBOT_ORCHESTRATION_URL', 'http://localhost:8001')
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{chatbot_service_url}/internal/clear-agent-cache",
            timeout=5.0
        )
        
        if response.status_code == 200:
            logger.info("✅ Agent cache cleared successfully")
        else:
            logger.warning(f"⚠️ Failed to clear agent cache: {response.status_code}")
except Exception as cache_error:
    logger.warning(f"⚠️ Could not clear agent cache: {cache_error}")
    # Don't fail the request if cache clearing fails
```

---

## How It Works

### Flow

1. **User changes Response Policy or Response Timeout** in the UI
2. **Configuration is saved** → `save_chatbot_config()` endpoint is called
3. **Cache clearing is triggered** → Configuration service calls `/internal/clear-agent-cache`
4. **All agent caches are cleared** → Next message will create a fresh agent
5. **Fresh agent is created** → Uses the updated Response Policy/Timeout settings
6. **Model response uses new settings** → ✅ Updated settings are applied!

### Endpoint Usage

**Clear all agent caches:**
```bash
POST /internal/clear-agent-cache
```

**Clear specific session cache:**
```bash
POST /internal/clear-agent-cache?session_id=session_12345
```

---

## Testing

To verify the fix works:

1. **Change Response Policy** (e.g., from "Strict" to "Relaxed")
2. **Change Response Timeout** (e.g., from 30s to 60s)
3. **Send a message** to the chatbot
4. **Verify the response** uses the new settings

### Expected Behavior

- ✅ Configuration is saved successfully
- ✅ Logs show "🔄 Clearing agent cache in chatbot-orchestration service..."
- ✅ Logs show "✅ Agent cache cleared successfully"
- ✅ Next message uses updated Response Policy/Timeout
- ✅ Model response reflects the new settings

---

## Files Modified

1. **chatbot_orchestration/service/agent_manager.py**
   - Updated `clear_agent_cache()` to support clearing all caches

2. **chatbot_orchestration/routers/router.py**
   - Added `/internal/clear-agent-cache` POST endpoint

---

## Deployment

- ✅ Commit: caed76b
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Verification

After deployment, check logs:

```bash
# Should see cache clearing being triggered
railway logs --service configuration | grep "Clearing agent cache"

# Should see successful cache clearing
railway logs --service chatbot-orchestration | grep "Cleared all cached agents"

# Should see new agent being created with updated settings
railway logs --service chatbot-orchestration | grep "CREATE_AGENT"
```

---

## Related Tasks

- **Task 11:** Custom Persona Not Applied to Model Response (uses same cache clearing mechanism)
- **Task 10:** Capture Router Request Mapping in Logs
- **Task 9:** Fix OTEL KeyError - Duplicate Attribute Setting

---

## Summary

Task 12 is now complete. When Response Policy or Response Timeout settings are changed from the UI, the agent cache is automatically cleared. This ensures the next message uses the updated settings. The implementation includes:

- Updated `clear_agent_cache()` method to support clearing all caches
- New `/internal/clear-agent-cache` endpoint in chatbot-orchestration service
- Configuration service calls this endpoint when config is saved
- Comprehensive logging with emoji indicators

---

**Generated:** March 11, 2026  
**Status:** ✅ Completed and Deployed  
**Commit:** caed76b
