# Human Agent Message Visibility Fix

## Problem
When a customer requests a human agent, the admin/agent does not see the customer's message in the ChatLog UI conversation list.

## Root Causes

### 1. Duplicate Tool Calls
The Gemini model was calling `request_human_agent_connection` twice in the same response, causing duplicate agent assignments.

### 2. Message Broadcast Timing Issue
Customer messages were being broadcast BEFORE an agent was assigned to the session:
1. Customer sends "agent" message
2. Message is saved → broadcast to channels (no agent assigned yet!)
3. AI calls `request_human_agent_connection` tool
4. Agent is assigned to session
5. AI response is saved

Since the customer message was broadcast before assignment, it only went to the broadcast channel (`agent:events:broadcast`), which only admins subscribe to, not human_agents.

### 3. Redis Pub/Sub is Fire-and-Forget
Redis Pub/Sub doesn't queue messages - if there's no subscriber when a message is published, it's lost forever. Re-broadcasting doesn't help.

## Solutions Implemented

### Fix 1: Prevent Duplicate Tool Calls (Idempotency)
Added a check at the beginning of `request_human_agent_connection` to see if an agent is already assigned:

```python
# Check if agent is already assigned (prevents duplicate calls)
try:
    from shared.sqlalchemy_db import get_db_session
    from sqlalchemy import text
    
    async with get_db_session() as db_session:
        check_query = "SELECT assigned_agent_email FROM chat_sessions WHERE id = :id LIMIT 1"
        result = await db_session.execute(text(check_query), {"id": session_numeric_id})
        row = result.mappings().first()
        
        if row and row.get('assigned_agent_email'):
            assigned_agent = row['assigned_agent_email']
            logger.info(f"✅ Agent already assigned: {assigned_agent} - skipping duplicate assignment")
            return f"👋 You're already connected to a human agent ({assigned_agent}). They will respond shortly. 💪\n"
except Exception as e:
    logger.warning(f"⚠️ Could not check existing agent assignment: {e}")
    # Continue with assignment attempt if check fails
```

**Location**: `knowledgebot-railway-backend/chatbot_orchestration/tools/knowledge_tools.py`

### Fix 2: Assign Agent BEFORE AI Responds
The key insight: instead of letting the AI detect and assign the agent via tool call, we detect agent requests BEFORE invoking the AI and assign immediately.

**New Flow**:
1. Customer sends "agent" message
2. **Detect agent request keywords** (agent, human, person, support, etc.)
3. **Assign agent immediately** via configuration service
4. Save customer message to database
5. **Broadcast session_update with ALL messages** to assigned agent
6. Send confirmation to customer
7. **Skip AI response entirely**

If no agent is available (503 error), fall back to normal AI response.

**Implementation**:

```python
def _detect_agent_request(self, message: str) -> bool:
    """Detect if user is explicitly requesting a human agent."""
    message_lower = message.lower().strip()
    
    agent_keywords = [
        "agent", "human", "person", "representative", "support",
        "help me", "speak to someone", "talk to someone", "connect me",
        "real person", "customer service", "customer support"
    ]
    
    for keyword in agent_keywords:
        if keyword in message_lower:
            return True
    return False

# In stream_agent_response, before AI invocation:
user_wants_agent = self._detect_agent_request(message)

if user_wants_agent:
    # Assign agent immediately
    # Get all messages from database
    # Broadcast session_update with messages array to agent
    # Send confirmation to customer
    # Return (skip AI)
```

**Location**: `knowledgebot-railway-backend/chatbot_orchestration/service/streaming_service.py`

## How It Works Now

1. Customer sends "agent" message
2. **Keyword detection** identifies agent request
3. **Agent assigned immediately** (before AI responds)
4. Customer message saved to database
5. **All messages loaded from database** (including the "agent" message)
6. **session_update event broadcast** to agent with complete messages array
7. Agent's ChatLog UI receives session with all messages via SSE
8. Customer receives confirmation message
9. **AI never invoked** for agent requests

If no agent available:
- Configuration service returns 503
- System falls back to normal AI response
- AI can still use `request_human_agent_connection` tool if needed

## Benefits

1. **No lost messages**: Agent is subscribed before messages are broadcast
2. **Complete history**: session_update includes all messages from database
3. **Faster response**: No AI invocation needed for simple agent requests
4. **Graceful fallback**: If no agent available, AI responds normally
5. **No duplicate assignments**: Idempotency check prevents double-assignment

## Testing

To verify the fix:
1. Open ChatLog UI as admin/human_agent
2. Open customer chatbot in another window
3. Customer types "agent" or "I need help"
4. Verify that:
   - The customer's "agent" message appears in ChatLog conversation list
   - The session appears in ChatLog session list immediately
   - No duplicate assignments occur
   - All previous customer messages are visible
   - If no agent available, AI responds normally

## Files Modified

1. `knowledgebot-railway-backend/chatbot_orchestration/service/streaming_service.py`
   - Added `_detect_agent_request()` method for keyword detection
   - Added pre-AI agent assignment logic with complete message loading
   - Broadcasts session_update with all messages to assigned agent

2. `knowledgebot-railway-backend/chatbot_orchestration/tools/knowledge_tools.py`
   - Added idempotency check for duplicate tool calls
   - Kept as fallback for AI-detected agent requests

## Related Issues

- Duplicate tool calls by Gemini model
- Message broadcast timing with agent assignment
- Redis Pub/Sub fire-and-forget behavior
- Channel subscription differences between admin and human_agent roles
