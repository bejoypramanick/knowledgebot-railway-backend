# OpenTelemetry Tracing Guide

## Overview
Complete request tracing across all layers (Router → Service → DAO) using OpenTelemetry spans.

---

## Quick Start

### 1. Import the Decorators

```python
from shared.tracing_decorator import trace_router, trace_service, trace_dao, trace_class
```

### 2. Decorate Your Functions

#### Router/Endpoint Layer
```python
from shared.tracing_decorator import trace_router

@router.post("/api/v1/users")
@trace_router(span_name="POST /api/v1/users")
async def create_user(user_data: UserCreate):
    # Your endpoint logic
    return await user_service.create_user(user_data)
```

#### Service Layer
```python
from shared.tracing_decorator import trace_service

class UserService:
    @trace_service(span_name="service.UserService.create_user")
    async def create_user(self, user_data: dict):
        # Your service logic
        return await self.dao.insert_user(user_data)
```

#### DAO Layer
```python
from shared.tracing_decorator import trace_dao

class UserDAO:
    @trace_dao(span_name="dao.UserDAO.insert_user", capture_result=True)
    async def insert_user(self, user_data: dict):
        # Your database logic
        query = "INSERT INTO users ..."
        return await self.execute(query, user_data)
```

---

## Automatic Class Tracing

Trace all methods in a class automatically:

```python
from shared.tracing_decorator import trace_class

@trace_class(layer="service")
class UserService:
    def create_user(self, user_data):
        # Automatically traced
        pass
    
    def get_user(self, user_id):
        # Automatically traced
        pass
    
    def update_user(self, user_id, data):
        # Automatically traced
        pass
```

---

## Complete Example: Full Request Flow

### Router (auth_router.py)
```python
from fastapi import APIRouter, Depends
from shared.tracing_decorator import trace_router

router = APIRouter()

@router.post("/auth/session")
@trace_router(span_name="POST /auth/session")
async def create_session_endpoint(
    request: CreateSessionRequest,
    session_service: SessionService = Depends(get_session_service_dep),
    profile_service: ProfileService = Depends(get_profile_service_dep)
):
    # Verify Firebase token
    user_data = verify_firebase_token(request.idToken)
    
    # Fetch profile (traced automatically)
    profile = await profile_service.fetch_user_profile(user_data)
    
    # Create session (traced automatically)
    session_id = session_service.create_session(user_data, ip_address, user_agent)
    
    return {"success": True, "session_id": session_id}
```

### Service (session_service.py)
```python
from shared.tracing_decorator import trace_service

class SessionService:
    @trace_service(span_name="service.SessionService.create_session")
    def create_session(self, user_data, ip_address, user_agent):
        # Generate session ID
        session_id = secrets.token_urlsafe(32)
        
        # Store in Redis (traced if DAO is decorated)
        self.store.create(session_id, session_data, ttl)
        
        return session_id
    
    @trace_service(span_name="service.SessionService.get_session")
    def get_session(self, session_id, ip_address, user_agent):
        # Get from store
        session_data = self.store.get(session_id)
        
        # Validate security
        if not self._validate_session_security(session_data, ip_address, user_agent):
            return None
        
        return session_data
```

### DAO (chat_log_dao.py)
```python
from shared.tracing_decorator import trace_dao

class ChatLogDAO:
    @trace_dao(span_name="dao.ChatLogDAO.get_session", capture_result=True)
    async def get_session(self, session_id: int):
        query = """
            SELECT * FROM chat_sessions 
            WHERE id = $1
        """
        result = await self.execute_query(query, session_id)
        return result
    
    @trace_dao(span_name="dao.ChatLogDAO.create_session")
    async def create_session(self, session_data: dict):
        query = """
            INSERT INTO chat_sessions (user_id, status, created_at)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        result = await self.execute_query(
            query,
            session_data['user_id'],
            session_data['status'],
            session_data['created_at']
        )
        return result['id']
```

---

## What Gets Traced

### Span Attributes

Each span automatically includes:

1. **Function Metadata**
   - `code.function`: Function name
   - `code.namespace`: Module path
   - `code.layer`: Layer type (router, service, dao)

2. **Arguments** (if `capture_args=True`)
   - `arg.{param_name}`: Primitive argument values
   - `arg.{param_name}.type`: Type for complex objects

3. **Result** (if `capture_result=True`)
   - `result.type`: Return value type
   - `result.value`: Return value (for primitives)

4. **Errors** (automatic)
   - `error.type`: Exception class name
   - `error.message`: Exception message
   - Full exception stack trace

5. **Status** (automatic)
   - `OK` for successful execution
   - `ERROR` for exceptions

