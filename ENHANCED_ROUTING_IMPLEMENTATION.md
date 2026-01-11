# Enhanced Routing Logic Implementation

## Overview
This document describes the enhanced routing logic for human agent requests, including admin fallback routing and agent-to-agent/admin chat transfers.

## Features Implemented

### 1. Admin Fallback Routing
When no human agents are online, chat requests are automatically routed to logged-in admins based on their current chat load.

**Backend Changes:**
- Modified `assign_chat_with_load_balancing()` in `chat_log.py`
- Falls back to admins when no agents are online
- Uses same load balancing algorithm (fewest active chats)
- Updated `get_agent_online_status()` to work for both agents and admins

**Key Logic:**
```python
# Check for online human agents first
if agents:
    for agent in agents:
        if await get_agent_online_status(agent_email, conn):
            # Assign to agent with load balancing
            
# If no agents online, check for admins
if not online_agents:
    admins = await conn.fetch("SELECT email FROM admins WHERE status = 'confirmed'")
    for admin in admins:
        if await get_agent_online_status(admin_email, conn):
            # Assign to admin with load balancing
```

### 2. Chat Transfer Functionality
Agents and admins can transfer active chats to other online agents or admins.

**Backend Endpoint:**
- `POST /api/v1/admin/chat-sessions/{session_id}/transfer`
- Query parameter: `target_agent_email`
- Requires authentication (confirmed agent or admin)
- Validates target user is confirmed agent or admin
- Updates session assignment
- Broadcasts transfer notification via WebSocket
- Adds system message to chat history

**Frontend Implementation:**
- Transfer button in chat header (agents/admins only, active sessions only)
- Dialog showing online users with:
  - Email address
  - Role (agent/admin)
  - Current active session count
- Real-time updates every 30 seconds
- Error handling and user feedback

### 3. Online Agents Endpoint
New endpoint to retrieve all online agents and admins with their current load.

**Endpoint:**
- `GET /api/v1/admin/agents/online`
- Returns: Array of `{ email, role, is_online, active_sessions }`
- Used for transfer UI and load balancing decisions
- Accessible to confirmed agents and admins only

## Customer Transparency

The implementation ensures customers cannot distinguish between agents and admins:

1. **Generic Transfer Messages:**
   - "Chat has been transferred to another support agent"
   - No email addresses or role information exposed

2. **Unified Agent Experience:**
   - Admins appear as regular support agents to customers
   - Same message format and interaction patterns

3. **System Messages:**
   - Use neutral language
   - Don't reveal internal routing decisions

## API Reference

### Transfer Chat Session
```typescript
POST /api/v1/admin/chat-sessions/{session_id}/transfer?target_agent_email={email}

Headers:
  Authorization: Bearer {firebase_token}

Response:
{
  "success": true,
  "message": "Chat transferred successfully",
  "session_id": "session_123",
  "transferred_to": "agent@example.com"
}
```

### Get Online Agents
```typescript
GET /api/v1/admin/agents/online

Headers:
  Authorization: Bearer {firebase_token}

Response:
{
  "success": true,
  "agents": [
    {
      "email": "agent1@example.com",
      "role": "agent",
      "is_online": true,
      "active_sessions": 3
    },
    {
      "email": "admin@example.com",
      "role": "admin",
      "is_online": true,
      "active_sessions": 1
    }
  ]
}
```

## Frontend Components

### ChatLog.tsx
**New State:**
- `onlineUsers`: List of online agents/admins
- `showTransferDialog`: Transfer dialog visibility
- `transferTargetEmail`: Selected transfer target
- `isTransferring`: Transfer in progress flag

**New Functions:**
- `loadOnlineUsers()`: Fetches online users every 30s
- `handleTransferChat(targetEmail)`: Executes transfer with error handling

**UI Components:**
- Transfer button (ArrowRightLeft icon)
- Transfer dialog with user selection
- Active session count badges
- Loading states and error messages

### configuration-api.ts
**New Method:**
```typescript
async transferChatSession(
  sessionId: string, 
  targetAgentEmail: string
): Promise<{
  success: boolean;
  message: string;
  session_id: string;
  transferred_to: string;
}>
```

## Testing Scenarios

### Scenario 1: Admin Fallback
1. No human agents online
2. Customer requests human agent
3. System assigns to online admin with fewest chats
4. Customer sees "Connected to support agent"

### Scenario 2: Agent Transfer
1. Agent has active chat with customer
2. Agent clicks Transfer button
3. Selects online agent/admin from list
4. Customer sees "Chat has been transferred to another support agent"
5. New agent receives chat in their queue

### Scenario 3: Load Balancing
1. Multiple admins online
2. No agents online
3. New chat request
4. System assigns to admin with fewest active chats
5. Load is distributed evenly

## Security Considerations

1. **Authentication Required:**
   - All endpoints require valid Firebase token
   - Only confirmed agents/admins can access

2. **Authorization Checks:**
   - Transfer endpoint verifies both source and target users
   - Only confirmed agents/admins can transfer
   - Only confirmed agents/admins can receive transfers

3. **Data Privacy:**
   - Customer never sees agent/admin email addresses
   - Transfer messages are generic
   - Role information hidden from customer view

## Future Enhancements

Potential improvements:
1. Transfer with notes/context
2. Transfer history tracking
3. Bulk transfer capabilities
4. Transfer notifications to target agent
5. Transfer acceptance/rejection flow
6. Analytics on transfer patterns

## Files Modified

### Backend
- `services/configuration_service/chat_log.py`
  - Added `/agents/online` endpoint
  - Added `/chat-sessions/{session_id}/transfer` endpoint
  - Modified `assign_chat_with_load_balancing()`
  - Updated `get_agent_online_status()`

### Frontend
- `src/lib/configuration-api.ts`
  - Added `transferChatSession()` method
  - Updated `getOnlineAgents()` return type
  - Added `status` field to ChatMessage interface

- `src/pages/ChatLog.tsx`
  - Added transfer UI components
  - Implemented transfer logic
  - Added online users polling

## Deployment Notes

1. **Database:** No schema changes required
2. **Environment:** No new environment variables needed
3. **Dependencies:** No new dependencies added
4. **Backward Compatibility:** Fully backward compatible

## Support

For questions or issues, refer to:
- Main documentation: `INTEGRATION_GUIDE.md`
- API documentation: `API_REFERENCE.md`
- Configuration guide: `CONFIGURATION.md`
