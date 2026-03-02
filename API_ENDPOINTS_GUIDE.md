# API Endpoints Guide - Knowledge Bot

## Overview of All Endpoints Observed

### 1. **Firebase Authentication**
```
GET https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=AIzaSyAv8ROp1WYCFjKhqaEm40ivbCR8c4XUtd4
```
- **Purpose**: Firebase API call to verify user authentication
- **Used By**: Frontend when initializing user session
- **Status**: ✅ Expected

---

## Configuration Endpoints

### 2. **Widget Configuration**
```
GET /api/v1/gateway/configuration/widgetConfig
```
- **Purpose**: Fetch chatbot widget settings (colors, size, position, etc.)
- **Returns**: Widget styling and behavior configuration
- **Status**: ✅ Expected

### 3. **Security Settings**
```
GET /api/v1/gateway/configuration/data/security-settings
```
- **Purpose**: Fetch security configuration (authentication requirements, CORS, etc.)
- **Returns**: Security policies and settings
- **Status**: ✅ Expected
- **Note**: Called TWICE - possibly debounced

### 4. **User Unique ID**
```
POST /api/v1/gateway/configuration/users/unique-id
GET /api/v1/gateway/configuration/users/unique-id
```
- **Purpose**: Generate or retrieve unique user ID for session tracking
- **Returns**: Unique identifier for anonymous user
- **Status**: ✅ Expected

### 5. **LLM Providers**
```
GET /api/v1/gateway/configuration/data/llm-providers
```
- **Purpose**: Fetch available LLM providers (OpenAI, Gemini, Claude, etc.)
- **Returns**: List of configured AI providers
- **Status**: ✅ Expected
- **Note**: Called TWICE - possibly debounced

### 6. **Active Persona**
```
GET /api/v1/gateway/configuration/data/active-persona
```
- **Purpose**: Fetch chatbot persona (name, tone, instructions, etc.)
- **Returns**: Active chatbot personality and behavior
- **Status**: ✅ Expected
- **Note**: Called TWICE - possibly debounced

### 7. **Human Agents List**
```
GET /api/v1/gateway/configuration/data/human-agents
```
- **Purpose**: Fetch list of available human agents (for escalation)
- **Returns**: List of agents with contact info
- **Status**: ✅ Expected
- **Note**: Called TWICE - possibly debounced

### 8. **Admin Emails**
```
GET /api/v1/gateway/configuration/data/admin-emails
```
- **Purpose**: Fetch list of admin email addresses
- **Returns**: Admin emails for notifications/escalation
- **Status**: ✅ Expected
- **Note**: Called TWICE - possibly debounced

---

## Admin Chat Log Endpoints

### 9. **Get Chat Sessions** (Main List)
```
GET /api/v1/gateway/configuration/admin/chat-sessions?role=admin&status=all&page=1&limit=50
```
- **Purpose**: Fetch list of chat sessions for admin dashboard
- **Parameters**:
  - `role`: admin, human_agent
  - `status`: active, archived, all
  - `page`: pagination page number
  - `limit`: results per page
- **Returns**:
  - List of sessions with metadata
  - **Messages ARE included** in response (by default)
  - Feedback counts for each session
- **Status**: ✅ Expected - **CRITICAL** for chat log display

