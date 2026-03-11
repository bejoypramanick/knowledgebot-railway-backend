# Request Mapping Capture - Router Endpoint Logging

**Date:** March 11, 2026  
**Commit:** 75cac15  
**Status:** ✅ IMPLEMENTED

---

## Overview

Now capturing the router request mapping (HTTP method + endpoint path) in all logs for better request traceability.

---

## What Changed

### Before

```
2026-03-11 11:48:04,853 [INFO] [configuration] [4ff6dc864148adc5fb47859adfbf0b96] [89cb104573cf0439] [globistaan@gmail.com] [] [otel_logger.py:228]
                                                                                                                    ↑
                                                                                                        Request Mapping (empty)
```

### After

```
2026-03-11 11:48:04,853 [INFO] [configuration] [4ff6dc864148adc5fb47859adfbf0b96] [89cb104573cf0439] [globistaan@gmail.com] [POST /api/v1/gateway/configuration/subscribe] [otel_logger.py:228]
                                                                                                                    ↑
                                                                                                        Request Mapping (now showing!)
```

---

## Implementation

### Updated FastAPI Middleware

**File:** `shared/telemetry.py`

**Change:** Generate request mapping from HTTP method + route path instead of reading from header

**Before:**
```python
# Extract user email and request mapping from headers
user_email = request.headers.get('X-User-Email', '')
request_mapping = request.headers.get('X-Request-Mapping', '')
```

**After:**
```python
# Extract user email from headers
user_email = request.headers.get('X-User-Email', '')

# Generate request mapping from method + route path (e.g., "POST /api/v1/gateway/auth/session")
request_mapping = f"{request.method} {route_path}"
```

### How It Works

1. **Extract route path** - Get the matched route pattern from the request
2. **Get HTTP method** - Extract from request.method (GET, POST, PUT, DELETE, etc.)
3. **Combine** - Create request mapping as `"{METHOD} {PATH}"` (e.g., `"POST /api/v1/gateway/configuration/subscribe"`)
4. **Set context variable** - Store in `request_mapping_ctx_var` for all logs in that request
5. **Display in logs** - Shows in the `[RequestMapping]` field

---

## Log Format

```
[Timestamp] [Level] [Service] [TraceID] [SpanID] [Email] [RequestMapping] [File:Line] - Message
```

**Example:**
```
2026-03-11 11:48:04,853 [INFO] [configuration] [4ff6dc864148adc5fb47859adfbf0b96] [89cb104573cf0439] [globistaan@gmail.com] [POST /api/v1/gateway/configuration/subscribe] [otel_logger.py:228] - 🔌 Admin globistaan@gmail.com subscribed to broadcast channel: agent:events:broadcast
```

---

## Benefits

### Request Traceability
- ✅ See which endpoint is being called
- ✅ See HTTP method (GET, POST, PUT, DELETE, etc.)
- ✅ Correlate logs with specific API calls

### Debugging
- ✅ Quickly identify which endpoint caused an error
- ✅ Track request flow through multiple services
- ✅ Monitor API usage patterns

### Monitoring
- ✅ Track which endpoints are being called
- ✅ Monitor endpoint performance
- ✅ Identify bottlenecks

---

## Examples

### Configuration Service Subscribe
```
[POST /api/v1/gateway/configuration/subscribe] - 🔌 Admin globistaan@gmail.com subscribed to broadcast channel
```

### Authentication Session
```
[POST /api/v1/gateway/auth/session] - ✅ Session created for user
```

### Get Chatbot Config
```
[GET /api/v1/gateway/configuration/chatAgentConfig] - 📊 Fetching chatbot config with sequential requests
```

### Update Profile
```
[PUT /api/v1/gateway/configuration/users/profile] - 💾 Updating user profile
```

---

## Scope

### Applies To
- ✅ All FastAPI services (API Gateway, Configuration, etc.)
- ✅ All HTTP requests
- ✅ All log levels (INFO, ERROR, WARNING, DEBUG)

### Does NOT Apply To
- ❌ Celery tasks (no HTTP request)
- ❌ Background jobs (no HTTP request)
- ❌ Internal service-to-service calls (unless they go through FastAPI)

---

## Verification

After deployment, check logs:

```bash
# Should show request mapping in logs
railway logs --service api-gateway | grep "POST /api/v1/gateway"

# Should show format like:
# [POST /api/v1/gateway/configuration/subscribe] - 🔌 Admin subscribed
```

---

## Deployment

- ✅ Commit: 75cac15
- ✅ Pushed to origin/main
- ✅ Railway will auto-deploy

---

## Next Steps

1. Monitor logs after deployment
2. Verify request mapping is showing for all endpoints
3. Use request mapping for debugging and monitoring

---

**Generated:** March 11, 2026  
**Status:** ✅ Implemented and Deployed  
**Commit:** 75cac15
