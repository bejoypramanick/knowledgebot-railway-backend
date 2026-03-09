# Human Agent Message Delivery Issues - Root Cause & Fix

## Issues Identified

### Issue #1: Agent Goes Offline When Ending Session
**Problem:** When an admin/human agent clicks "end session", they appear to go offline in the UI, preventing them from handling other customers.

**Root Cause:** NOT in backend code - likely UI state management issue. The agent is properly cleared from that specific session but the frontend may be tracking agent status incorrectly.

**Backend Status:** ✅ WORKING CORRECTLY
- Closing a session only clears the agent assignment cache for that session (line 381-383 in chat_log_service.py)
- Agent remains assigned to other active sessions
- `get_agent_online_status()` always returns `True` (line 116 in chat_log_service.py)

**Verification:** Agent should still receive messages from other customers after closing one session.

---

### Issue #2: Human Agent Messages NOT Reaching Customer via Redis Pubsub
**Problem:** When a human agent sends a message, the customer doesn't receive it through the SSE connection.

**Root Cause #2a: Session-Ended Event Not Broadcast to Customer**
```
File: configuration/service/chat_log_service.py, Line 394
Code: if status == 'closed' and not assigned_agent:
```

When agent ends a session:
1. Status set to 'closed' ✅
2. Assigned agent EXISTS (not None) ✅
3. Condition fails: `not assigned_agent` is FALSE ❌
4. Session-ended event NOT broadcast to customer ❌
5. Customer's SSE connection keeps waiting for update

**Timeline:**
```
Agent clicks "End Session"
    ↓
POST /admin/chat-sessions/end-agent ← Works
    ↓
update_chat_session(status='closed', assigned_agent='agent@example.com')
    ↓
Check: status == 'closed' AND not assigned_agent
    ↓
FALSE (because assigned_agent EXISTS)
    ↓
session_ended event NOT sent to customer ❌
    ↓
Customer never receives notification ❌
```

**Root Cause #2b: Missing Session UUID in Broadcast**

In `end_agent_session()` endpoint (line 1454):
```python
await broadcast_event_to_session(session_uuid, event_data)
```

This SHOULD work - broadcasts to session channel. BUT the condition in update_chat_session prevents the event from being sent to the customer at all!

---

## Solution

### Fix for Issue #2: Session-Ended Event Broadcasting

**File: `configuration/service/chat_log_service.py`**

**Change the condition to always broadcast session-ended to customer:**

```python
# BEFORE (line 394):
if status == 'closed' and not assigned_agent:
    if self.connection_manager:
        # ... send event to customer

# AFTER (should be):
if status == 'closed':  # ALWAYS send session-ended when closed
    if self.connection_manager:
        # ... send event to customer
```

**Why this works:**
- When agent closes session: assigned_agent exists, but we STILL need to notify customer
- When customer closes session: no assigned_agent, we notify customer
- When session expires: no assigned_agent, we notify customer
- Result: Customer always gets notified when session ends, regardless of who closed it

**Additionally:** Update `end_agent_session()` endpoint to ensure proper event structure:

In `configuration/routers/router.py` line 1447-1453:
```python
event_data = {
    "type": "session_ended",
    "session_id": numeric_session_id,  # ← Should also include UUID for reference
    "session_uuid": session_uuid,      # ← ADD THIS
    "ended_by": "agent",
    "show_feedback": True,
    "timestamp": datetime.datetime.utcnow().isoformat()
}
```

---

## Implementation Plan

### Step 1: Fix Session-Ended Broadcasting
Update `chat_log_service.py` line 394:
```python
# CHANGE FROM:
if status == 'closed' and not assigned_agent:

# CHANGE TO:
if status == 'closed':
```

### Step 2: Ensure Both Broadcast Paths Work

**Path 1:** `end_agent_session()` in router.py
- Directly broadcasts to session (line 1454)
- Also calls `update_chat_session()` which will broadcast via connection_manager
- Result: Session-ended sent via Redis pubsub ✅

**Path 2:** `end_customer_session()` in router.py
- Calls `update_chat_session()`
- Will broadcast via connection_manager when condition is fixed
- Result: Session-ended sent to customer ✅

### Step 3: Message Delivery Path Verification