### 10. **Mark Session as Read**
```
POST /api/v1/gateway/configuration/admin/chat-sessions/269/mark-read
```
- **Purpose**: Mark all messages in a session as read
- **Returns**: Success confirmation
- **Status**: ⚠️ RETURNS 403 FORBIDDEN
- **Issue**: User not recognized as admin/human_agent (we're debugging this)

### 11. **Get Feedback Counts**
```
POST /api/v1/gateway/configuration/feedback/counts
Body: { "session_ids": ["269", ...] }
```
- **Purpose**: Fetch feedback counts (thumbs up/down) for sessions
- **Returns**: Positive/negative feedback counts per session
- **Status**: ⚠️ RETURNS 500 ERROR
- **Issue**: Missing `feedback_type` column in database (migration not applied)

---

## Real-Time Event Streaming

### 12. **Admin Events Stream (SSE)**
```
GET /api/v1/gateway/configuration/admin/events?token=eyJhbGci...
```
- **Purpose**: Server-Sent Events for real-time agent updates
- **Type**: Long-lived streaming connection (HTTP Keep-Alive)
- **Sends**:
  - New messages in real-time
  - Typing indicators
  - Session status changes
  - Heartbeat pings (every 30 seconds)
- **Returns**: Status "cancelled" when connection closes
- **Status**: ⚠️ Connection cancelled
- **Issue**: SSE connection established but then closed (normal if dashboard closed)

---

## Online Agents

### 13. **Get Online Agents** (Repeated Multiple Times)
```
GET /api/v1/gateway/configuration/admin/agents/online
```
- **Purpose**: Fetch list of agents currently online
- **Returns**: Currently returns empty list (not yet implemented)
- **Status**: ⚠️ BEING CALLED TOO FREQUENTLY
- **Issue**: Called at least 5+ times in rapid succession
  - Suggests polling or component re-rendering issue
  - Should use debouncing or increase polling interval
  - Could be a performance problem

---

## Problem 1: Repeated API Calls (Performance Issue)

### What's Happening
You're seeing many **duplicate calls** to the same endpoints:
- `security-settings` - called 2x
- `llm-providers` - called 2x
- `active-persona` - called 2x
- `human-agents` - called 2x
- `admin-emails` - called 2x
- `admin/agents/online` - called **5+ times** ⚠️

### Root Causes
1. **Component re-rendering** - Components rendering multiple times trigger API calls
2. **Missing dependencies** in useEffect hooks
3. **No proper debouncing/caching** - Same data fetched multiple times
4. **Polling loops** - Intervals without proper cleanup
5. **Parent re-renders** - Child components fetch data on every parent render

### Solution
Add to frontend configuration services:
```typescript
// Use React Query or SWR for automatic caching
const { data: agents } = useQuery('onlineAgents', getOnlineAgents, {
  staleTime: 30000, // Cache for 30 seconds
  cacheTime: 60000,
});

// OR use fetch once and store in context
const [agents, setAgents] = useState(null);
useEffect(() => {
  fetchOnlineAgents().then(setAgents);
}, []); // Empty dependency array - only fetch once
```

---

## Problem 2: Messages Not Populating on Chat Log

### Architecture
The chat log messages should come from **two sources**:

1. **Initial Load**: `/admin/chat-sessions` endpoint returns sessions **with messages included**
2. **Real-time Updates**: `/admin/events` SSE stream sends new messages as they arrive

### Why Messages Might Not Be Showing

#### ❌ **Issue A: `/admin/chat-sessions` not returning messages**
Check if the endpoint is returning messages:
```bash
curl -X GET "https://api-gateway-common.up.railway.app/api/v1/gateway/configuration/admin/chat-sessions?page=1&limit=10" \
  -H "X-User-Email: globistaan@gmail.com" \
  -H "X-User-UID: your-uid"
```

Look for `"messages": [...]` in response. If empty or missing:
- Messages not being fetched from database
- Database query issue
- Filter is removing messages

#### ❌ **Issue B: SSE connection is cancelled**
If SSE connection is not staying open:
- Real-time updates won't be received
- New messages won't appear until page refresh
- Status shows "cancelled" because connection closed

**Check**: Is the `/admin/events` connection showing as "pending" or "cancelled"?

#### ❌ **Issue C: Messages exist but not displayed in UI**
If messages are in the response but not showing:
- UI state not being updated correctly
- Message list component has rendering issue
- Selected session not updated when new messages arrive

**Check**: Open browser DevTools Console and log:
```javascript
// In browser console
console.log(selectedSession?.messages);
```

#### ❌ **Issue D: 403 on mark-read blocks entire flow**
If mark-read endpoint returns 403, the frontend might:
- Stop loading messages
- Hide the chat log
- Think user is unauthorized

**Status**: This is known - we added debugging for it

---

## Diagnostic Checklist

### Step 1: Verify Initial Data Load
```bash
# Check if sessions endpoint returns messages
curl -X GET "...admin/chat-sessions?page=1&limit=1" \
  -H "X-User-Email: globistaan@gmail.com" \
  -H "X-User-UID: vUZw8Zn38WZm0CG33JbHuPINIxa2"
```
✅ Should return sessions with `"messages": [{...}, ...]`
❌ If messages empty or missing → Database issue

### Step 2: Verify User Permissions
```bash
# Check if user has admin/human_agent roles
# Query database directly:
SELECT u.email, r.role_name
FROM user_role_mapping urm
JOIN users u ON urm.user_id = u.id
JOIN roles r ON urm.role_id = r.id
WHERE u.email = 'globistaan@gmail.com';
```
✅ Should return: admin, human_agent
❌ If empty → User not set up correctly

### Step 3: Verify SSE Connection
1. Open browser DevTools → Network tab
2. Filter for `/admin/events`
3. Check if connection shows as:
   - 🟢 **Pending** (200) = Connected properly
   - 🔴 **Cancelled** = Connection closed
   - ❌ **Failed** = Network error

### Step 4: Check Frontend Logs
```javascript
// Open browser console
// Look for:
// - "[SSE] Attempting to connect to: /admin/events"
// - "[SSE] Successfully connected"
// - "[SSE] Connection cancelled"
// - API error messages
```

### Step 5: Check Backend Logs
```bash
# SSH into Railway container
# Check logs for:
# - "🔍 mark_session_as_read: Checking roles for user_email:"
# - "📨 Loaded messages for X sessions"
# - "🔌 Agent connected to SSE stream"
# - Any error messages
```

---

## Expected API Flow for Chat Log

1. **User opens admin dashboard**
   - Calls `/data/security-settings`, `/data/llm-providers`, etc. (config)
   - Calls `/admin/chat-sessions` (gets sessions + messages)
   - Opens `/admin/events` SSE connection

2. **User selects a chat session**
   - Shows messages from `/admin/chat-sessions` response
   - Calls `/admin/chat-sessions/{id}/mark-read` (should fail currently - 403)
   - SSE stream sends new messages in real-time

3. **New customer message arrives**
   - Backend broadcasts via SSE to `/admin/events`
   - Frontend receives event and updates message list
   - New message appears in chat log

4. **User sends agent message** (if implemented)
   - POST to `/admin/chat-sessions/{id}/messages`
   - Message appears in UI
   - SSE broadcasts to other agents

---

## Summary: Why Messages Not Showing

| Scenario | Indicator | Fix |
|----------|-----------|-----|
| `/admin/chat-sessions` not loading messages | Response has empty messages array | Check database messages table |
| User not authorized | 403 error on mark-read | Fix user role mapping in database |
| SSE connection not staying open | Status shows "cancelled" immediately | Check auth headers, network connectivity |
| Frontend not updating | Messages in API response but not in UI | Check React state updates |
| Repeated API calls killing performance | Network tab shows duplicates | Add proper React caching/deps |

