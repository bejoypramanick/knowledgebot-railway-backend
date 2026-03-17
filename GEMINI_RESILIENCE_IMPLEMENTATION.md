# Gemini 503 Error Resilience Implementation

## Problem
Gemini 2.5 Flash-lite was experiencing 503 errors due to high demand:
```
status_code: 503, model_name: gemini-2.5-flash-lite, 
body: {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. 
Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}
```

## Solution
Implemented three resilience patterns in `chatbot_orchestration/core/cached_google_model.py`:

### 1. Exponential Backoff (The "Polite" Way)
- Retries failed requests with exponential backoff + jitter
- Max 3 attempts: waits ~1s, ~2s, ~3s between retries
- Prevents overwhelming Google's servers during traffic spikes
- Jitter (random 0-1s) prevents thundering herd problem

**Implementation:**
```python
wait_time = (2 ** attempt) + random.uniform(0, 1)
await asyncio.sleep(wait_time)
```

### 2. Model Fallback (The "UX First" Way)
- Automatically falls back to `gemini-2.0-flash` if `gemini-2.5-flash-lite` is unavailable
- Provides seamless user experience during outages
- More stable model as backup (slightly higher cost but better availability)
- **Cache Handling**: Strips model-specific cache reference, uses inline system_instruction + tools
- **RAG Search**: Functions identically - all tools (search_knowledge_base, etc.) work the same
- **System Prompt**: Automatically included from Agent configuration
- **No Configuration Changes**: Fallback is transparent to the application

**Flow:**
```
gemini-2.5-flash-lite (503) → Retry with backoff → Still failing? 
→ Fall back to gemini-2.0-flash (with inline system prompt + tools, no cache)
```

**Cache Behavior:**
- Primary model: Uses Gemini cache (system prompt + tools cached)
- Fallback model: Uses inline mode (system prompt + tools sent with each request)
- Both modes produce identical responses - only performance/cost differs

### 3. Circuit Breaker Pattern
- Tracks failures per model over a 60-second window
- Trips after 10 failures in 60 seconds
- When tripped: blocks requests for 60 seconds, immediately uses fallback
- Prevents cascading failures and saves server resources
- Auto-resets after cooldown period

**States:**
- **CLOSED** (normal): Requests pass through
- **OPEN** (tripped): Requests blocked, fallback used immediately
- **HALF-OPEN** (after cooldown): Allows requests again, resets on success

## Benefits

1. **User Experience**: Users see responses instead of errors
2. **Cost Optimization**: Only uses more expensive fallback when necessary
3. **System Stability**: Circuit breaker prevents cascading failures
4. **Graceful Degradation**: System continues functioning during Google outages
5. **Resource Efficiency**: Exponential backoff prevents server overload

## Configuration

All patterns are automatically active. Configuration in `CachedGoogleModel`:

```python
# Circuit Breaker Settings
threshold=10          # Failures before tripping
window_seconds=60     # Time window for counting failures
cooldown_seconds=60   # How long circuit stays open

# Retry Settings
max_retries=3         # Number of retry attempts
```

## Monitoring

Look for these log messages:

**Exponential Backoff:**
```
503 detected for gemini-2.5-flash-lite (attempt 1/3), retrying in 1.23s...
```

**Model Fallback:**
```
🔄 Falling back from gemini-2.5-flash-lite to gemini-2.0-flash
✅ Fallback to gemini-2.0-flash succeeded
```

**Circuit Breaker:**
```
🔴 Circuit breaker TRIPPED for gemini-2.5-flash-lite: 10 failures in 60s. Blocking requests for 60s
🔴 Circuit breaker is OPEN for gemini-2.5-flash-lite (45s remaining)
🟢 Circuit breaker CLOSED for gemini-2.5-flash-lite (cooldown complete)
```

## Testing

The implementation handles:
- ✅ 503 Service Unavailable errors
- ✅ "UNAVAILABLE" status from Gemini API
- ✅ "high demand" messages
- ✅ Stale cache errors (existing functionality preserved)
- ✅ Model-specific cache handling (strips cache on fallback)
- ✅ RAG search functionality (identical in primary and fallback modes)
- ✅ Tool execution (search_knowledge_base, query_railway_postgres, etc.)
- ✅ System prompt preservation (via Agent configuration)
- ✅ Other errors (propagated normally)

## Cache and RAG Behavior

### Primary Model (gemini-2.5-flash-lite with cache)
- System prompt + tool declarations cached in Gemini
- Reduces token usage and cost
- Faster response times
- RAG search via search_knowledge_base tool

### Fallback Model (gemini-2.0-flash without cache)
- System prompt + tool declarations sent inline with each request
- Slightly higher token usage (no cache benefit)
- Identical functionality - all tools work the same
- RAG search via search_knowledge_base tool (same behavior)

**Key Point**: The fallback is functionally identical to the primary model. Users get the same quality responses with the same RAG search capabilities. The only differences are:
- Model version (2.0 vs 2.5)
- No cache benefit (inline mode)
- Slightly higher cost per request

## Files Modified

- `chatbot_orchestration/core/cached_google_model.py` - Added all three resilience patterns

## Deployment

No configuration changes needed. The patterns activate automatically when 503 errors occur.
