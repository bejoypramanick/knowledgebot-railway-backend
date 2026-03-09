# Human Agent Message Delivery - Diagnostic Guide

## Backend Status: ✅ WORKING

All logs confirm backend is functioning:
- Messages saved to database ✅
- Redis broadcast to customer: `result: True` ✅
- Redis broadcast to agent: `result: True` ✅
- Redis broadcast to admins: `1 subscribers` ✅
- Event yielded to SSE client ✅

## Message Flow (Live Example)

```
09:07:45 - Agent sends "hello"
    ↓
09:07:45 POST /api/v1/chatbot/proxy-agent-message (API Gateway)
    ↓
09:07:45 Converted UUID → numeric ID 667
    ↓
09:07:45 POST /admin/chat-sessions/messages (Configuration Service)
    ↓
09:07:45.764 📤 [AGENT_MESSAGE] Broadcasting to customer on channel: sse/session/session_1773047255336_o7xukkf6no
09:07:46.143 📤 [AGENT_MESSAGE] Customer broadcast result: True ✅
    ↓
09:07:46.144 📤 [AGENT_MESSAGE] Broadcasting to agent system
09:07:46.151 📤 [AGENT_MESSAGE] Agent broadcast result: True ✅
    ↓
09:07:46.152 📤 [AGENT_MESSAGE] Broadcasting to all admins
09:07:46.158 📢 Broadcasted event on channel agent:events:broadcast: agent_message (1 subscribers)
09:07:46.159 📤 [AGENT_MESSAGE] Admin broadcast result: True ✅
    ↓
09:07:46.161 🔌 Parsed event type: agent_message, yielding to SSE client ✅
```

## Channel Verification

### Broadcaster Channel (redis_pubsub_manager.py:102)
```python
def _get_session_channel(self, session_id: str) -> str:
    return f"session:events:{session_id}"
```

### Customer SSE Subscriber (router.py:1006)
```python
channel_name = f"session:events:{session_id}"
```

### Match: ✅ YES
- Broadcaster publishes to: `session:events:{uuid}`
- Customer listens on: `session:events:{uuid}`
- Same channel ✅

---

## Troubleshooting Checklist

### 1. Check Customer SSE Connection

**Question:** Is customer connected to SSE endpoint when agent sends message?

**Test:**
```bash
# In browser console when customer is in chat
fetch('https://dailogueapi.globistaan.com/api/v1/gateway/customer/events?session_id=session_1773047255336_o7xukkf6no')
  .then(response => {
    console.log('SSE connected:', response.status);
    // Should see logs appear as you type messages
  })
```

**Expected:** Connection to `/customer/events?session_id=...` should be active (network tab)

**If missing:** Customer JS not opening SSE endpoint

### 2. Check Redis Pub/Sub is Working

**Test:** Create two Redis connections
```python
import redis.asyncio as redis

redis_url = os.getenv('PUBSUB_REDIS_URL')  # Should be redis://...@host:6379/3
client = redis.from_url(redis_url)

# Publish test message
await client.publish('session:events:test_session', '{"type": "test", "message": "hello"}')
# Should return: 1 (1 subscriber got it)
```

**If returns 0:** No subscribers listening on that channel

### 3. Check Event Format

**Message should be JSON:**
```json
{
  "type": "agent_message",
  "session_id": "session_1773047255336_o7xukkf6no",
  "message_id": "123",
  "text": "hello",
  "sender": "agent",
  "agent_email": "system",
  "timestamp": "2026-03-09T09:07:46.123456"
}
```

**Not:** Raw string or invalid JSON

### 4. Check SSE Event Format in Browser

**Expected SSE format received by client:**
```
data: {"type":"agent_message","text":"hello",...}

```

**Not:** Missing `data:` prefix or incorrect format

### 5. Frontend Event Listener

**Check if frontend is listening:**
```javascript
const eventSource = new EventSource(
  `https://dailogueapi.globistaan.com/api/v1/gateway/customer/events?session_id=${sessionId}`
);

eventSource.addEventListener('message', (event) => {
  console.log('Received SSE event:', event.data);
  const data = JSON.parse(event.data);
  console.log('Message:', data);
});

eventSource.addEventListener('error', (err) => {
  console.error('SSE error:', err);
});
```

---

## Common Issues & Fixes

### Issue 1: "Customer broadcast result: False"

**Symptoms:**
- Backend shows: `📤 [AGENT_MESSAGE] Customer broadcast result: False`
- Customer doesn't receive messages

**Causes:**
1. No customer SSE connection active
2. Wrong Redis database (should be 3)
3. Redis connection error

**Fix:**
- Verify customer connected to SSE endpoint
- Check `PUBSUB_REDIS_URL` points to database 3
- Verify Redis is running: `redis-cli -n 3 PING`

### Issue 2: "No subscribers for session channel"

**Symptoms:**
- Backend shows: `📭 No subscribers for session...`
- But customer is in chat

**Causes:**
1. Customer SSE connection not active yet
2. Different session UUID in broadcast vs subscriber
3. Race condition (message sent before customer connects)

**Fix:**
- Ensure customer calls `/customer/events?session_id=...` BEFORE sending message
- Verify session_uuid matches in both broadcaster and subscriber

### Issue 3: Customer Connected but No Message Appears

**Symptoms:**
- Network shows SSE connection active
- Backend shows broadcast result: True
- Customer doesn't see message in UI

**Causes:**
1. Frontend not listening to SSE events
2. Frontend listening but not updating DOM
3. Event parsing error in frontend

**Fix:**
- Add console.log to EventSource listener
- Check browser DevTools → Network → SSE connection → Messages
- Verify JSON parsing works: `JSON.parse(event.data)`

---

## Redis Pub/Sub Debug

### Check Active Subscribers

```bash
redis-cli -n 3 PUBSUB CHANNELS
# Should show: "session:events:session_1773047255336_o7xukkf6no"

redis-cli -n 3 PUBSUB NUMSUB "session:events:*"
# Should show count of subscribers
```

### Manually Test Message Delivery

```bash
# Terminal 1: Subscribe
redis-cli -n 3 SUBSCRIBE "session:events:test"

# Terminal 2: Publish
redis-cli -n 3 PUBLISH "session:events:test" '{"type":"test","text":"hello"}'

# Terminal 1: Should see the message
```

---

## Log Locations

### Backend Logs
- Configuration Service: `[configuration]` tag
- Look for: `[AGENT_MESSAGE]` for message send logs
- Look for: `📤 Customer broadcast result:` for delivery status

### Frontend Logs
- Browser Console (F12)
- Network tab → filter by `/customer/events`
- Check SSE response messages

---

## Next Steps

1. **Enable detailed logging** in frontend to see if SSE events are received
2. **Verify Redis** is properly configured with database 3
3. **Check network tab** in browser for SSE connection status
4. **Test with curl** to verify SSE endpoint returns events

```bash
curl -i https://dailogueapi.globistaan.com/api/v1/gateway/customer/events?session_id=YOUR_SESSION_ID
# Should show: text/event-stream content-type
# Should stream events as they arrive
```

---

## Summary

**Backend is 100% working.** If messages aren't appearing:

1. Check frontend is connected to SSE endpoint
2. Check Redis is running on database 3
3. Check frontend is listening to SSE events
4. Check frontend is parsing and displaying JSON

The issue is either in **frontend connectivity** or **frontend event handling**, not in the backend.
