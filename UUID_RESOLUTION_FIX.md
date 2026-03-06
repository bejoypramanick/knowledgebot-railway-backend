# UUID to Numeric ID Resolution Fix

## Problem

The mark-read and mark-unread endpoints were failing with error:
```
400: Invalid session: UUID could not be resolved. Session may not exist or may have expired.
```

Error logs showed:
```
❌ Failed to resolve session UUID session_1772838103584_pdzbgdgei0 for configuration/admin/chat-sessions/mark-read
```

## Root Cause

The API gateway has two different paths for session UUID resolution:

### Path 1: Customer Endpoints (Cookie-based)
- Customer endpoints: `/api/v1/gateway/configuration/customer/*` or `/api/v1/gateway/chatbot/sessions/*`
- Session UUID comes from httpOnly cookie (`chatbot_session_id`)
- Middleware (`auth_middleware.py`) extracts UUID from cookie and resolves it to numeric ID
- Sets `request.state.session_numeric_id` for downstream use

### Path 2: Admin Endpoints (Body-based)
- Admin endpoints: `/api/v1/gateway/configuration/admin/*`
- Session UUID comes from request body (e.g., `{"session_id": "session_xxx"}`)
- Middleware does NOT resolve UUIDs for admin endpoints (only for customer endpoints)
- Generic proxy handler needs to resolve the UUID

**The bug**: The generic proxy handler was checking if `request.state.session_numeric_id` existed, but for admin endpoints, the middleware never set it. When it didn't exist, the handler rejected the request instead of resolving the UUID itself.

## Solution

Updated the generic proxy handler in `api_gateway/routers/router.py` to handle both scenarios:

```python
if isinstance(client_session_id, str) and client_session_id.startswith("session_"):
    # Two scenarios:
    # 1. Customer endpoints: UUID from cookie, middleware already resolved it
    # 2. Admin endpoints: UUID from request body, need to resolve it here
    numeric_id = None
    
    # First check if middleware already resolved it (customer endpoints)
    if hasattr(request.state, "session_numeric_id") and request.state.session_numeric_id:
        numeric_id = request.state.session_numeric_id
        logger.info(f"🔄 Using middleware-resolved numeric ID")
    else:
        # Middleware didn't resolve it (admin endpoints) - do it here
        async with get_db_session() as db_session:
            query = text("SELECT id FROM chat_sessions WHERE session_id = :session_uuid")
            result = await db_session.execute(query, {"session_uuid": client_session_id})
            row = result.mappings().first()
            
            if row:
                numeric_id = row['id']
                logger.info(f"✅ Resolved UUID to numeric ID: {client_session_id} → {numeric_id}")
    
    if numeric_id:
        body_data["session_id"] = numeric_id
    else:
        raise HTTPException(status_code=400, detail="Invalid session: UUID could not be resolved")
```

## Why This Design?

### Customer Endpoints
- Customers don't have authentication tokens
- Session UUID is stored in httpOnly cookie for security
- Middleware resolves UUID once per request (efficient)
- All customer endpoints can use `request.state.session_numeric_id`

### Admin Endpoints
- Admins have Firebase authentication
- Admins can operate on ANY customer session (not just their own)
- Session UUID comes from request body (which session to operate on)
- Middleware doesn't resolve it (would need to parse body, which is inefficient)
- Proxy handler resolves it only when needed

## Affected Endpoints

This fix applies to all admin endpoints that accept a `session_id` in the request body:
- `/admin/chat-sessions/mark-read`
- `/admin/chat-sessions/mark-unread`
- `/admin/chat-sessions/messages` (already had custom proxy with UUID resolution)
- Any future admin endpoints that operate on customer sessions

## Files Changed

1. `api_gateway/routers/router.py` - Added UUID resolution in generic proxy handler

## Testing

After this fix:
- Admins can mark customer sessions as read/unread
- Customer endpoints continue to work (middleware path)
- Admin endpoints work (proxy handler path)
- Both customer UUIDs (`session_*`) and numeric IDs are supported
