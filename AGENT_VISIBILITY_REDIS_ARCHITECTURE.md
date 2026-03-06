# Agent Message Visibility - Redis Architecture

## Redis Database Layout

The system uses a single Redis instance with multiple databases for different purposes:

- **Database 0**: File upload Celery tasks (`FILE_REDIS_URL`)
- **Database 1**: Website crawl Celery tasks (`WEB_REDIS_URL`)
- **Database 2**: Docling document processing queue (`DOCLING_SERVE_ENG_RQ_REDIS_URL`)
- **Database 3**: Pub/Sub + Caching (`PUBSUB_REDIS_URL`) ← **Used for agent messages**

## Database 3 Usage

Database 3 is used for both:

1. **Redis Pub/Sub** (SSE events)
   - Channel: `agent:events:{email}` - Agent-specific messages
   - Channel: `agent:events:broadcast` - Broadcast to all admins
   - Channel: `session:events:{session_uuid}` - Customer messages

2. **Caching** (via `get_pubsub_redis()`)
   - Key: `session:assigned_agent:{session_uuid}` - Agent assignment cache
   - Key: `session:uuid_to_id:{session_uuid}` - Session UUID to numeric ID mapping
   - TTL: 1 hour (3600 seconds)

## Message Flow

### When Customer Sends "agent" Message:

1. **Keyword Detection** (streaming_service.py)
   - Detects "agent" keyword before AI invocation
   
2. **Agent Assignment** (configuration service)
   - Assigns agent via HTTP call to configuration service
   - Configuration service updates `session_assignments` table in PostgreSQL
   
3. **Cache Update** (streaming_service.py)
   - Immediately caches assignment in Redis DB 3:
   ```python
   cache_key = f"session:assigned_agent:{session_uuid}"
   await redis_client.set(cache_key, assigned_agent, ex=3600)
   ```

4. **Message Broadcast** (streaming_service.py)
   - Loads all messages from PostgreSQL
   - Broadcasts `session_update` event to agent's channel in Redis DB 3:
   ```python
   channel = f"agent:events:{assigned_agent}"
   await redis_client.publish(channel, json.dumps(session_event))
   ```

5. **Subsequent Messages** (session_manager.py)
   - Checks cache first for assigned agent
   - If found, broadcasts to agent's specific channel
   - If not found, queries PostgreSQL and caches result

## Channel Subscription

### Admin Users (role='admin'):
```python
# Subscribe to TWO channels:
await pubsub.subscribe(f"agent:events:{email}")  # Personal channel
await pubsub.subscribe("agent:events:broadcast")  # Broadcast channel
```

### Human Agents (role='human_agent'):
```python
# Subscribe to ONE channel:
await pubsub.subscribe(f"agent:events:{email}")  # Personal channel only
```

## Why 0 Subscribers Issue Occurred

### Root Cause:
Session data didn't include `role` field, so all users defaulted to `role='human_agent'` and didn't subscribe to the broadcast channel.

### Fix:
1. Fetch user role from PostgreSQL when creating session
2. Store `role` and `roles` in session data (Redis session store)
3. Pass role to `AgentEventSubscriber` which subscribes to appropriate channels

### Important:
**Existing sessions must be recreated** - users need to log out and log back in to get a new session with role information.

## Verification

To verify the fix is working:

1. Check logs for session creation:
   ```
   ✅ Session created for user {email} (role=admin) from IP {ip}
   ```

2. Check logs for channel subscription:
   ```
   🔌 Admin {email} subscribed to channel: agent:events:broadcast
   ```

3. Check logs for message broadcast:
   ```
   📤 Published event to {email}: agent_message (1 subscribers)
   ```

If you see `(0 subscribers)`, it means:
- The agent is not connected to SSE, OR
- The agent's session doesn't have the role field (needs to re-login)

## Cache vs Pub/Sub - Same Database

Both caching and Pub/Sub use **Database 3**, so there's no cross-database issue:

```python
# Both use the same Redis client
redis_client = await get_pubsub_redis()  # Connects to DB 3

# Caching
await redis_client.set(cache_key, value, ex=3600)

# Pub/Sub
await redis_client.publish(channel, message)
```

This ensures:
- Cache writes are immediately visible to Pub/Sub operations
- No synchronization issues between databases
- Single connection pool for efficiency
