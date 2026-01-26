# Model Caching Implementation - Comprehensive Guide

## 📋 Overview

This document explains the complete model caching implementation in the KnowledgeBot system, including flow charts, detailed logging, and debugging guidance.

## 🔄 Model Caching Architecture Flow Chart

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           USER REQUEST (Chat Message)                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           1. CHAT_STREAM ENDPOINT (/chat/stream)                        │
│   - session_id: existing or new UUID4                                              │
│   - message: user query                                                            │
│   - use_rag: boolean                                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           2. SYSTEM PROMPT GENERATION (get_system_prompt)              │
│   ├─ Create prompt_components:                                                          │
│   │   - file_context: null (handled by FileSearch tool)                              │
│   │   - custom_prompt: user custom prompt (if any)                                   │
   │   - response_policy: 0-100 (flexible to strict)                                   │
│   │   - rag_had_results: true                                                           │
│   │   - model_name: "gemini-2.5-flash-lite"                                            │
│   ├─ Check cache with generate_cache_key()                                             │
│   │   - SHA256 hash of all components                                               │
│   │   - Key format: "file_context|custom_prompt|response_policy|rag_had_results|model_name" │
│   ├─ If cache hit:                                                                     │
│   │   - ✅ Return cached prompt (90% discount)                                           │
│   │   - 📦 Log: "Using cached system prompt (cache age: X.Xs)"                            │
│   └─ If cache miss:                                                                    │
   │       - Generate new ~2500-word system prompt                                     │
       - 💾 Cache it with 1-hour TTL                                               │
       - 📝 Log: "Cached system prompt with key: abc12345..."                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           3. PYDANTIC AI GATEWAY SERVICE (create_optimized_agent)       │
│   ├─ Initialize service (get_genai_client, get_railway_db)                             │
│   ├─ Get session metadata from PostgreSQL:                                                │
│   │   - file_search_store_id: existing or null                                          │
│   │   - cached_content_id: existing or null                                              │
│   │   - is_new_session: boolean                                                       │
│   ├─ If no cached_content_id:                                                              │
│   │   - 🧠 Create cached content via GenAI SDK                                         │
   │   - Model: gemini-2.5-flash-lite                                                    │
   │   - Contents: system prompt (2500 words)                                            │
   │   - TTL: 3600 seconds (1 hour)                                                   │
   │   - 📝 Log: "Creating cached content for system prompt"                             │
   │   - 📝 Log: "Created cached content: abc12345..."                                    │
│   ├─ If no file_search_store_id:                                                            │
   │   - 📦 Get existing stores via GenAI SDK                                        │
   │   - Look for "KnowledgeBot FileSearch Store"                                        │
   │   - If not found, create new one                                                      │
   │   - 📝 Log: "Found existing FileSearchStore: xyz789" or "Creating new FileSearchStore"       │
│   ├─ Configure GoogleModelSettings:                                                        │
   │   - google_cached_content: cached_content_id (90% discount key)                         │
   │   - 📝 Log: "Model settings: google_cached_content=abc123, file_search_store=xyz789"             │
│   ├─ Create GoogleModel with settings:                                                     │
│   │   - Model: gemini-2.5-flash-lite                                                    │
   │   - Settings: GoogleModelSettings(google_cached_content=cached_content_id)               │
│   │   - 📝 Log: "Created GoogleModel with google_cached_content for 90% discount"          │
│   └─ Create Pydantic AI Agent with optimized model                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           4. SESSION STATE MANAGEMENT (SessionStateManager)          │
│   ├─ Get session state:                                                                 │
│   │   - turn_count: 0 for new session                                                    │
│   │   - message_history: [] for new session                                               │
│   │   - last_activity: timestamp                                                        │
│   ├─ If turn_count > 0 (multi-turn):                                                        │
│   │   - 📚 Get preserved message_history from previous turns                              │
│   │   - 📝 Log: "Using preserved message history for turn X: Y messages"                     │
│   │   - 📝 Log: "Starting new session (turn 1) for session_id"                             │
│   └─ After agent.run():                                                                     │
│       - 🔄 Update session state with result.all_messages()                                │
│       - 📝 Log: "Updated session state for session_id: turn X, messages Y"                     │
│       - 📝 Log: "Preserved X messages for session_id"                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           5. AGENT EXECUTION (agent.run)                        │
│   ├─ Turn 1 (New Session):                                                              │
│   │   - Message: user query                                                            │
   │   - message_history: []                                                              │
   │   - deps: ChatSessionDeps(session_id)                                                  │
   │   - 📝 Log: "Starting optimized chat stream for session_id (turn 1)"                 │
│   │   - Gemini uses google_cached_content (90% discount)                               │
   │   - FileSearch tool uses file_search_store_id                                     │