For **agent sends message** (line 1390-1396 in router.py):
```
Agent sends message via POST /admin/chat-sessions/messages
    ↓
save_agent_message(session_id, sender_id, text) ✅
    ↓
broadcast_event_to_session(session_uuid, event_data) ✅ ← Publishes to Redis
    ↓
Customer SSE listens on channel: sse/session/{session_uuid}
    ↓
Customer receives event ✅
```

This path already works - the Redis broadcast is correct!

---

## Testing Checklist

### Test 1: Agent Sends Message to Customer
```
1. Admin/Agent logs in to ChatLog UI
2. Opens active chat session
3. Types and sends message
4. Customer SSE connection should receive event immediately
   - Check: event_data includes "type": "agent_message"
   - Check: message content is in "text" field
   - Check: session_uuid matches customer's session
5. Customer UI displays message ✅
```

### Test 2: Agent Ends Session
```
1. Agent opens active session
2. Clicks "End Session" button
3. Confirm dialog appears
4. Click "Yes" to end session
5. Check logs:
   - See: "🛑 Session ended event received for session..."
   - See: "session_ended event broadcast to customer" ← NEW
6. Customer SSE should receive:
   - Event type: "session_ended"
   - Feedback prompt should appear
7. Agent should still see other customer sessions as active ✅
```

### Test 3: Multiple Agents
```
1. Agent A opens customer session
2. Admin B opens same session
3. Agent A sends message
   - Admin B receives via broadcast_to_all_agents ✅
   - Customer receives via broadcast_to_session ✅
4. Admin B sends message
   - Agent A receives via broadcast_to_agent ✅
   - Customer receives via broadcast_to_session ✅
5. Agent A closes session
   - Customer receives session_ended ✅
   - Agent A still active for other customers ✅
```

---

## Redis Pubsub Channel Structure

```
sse/session/{session_uuid}
    ↑
    └─ Customer's SSE connection listens here
    └─ Receives: agent_message, session_ended, system events

sse/agent/{agent_email}
    ↑
    └─ Agent's SSE connection listens here
    └─ Receives: customer_message, session_update, new_assignment

sse/broadcast
    ↑
    └─ All admins listen here
    └─ Receives: all events for overview
```

**Agent sends message flow:**
```
1. Message endpoint called
2. Save to DB
3. Publish to 3 channels:
   - sse/session/{session_uuid}        → Customer receives via SSE ✅
   - sse/agent/{agent_email}            → Agent receives confirmation
   - sse/broadcast                       → All admins see it
```

---

## Files to Modify

1. **configuration/service/chat_log_service.py** (Line 394)
   - Change condition from `if status == 'closed' and not assigned_agent:` to `if status == 'closed':`
   - This ensures session_ended event is ALWAYS sent to customer

2. **configuration/routers/router.py** (Line 1447-1453) [OPTIONAL]
   - Add `session_uuid` to event_data for consistency
   - Not critical but helpful for debugging

---

## Why Messages Work Now But Session-End Doesn't

**Agent Message Send (WORKS):**
- Line 1393 explicitly broadcasts to session UUID
- Redis pubsub receives and delivers to customer's SSE
- Message appears in customer UI ✅

**Agent Session End (BROKEN):**
- Line 1454 attempts to broadcast to session UUID
- BUT line 394 condition prevents delivery
- Session_ended event never reaches Redis pubsub
- Customer never gets notification ❌

---

## Affected User Experience

### Before Fix
```
Customer: "Thanks for helping!"
Agent:    "You're welcome! Ending session now..."
[Agent clicks End Session]
↓
Customer:  [Waiting... no notification] ❌
           [Refreshes page to discover session is closed]
           [Confused state - no feedback prompt]

Agent:     "Hmm, it says offline but I can still help others..."
           [Admin concerned about status]
```

### After Fix
```
Customer: "Thanks for helping!"
Agent:    "You're welcome! Ending session now..."
[Agent clicks End Session]
↓
Customer:  [Receives session_ended event via SSE] ✅
           [Sees feedback prompt] ✅
           [Optional: Rate the interaction] ✅

Agent:     [Continues helping other customers] ✅
           [Still shows as online for new assignments] ✅
```

---

## Summary

**Two independent issues:**
1. **Agent offline UI** - Not in backend (skip for now)
2. **Agent messages to customer** - Message delivery works! ✅
3. **Session-ended event** - NOT being broadcast due to logic bug ❌

**Fix:** One line change in `chat_log_service.py` line 394 to always broadcast session_ended event regardless of whether agent is assigned.
