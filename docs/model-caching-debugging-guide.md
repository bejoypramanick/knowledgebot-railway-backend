# Model Caching Debugging Guide

## 🔍 What to Search in Railway Logs

### 1. Cache Hit/Miss Patterns

**Search for these log patterns to understand cache behavior:**

```bash
# Cache key generation
grep "🔑 Generated cache key" chatbot_orchestration.log

# Cache hits (90% discount applied)
grep "✅ CACHE HIT" chatbot_orchestration.log

# Cache misses (new prompt generation)
grep "❌ CACHE MISS" chatbot_orchestration.log

# Cache expiration
grep "⏰ CACHE EXPIRED" chatbot_orchestration.log

# Cache storage
grep "💾 Caching system prompt" chatbot_orchestration.log
```

### 2. Gemini Cached Content Operations

**Search for Gemini cached content creation and usage:**

```bash
# Cached content creation
grep "💾 Creating cached content via GenAI SDK" chatbot_orchestration.log

# Successful cached content creation
grep "✅ Successfully created cached content" chatbot_orchestration.log

# Cached content ID usage
grep "🧠 Using cached content" chatbot_orchestration.log

# Cost efficiency indicators
grep "💰 COST EFFICIENCY" chatbot_orchestration.log
```

### 3. FileSearchStore Management

**Search for FileSearchStore operations:**

```bash
# FileSearchStore discovery
grep "📦 Found existing FileSearchStore" chatbot_orchestration.log

# FileSearchStore creation
grep "🆕 Creating new FileSearchStore" chatbot_orchestration.log

# FileSearchStore usage
grep "🔗 Using FileSearchStore" chatbot_orchestration.log
```

### 4. Pydantic AI Agent Configuration

**Search for agent optimization:**

```bash
# GoogleModelSettings configuration
grep "⚙️ Model settings" chatbot_orchestration.log

# GoogleModel creation
grep "✅ Created GoogleModel with google_cached_content" chatbot_orchestration.log

# Agent creation
grep "🤖 Created optimized Pydantic AI Agent" chatbot_orchestration.log
```

### 5. Session State Management

**Search for multi-turn conversation patterns:**

```bash
# Session state updates
grep "🔄 Updated session state" chatbot_orchestration.log

# Message history preservation
grep "📚 Using preserved message history" chatbot_orchestration.log

# Turn counting
grep "turn" chatbot_orchestration.log

# New session detection
grep "🆕 Starting new session" chatbot_orchestration.log
```

### 6. Database Operations

**Search for PostgreSQL metadata operations:**

```bash
# Session metadata retrieval
grep "🔍 Retrieving session metadata" chatbot_orchestration.log

# Database queries
grep "📊 Querying chat_sessions table" chatbot_orchestration.log

# Metadata updates
grep "💾 Updated session metadata" chatbot_orchestration.log
```

## 📊 Expected Log Patterns

### ✅ Successful Cache Hit (90% Discount)

```
🚀 Generating system prompt:
  - file_context: 0 items
  - custom_prompt: 'None'...
  - response_policy: None
  - rag_had_results: True
  - model_name: gemini-2.5-flash-lite

🔍 Checking local cache for system prompt...
🔑 Generating cache key for prompt components:
  - file_context: 0 items
  - custom_prompt: ''...
  - response_policy: None
  - rag_had_results: True
  - model_name: gemini-2.5-flash-lite
🔑 Generated cache key: a1b2c3d4e5f6g7h8...
🔍 Checking cache for key: a1b2c3d4e5f6g7h8...
🔍 Current cache size: 3 entries
📦 Cache entry found:
  - Cache age: 120.5s (2.0m)
  - TTL: 3600s (60.0m)
  - Expires in: 3479.5s
  - Prompt length: 2543 chars
  - Created at: 2025-01-26T10:15:30.123456
✅ CACHE HIT - Using cached system prompt (age: 120.5s)
✅ Cache efficiency: 90% discount applied
✅ SYSTEM PROMPT CACHED - Using cached prompt (2543 chars)
```

### ❌ Cache Miss (New Prompt Generation)

```
🚀 Generating system prompt:
  - file_context: 0 items
  - custom_prompt: 'Be more conversational'...
  - response_policy: 50
  - rag_had_results: True
  - model_name: gemini-2.5-flash-lite

🔍 Checking local cache for system prompt...
🔑 Generating cache key for prompt components:
  - file_context: 0 items
  - custom_prompt: 'Be more conversational'...
  - response_policy: 50
  - rag_had_results: True
  - model_name: gemini-2.5-flash-lite
🔑 Generated cache key: x9y8z7w6v5u4t3s2...
🔍 Checking cache for key: x9y8z7w6v5u4t3s2...
🔍 Current cache size: 3 entries
❌ CACHE MISS - No entry found for key: x9y8z7w6v5u4t3s2...
❌ SYSTEM PROMPT NOT CACHED - Generating new prompt...
📝 Generating new system prompt (~2500 words)...

💾 Caching system prompt:
  - Cache key: x9y8z7w6v5u4t3s2...
  - Prompt length: 2543 characters
  - TTL: 3600s (60.0m)
  - Timestamp: 2025-01-26T10:17:45.789012
  - Components: ['file_context', 'custom_prompt', 'response_policy', 'rag_had_results']
💾 Cache entry stored. New cache size: 4 entries
💾 Cache efficiency: 90% discount available for future requests
```