│   ├─ Turns 2-5 (Multi-Turn):                                                             │
   │   - Message: follow-up question                                                       │
   │   - message_history: preserved from previous turns                                    │
   │   - deps: ChatSessionDeps(session_id)                                                  │
   │   - 📝 Log: "Starting optimized chat stream for session_id (turn X)"                 │
   │   - Gemini applies Implicit Prefix Caching (additional discount)                       │
   │   - FileSearch tool continues using same store_id                                   │
│   └─ Result processing and streaming                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                                    │
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           6. RESPONSE STREAMING                          │
│   ├─ Word-by-word streaming                                                              │
   │   - JSON chunks sent to frontend                                                  │
   │   - 📝 Log: "Stream completed successfully on attempt X (turn Y)"                      │
│   ├─ Success/Error handling                                                               │
│   └─ Session state cleanup                                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 🔧 Implementation Details

### 1. Local Memory Caching (Fast Path)

**Location**: `services/chatbot_orchestration/main.py:98-147`

```python
CACHE_TTL_SECONDS = 3600  # 1 hour TTL
context_cache = {}

def generate_cache_key(prompt_components: Dict[str, Any]) -> str:
    """Generate a unique cache key based on prompt components."""
    cache_data = {
        'file_context': str(sorted([(f.file_name, f.content[:100]) for f in prompt_components.get('file_context', [])])),
        'custom_prompt': prompt_components.get('custom_prompt', ''),
        'response_policy': prompt_components.get('response_policy', ''),
        'rag_had_results': prompt_components.get('rag_had_results', True),
        'model_name': MODEL_NAME
    }
    cache_string = json.dumps(cache_data, sort_keys=True)
    return hashlib.sha256(cache_string.encode()).hexdigest()
```

**Purpose**: Fast in-memory cache for frequently used system prompts
**TTL**: 1 hour
**Key Generation**: SHA256 hash of all prompt components

### 2. Gemini Cached Content (90% Discount)

**Location**: `services/chatbot_orchestration/main.py:1899-1919`

```python
async def get_or_create_cached_content(self, system_prompt: str) -> str:
    """Get existing cached content ID or create a new one using GenAI SDK."""
    try:
        logger.info("💾 Creating cached content for system prompt")
        cached_content = self.genai_client.cached_content.create(
            model=MODEL_NAME,
            contents=system_prompt,
            ttl=3600  # 1 hour TTL
        )
        logger.info(f"✅ Created cached content: {cached_content.name}")
        return cached_content.name
    except Exception as e:
        logger.error(f"❌ Error creating cached content: {e}")
        raise
```

**Purpose**: Google's native caching system with 90% discount
**TTL**: 1 hour
**Integration**: Used via `google_cached_content` in GoogleModelSettings

### 3. FileSearchStore Management

**Location**: `services/chatbot_orchestration/main.py:1864-1897`

```python
async def get_or_create_file_search_store(self) -> str:
    """Get existing FileSearchStore ID or create a new one using GenAI SDK."""
    try:
        stores = list(self.genai_client.stores.list())
        app_store = None
        for store in stores:
            if hasattr(store, 'display_name') and 'knowledgebot_file_search' in store.display_name.lower():
                app_store = store
                break
        
        if app_store:
            logger.info(f"📦 Found existing FileSearchStore: {app_store.name}")
            return app_store.name
        else:
            logger.info("🆕 Creating new FileSearchStore for knowledgebot")
            new_store = self.genai_client.stores.create(
                display_name="KnowledgeBot FileSearch Store",
                description="Centralized file search store for KnowledgeBot RAG operations"
            )
            logger.info(f"✅ Created new FileSearchStore: {new_store.name}")
            return new_store.name
    except Exception as e:
        logger.error(f"❌ Error managing FileSearchStore: {e}")
        raise
```

**Purpose**: Centralized file search store for RAG operations
**Reuse**: Same store reused across sessions for cost efficiency

### 4. Pydantic AI Integration

**Location**: `services/chatbot_orchestration/main.py:1942-1976`

```python
# Configure GoogleModelSettings with google_cached_content
model_settings = GoogleModelSettings(
    google_cached_content=cached_content_id,  # The "90% discount" key
)

google_model = GoogleModel(
    MODEL_NAME,
    settings=model_settings
)
```

**Purpose**: Bridge between GenAI SDK and Pydantic AI
**Key Feature**: `google_cached_content` tells Gemini to use cached content instead of raw system prompt

## 📊 Enhanced Logging Implementation

Let me add comprehensive logging to help with debugging:
<tool_call>edit
<arg_key>explanation</arg_key>
<arg_value>Add comprehensive logging for model caching debugging
