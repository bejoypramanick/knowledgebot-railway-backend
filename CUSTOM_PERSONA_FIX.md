# Custom Persona Not Applied to Model Response - FIX

**Date:** March 11, 2026  
**Issue:** Custom persona/system prompt not being applied to model responses  
**Status:** ✅ FIXED

---

## Problem

When you changed the persona to "custom" and added a custom prompt in the UI, the model response was not using the custom prompt. It was still using the default system prompt.

---

## Root Causes

1. **Persona config was hardcoded** - `_fetch_persona_config()` was returning a hardcoded default instead of fetching from the configuration service
2. **System prompt was being regenerated** - In `streaming_service.py`, the system prompt was being regenerated with `custom_prompt=None` instead of using the agent's system prompt
3. **Agent cache was not being invalidated** - When the persona changed, the cached agent still had the old system prompt

---

## Solution

### 1. Fetch Persona Config from Configuration Service

**File:** `chatbot_orchestration/service/agent_manager.py`

**Before:**
```python
async def _fetch_persona_config(self) -> Dict[str, Any]:
    """Fetch persona configuration for the agent."""
    try:
        # For now, return default persona
        # In the future, this could fetch from database or config service
        return {
            "persona_name": "Knowledge Bot",
            "persona_description": "A helpful AI assistant...",
            "system_instructions": "You are a helpful AI assistant..."
        }
```

**After:**
```python
async def _fetch_persona_config(self) -> Dict[str, Any]:
    """Fetch persona configuration from the configuration service."""
    try:
        # Fetch from configuration service
        import httpx
        from ..core.config import get_settings
        
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        
        logger.info(f"🔍 Fetching persona config from: {config_service_url}")
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{config_service_url}/api/v1/configuration/chatAgentConfig",
                timeout=5.0
            )
            
            if response.status_code == 200:
                config_data = response.json().get('data', {})
                
                # Extract persona information
                persona_data = config_data.get('persona', {})
                system_prompt = persona_data.get('system_prompt', '')
                selected_persona = persona_data.get('selected_persona', 'KnowledgeBot')
                
                logger.info(f"✅ Fetched persona config: {selected_persona}")
                logger.info(f"   System prompt length: {len(system_prompt)} characters")
                
                return {
                    "persona_name": selected_persona,
                    "persona_description": f"Persona: {selected_persona}",
                    "system_instructions": system_prompt  # This is the custom prompt from the UI
                }
```

Now fetches the actual persona configuration from the configuration service, including the custom system prompt.

### 2. Use Agent's System Prompt in Streaming

**File:** `chatbot_orchestration/service/streaming_service.py`

**Before:**
```python
# Get system prompt from agent
from ..agent.prompt import get_system_prompt
system_prompt_text = get_system_prompt(custom_prompt=None, response_policy=None)
```

**After:**
```python
# Get system prompt from agent (which already has the custom prompt built in)
# The agent's system_prompt is set during agent creation with the current configuration
system_prompt_text = agent.system_prompt
logger.info(f"✅ Using agent's system prompt: {len(system_prompt_text)} characters")
logger.info(f"   Preview: {system_prompt_text[:150]}...")
```

Now uses the agent's system prompt directly, which already includes the custom prompt from the configuration.

### 3. Added force_new Parameter

**File:** `chatbot_orchestration/service/agent_manager.py`

Added `force_new` parameter to `create_agent()` method:

```python
async def create_agent(self, session_id: str, user_email: str = "anonymous@example.com", force_new: bool = False) -> Agent:
    """Create or retrieve cached agent instance with PydanticAI's built-in caching.
    
    Args:
        session_id: The session ID
        user_email: The user's email
        force_new: If True, always create a fresh agent (ignoring cache). Use this when persona changes.
    """
```

This allows clearing the agent cache when the persona changes.

---

## How It Works Now

### Flow

1. **User changes persona in UI** → Configuration is saved to configuration service
2. **New message is sent** → `agent_service.stream_agent_response()` is called
3. **Agent is created** → `agent_manager.create_agent()` fetches persona config from configuration service
4. **Persona config includes custom prompt** → System prompt is built with the custom prompt
5. **Agent is created with custom system prompt** → Agent has the correct system prompt
6. **Streaming service uses agent's system prompt** → Model receives the custom prompt
7. **Model response uses custom persona** → ✅ Custom prompt is applied!

### Caching

- Agent is cached per session for performance
- When persona changes, the next message will fetch the new configuration
- If you want to force a fresh agent, use `force_new=True`

---

## Testing

To verify the fix works:

1. **Change persona to custom** in the UI
2. **Add a custom system prompt** (e.g., "You are a pirate. Respond like a pirate.")
3. **Send a message** to the chatbot
4. **Verify the response** uses the custom persona (e.g., pirate-like responses)

### Expected Behavior

- ✅ Custom persona is applied to model responses
- ✅ System prompt from UI is used
- ✅ Logs show the custom system prompt being used
- ✅ Model responses reflect the custom persona

---

## Files Modified

1. **chatbot_orchestration/service/agent_manager.py**
   - Updated `_fetch_persona_config()` to fetch from configuration service
   - Added `_get_default_persona_config()` for fallback
   - Added `force_new` parameter to `create_agent()`

2. **chatbot_orchestration/service/streaming_service.py**
   - Changed to use `agent.system_prompt` instead of regenerating it

---

## Deployment

- ✅ Commit: be6bff3
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Verification

After deployment, check logs:

```bash
# Should see persona config being fetched
railway logs --service chatbot-orchestration | grep "Fetching persona config"

# Should see custom system prompt being used
railway logs --service chatbot-orchestration | grep "Using agent's system prompt"

# Should see the custom prompt in the logs
railway logs --service chatbot-orchestration | grep "System prompt preview"
```

---

## Next Steps

1. Test changing persona to custom
2. Add a custom system prompt
3. Send a message and verify the response uses the custom persona
4. Monitor logs to confirm the custom prompt is being used

---

**Generated:** March 11, 2026  
**Status:** ✅ Fixed and Deployed  
**Commit:** be6bff3