### 🧠 Gemini Cached Content Creation

```
🧠 Managing cached content for system prompt:
  - System prompt length: 2543 characters
  - Model: gemini-2.5-flash-lite
  - TTL: 3600 seconds (1 hour)

💾 Creating cached content via GenAI SDK...
  - Model: gemini-2.5-flash-lite
  - TTL: 3600s
  - Content preview: You are an advanced intelligent knowledge assistant chatbot with access to multiple sophisticated data sources...

✅ Successfully created cached content:
  - Content ID: cached_content_abc123def456
  - Content name: cached_content_abc123def456
  - Model: gemini-2.5-flash-lite
  - TTL: 3600s
  - Created at: 2025-01-26T10:17:50.123456
💰 COST EFFICIENCY: 90% discount applied to future requests
```

### 🤖 Optimized Agent Creation

```
⚙️ Model settings: google_cached_content=cached_content_abc123def456, file_search_store=file_search_store_xyz789
✅ Created GoogleModel with google_cached_content for 90% discount
🤖 Created optimized Pydantic AI Agent for session_123456789
```

### 🔄 Multi-Turn Conversation

```
🆕 Starting new session (turn 1) for session_123456789
🚀 Starting optimized chat stream for session_123456789 (turn 1)
✅ Stream completed successfully on attempt 1 (turn 1)
🔄 Updated session state for session_123456789: turn 1, messages 2

📚 Using preserved message history for turn 2: 2 messages
🚀 Starting optimized chat stream for session_123456789 (turn 2)
✅ Stream completed successfully on attempt 1 (turn 2)
🔄 Updated session state for session_123456789: turn 2, messages 4
```

## 🚨 Error Patterns to Watch For

### 1. Cache Creation Failures

```
❌ Error creating cached content: [ERROR_DETAILS]
❌ This will prevent 90% cost discount optimization
```

**Impact**: No 90% discount, full price for all requests

### 2. FileSearchStore Issues

```
❌ Error managing FileSearchStore: [ERROR_DETAILS]
```

**Impact**: RAG functionality may fail

### 3. Database Connection Issues

```
❌ Database not initialized for session metadata retrieval
```

**Impact**: Session state lost, no metadata persistence

### 4. Cache Expiration Issues

```
⏰ CACHE EXPIRED - Removing expired entry for key: abc123...
⏰ Cache was 120.5s past TTL
```

**Impact**: Normal behavior, but monitor frequency

## 📈 Performance Metrics to Track

### 1. Cache Hit Rate

```bash
# Count cache hits vs misses
grep "✅ CACHE HIT" chatbot_orchestration.log | wc -l
grep "❌ CACHE MISS" chatbot_orchestration.log | wc -l

# Calculate hit rate
HITS=$(grep "✅ CACHE HIT" chatbot_orchestration.log | wc -l)
MISSES=$(grep "❌ CACHE MISS" chatbot_orchestration.log | wc -l)
TOTAL=$((HITS + MISSES))
HIT_RATE=$((HITS * 100 / TOTAL))
echo "Cache Hit Rate: ${HIT_RATE}%"
```

### 2. Cost Savings

```bash
# Count 90% discount applications
grep "💰 COST EFFICIENCY: 90% discount" chatbot_orchestration.log | wc -l

# Count full price operations
grep "❌ SYSTEM PROMPT NOT CACHED" chatbot_orchestration.log | wc -l
```

### 3. Session Duration

```bash
# Track multi-turn conversations
grep "turn" chatbot_orchestration.log | grep "completed successfully"
```

## 🔧 Troubleshooting Steps

### 1. Cache Not Working

**Symptoms**: All requests show "❌ CACHE MISS"

**Check**:
1. Are cache keys being generated consistently?
2. Is the cache being cleared prematurely?
3. Are prompt components changing between requests?

### 2. 90% Discount Not Applied

**Symptoms**: No "💰 COST EFFICIENCY" logs

**Check**:
1. Is `google_cached_content` being set in GoogleModelSettings?
2. Is Gemini cached content creation successful?
3. Are cached content IDs being reused properly?

### 3. Multi-Turn Not Working

**Symptoms**: Always "turn 1" in logs

**Check**:
1. Is session state being preserved?
2. Are message history objects being stored?
3. Is `result.all_messages()` being called correctly?

## 📱 Railway Log Access

1. **Go to Railway Dashboard**
2. **Select your service**
3. **Click "Logs" tab**
4. **Use the search patterns above**
5. **Filter by time range for specific sessions**

## 🎯 Success Indicators

✅ **High Cache Hit Rate** (>80%)
✅ **Frequent "💰 COST EFFICIENCY" logs**
✅ **Multi-turn conversations (turns 2-5)**
✅ **Consistent FileSearchStore reuse**
✅ **No error patterns in logs**

🚨 **Warning Signs**:
❌ Low cache hit rate (<50%)
❌ Frequent cache creation failures
❌ Always turn 1 (no multi-turn)
❌ Database connection errors
❌ FileSearchStore creation failures