---

## Log Output Example

### Before Tracing
```
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [def456] - 📨 POST /api/v1/auth/session
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [def456] - ✅ Session created
```

### After Tracing
```
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [def456] - 📨 POST /api/v1/auth/session
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [def456] - 📍 Route: POST /api/v1/auth/session
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [span789] - service.ProfileService.fetch_user_profile
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [span890] - dao.UserDAO.get_user_by_email
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [span901] - service.SessionService.create_session
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [span902] - dao.SessionDAO.insert_session
2024-01-15 10:30:45 [INFO] [api-gateway] [abc123] [def456] - ✅ Session created
```

**Notice:**
- Same TraceID (`abc123`) across all operations
- Different SpanIDs for each layer
- Clear hierarchy: Router → Service → DAO

---

## Searching Logs

### By Route
```bash
grep "POST /api/v1/auth/session" logs.txt
```

### By TraceID (entire request flow)
```bash
grep "abc123" logs.txt
```

### By Layer
```bash
grep "service.SessionService" logs.txt
grep "dao.ChatLogDAO" logs.txt
```

### By Function
```bash
grep "create_session" logs.txt
```

---

## Best Practices

### 1. Use Descriptive Span Names
```python
# Good
@trace_service(span_name="service.UserService.create_user")

# Bad
@trace_service(span_name="create")
```

### 2. Trace at All Layers
```
Router (endpoint) → Service (business logic) → DAO (database)
     ↓                      ↓                      ↓
  Traced               Traced                  Traced
```

### 3. Capture Arguments Selectively
```python
# Capture args for debugging
@trace_service(capture_args=True)
async def process_payment(amount, currency):
    ...

# Don't capture sensitive data
@trace_service(capture_args=False)
async def process_password(password):
    ...
```

### 4. Capture Results for DAOs
```python
# Useful for database queries
@trace_dao(capture_result=True)
async def get_user(self, user_id):
    return await self.execute_query(...)
```

### 5. Use Class Decorator for Consistency
```python
# Trace all methods automatically
@trace_class(layer="service")
class UserService:
    # All methods traced
    pass
```

---

## Migration Guide

### Step 1: Add Imports
```python
from shared.tracing_decorator import trace_router, trace_service, trace_dao
```

### Step 2: Decorate Routers
```python
@router.post("/endpoint")
@trace_router(span_name="POST /endpoint")
async def my_endpoint(...):
    ...
```

### Step 3: Decorate Services
```python
@trace_service(span_name="service.MyService.method")
async def my_method(...):
    ...
```

### Step 4: Decorate DAOs
```python
@trace_dao(span_name="dao.MyDAO.query")
async def my_query(...):
    ...
```

### Step 5: Test
```bash
# Make a request
curl -X POST http://localhost:8080/endpoint

# Check logs for trace
grep "POST /endpoint" logs.txt
```

---

## Performance Impact

### Overhead
- **Minimal**: ~0.1-0.5ms per span
- **Negligible** for most applications
- **Worth it** for debugging and monitoring

### Optimization
- Disable argument capture in production if needed
- Use `capture_result=False` for large objects
- Spans are batched and exported asynchronously

---

## Troubleshooting

### Spans Not Appearing
1. Check OpenTelemetry is initialized: `setup_telemetry(service_name)`
2. Check span exporter is enabled: `OTEL_SPAN_EXPORTER_ENABLED=true`
3. Check decorator is applied correctly

### TraceID is "0"
- No active span context
- Ensure FastAPI is instrumented: `instrument_fastapi(app, service_name)`

### Arguments Not Captured
- Check `capture_args=True` in decorator
- Ensure arguments are primitive types (str, int, float, bool)

---

## Advanced Usage

### Custom Attributes
```python
from opentelemetry import trace

@trace_service()
async def my_method(user_id):
    span = trace.get_current_span()
    span.set_attribute("custom.user_id", user_id)
    span.set_attribute("custom.operation", "create")
    ...
```

### Manual Spans
```python
from opentelemetry import trace

async def my_function():
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("custom.operation") as span:
        span.set_attribute("key", "value")
        # Your code here
```

### Nested Spans
```python
@trace_service()
async def outer_function():
    # Outer span
    
    @trace_service()
    async def inner_function():
        # Inner span (child of outer)
        pass
    
    await inner_function()
```

---

## Summary

1. **Import decorators** from `shared.tracing_decorator`
2. **Decorate functions** at router, service, and DAO layers
3. **Use descriptive span names** for easy searching
4. **Search logs by TraceID** to see entire request flow
5. **Minimal overhead**, maximum visibility

Complete request tracing is now automatic across all layers!
