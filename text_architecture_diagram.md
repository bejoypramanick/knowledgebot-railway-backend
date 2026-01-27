# Text-Based Architecture Diagram - Gemini Caching Flow

## Complete Request Flow with Parameters

```
USER REQUEST
├── message: "What are your business hours?"
├── sessionId: "abc123-def456" (UUID)
├── userType: "customer"
└── timestamp: "2025-01-26T10:15:30Z"

FRONTEND LAYER
├── use-chat.ts
│   ├── sendMessage(text, sessionId, messages, chatConfig)
│   └── parameters:
│       ├── text: "What are your business hours?"
│       ├── sessionId: "abc123-def456"
│       ├── messages: []
│       └── chatConfig: {hil_enabled: false, security: {...}, persona: {...}}
│
├── AuthCacheService
│   ├── cacheKey: "digibot_auth_cache"
│   ├── cacheData: {userData: {...}, selectedRole: "customer", timestamp: 1706234567, uid: "user123"}
│   └── ttl: 300000 (5 minutes)
│
└── use-agent-chat-sse.tsx
    ├── sseUrl: "https://api-gateway.example.com/api/v1/chat/abc123-def456/events"
    ├── connectionState: "connecting"
    └── retryCount: 0

API GATEWAY
├── POST /chat/stream
├── headers: {"Content-Type": "application/json", "Authorization": "Bearer token123"}
├── body:
│   {
│     "session_id": "abc123-def456",
│     "message": "What are your business hours?",
│     "use_rag": true,
│     "custom_prompt": null,
│     "response_policy": 50
│   }
└── validatedRequest: ChatRequest(session_id="abc123-def456", message="What are your business hours?", ...)

LOCAL MEMORY CACHE LAYER
├── System Prompt Generation
│   ├── promptComponents:
│   │   ├── file_context: []
│   │   ├── custom_prompt: null
│   │   ├── response_policy: 50
│   │   ├── rag_had_results: true
│   │   └── model_name: "gemini-2.5-flash-lite"
│   └── cacheKey: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6"
│
├── Cache Check
│   ├── contextCache: {cacheKey: {prompt: "...", timestamp: 1706234447.89, components: {...}}}
│   ├── cacheAge: 120.5 seconds
│   ├── ttl: 3600 seconds
│   └── result: "CACHE_HIT"
│
└── Cache Entry (if hit)
    ├── prompt: "You are an advanced intelligent knowledge assistant..." (2543 chars)
    ├── timestamp: 1706234447.89
    └── components: {file_context: [], custom_prompt: "", response_policy: 50, ...}

SESSION MANAGEMENT LAYER
├── SessionStateManager
│   ├── sessionId: "abc123-def456"
│   ├── currentState:
│   │   ├── session_id: "abc123-def456"
│   │   ├── turn_count: 0
│   │   ├── message_history: []
│   │   ├── last_activity: 1706234567.89
│   │   └── created_at: 1706234567.89
│   └── operation: "get_session_state"
│
└── Session Update (after response)
    ├── turn_count: 1
    ├── message_history: [ModelMessage(user), ModelMessage(bot)]
    └── last_activity: 1706234589.12

DATABASE LAYER
├── PostgreSQL Query
│   ├── sql: "SELECT file_search_store_id, cached_content_id, created_at, updated_at FROM chat_sessions WHERE session_id = $1"
│   ├── params: ["abc123-def456"]
│   └── result: {file_search_store_id: null, cached_content_id: null, ...}
│
├── Session Metadata
│   ├── session_id: "abc123-def456"
│   ├── file_search_store_id: null (needs creation)
│   ├── cached_content_id: null (needs creation)
│   └── is_new_session: true
│
└── Metadata Update (after creation)
    ├── file_search_store_id: "stores/xyz789abc123"
    ├── cached_content_id: "cached_content_def456ghi789"
    └── updated_at: "2025-01-26T10:17:45Z"

GEMINI SDK LAYER
├── FileSearchStore Management
│   ├── operation: "stores.list()"
│   ├── existingStore: null (not found)
│   ├── createStore:
│   │   ├── display_name: "KnowledgeBot FileSearch Store"
│   │   ├── description: "Centralized file search store for KnowledgeBot RAG operations"
│   │   └── result: {name: "stores/xyz789abc123"}
│   └── storeId: "stores/xyz789abc123"
│
├── Cached Content Creation
│   ├── operation: "cached_content.create()"
│   ├── params:
│   │   ├── model: "gemini-2.5-flash-lite"
│   │   ├── contents: "You are an advanced intelligent knowledge assistant..." (2543 chars)
│   │   └── ttl: 3600
│   └── result: {name: "cached_content_def456ghi789"}
│
└── GoogleModelSettings
    ├── google_cached_content: "cached_content_def456ghi789"
    └── cost_discount: "90%"

PYDANTIC AI LAYER
├── GoogleModel Creation
│   ├── modelName: "gemini-2.5-flash-lite"
│   ├── settings: GoogleModelSettings(google_cached_content="cached_content_def456ghi789")
│   └── optimization: "90% discount applied"
│
├── Agent Creation
│   ├── model: GoogleModel (with cached content)
│   ├── system_prompt: "You are an advanced intelligent knowledge assistant..."
│   ├── tools: [FileSearchTool]
│   └── deps_type: ChatSessionDeps
│
└── Agent Execution
    ├── message: "What are your business hours?"
    ├── message_history: []
    ├── deps: ChatSessionDeps(session_id="abc123-def456")
    └── result: AgentResult(data="Our business hours are...", all_messages=[...], usage={...})

TOOLS & RAG LAYER
├── FileSearch Tool
│   ├── storeId: "stores/xyz789abc123"
│   ├── query: "business hours"
│   └── operation: "files.search(store, query)"
│
├── RAG Results
│   ├── results:
│   │   ├── {
│   │   │   ├── file_name: "business_info.pdf"
│   │   │   ├── content: "Our business hours are Monday-Friday 9AM-6PM..."
│   │   │   ├── relevance_score: 0.95
│   │   │   └── page_number: 1
│   │   └── {...}
│   └── total_count: 3
│
└── Context Enhancement
    ├── originalQuery: "What are your business hours?"
    ├── ragContext: "Based on business_info.pdf: Our business hours are..."
    └── enhancedPrompt: "User asks about business hours. Context: Our business hours are..."

RESPONSE LAYER
├── Response Generation
│   ├── finalResponse: "Based on our knowledge base, our business hours are Monday-Friday 9AM-6PM and weekends 10AM-4PM."
│   ├── sources: [{file_name: "business_info.pdf", relevance: 0.95, ...}]
│   └── metadata: {cached: true, turn_number: 1, response_time: 1.2s}
│
├── Session State Update
│   ├── session_id: "abc123-def456"
│   ├── turn_count: 1
│   ├── message_history: [ModelMessage(user), ModelMessage(bot)]
│   └── last_activity: 1706234589.12
│
├── Stream Response
│   ├── chunks:
│   │   ├── {type: "content", content: "Based ", session_id: "abc123-def456", timestamp: "..."}
│   │   ├── {type: "content", content: "on ", session_id: "abc123-def456", timestamp: "..."}
│   │   ├── {type: "content", content: "our ", session_id: "abc123-def456", timestamp: "..."}
│   │   └── ... (word by word streaming)
│   └── delay: 50ms between chunks
│
└── Frontend Update
    ├── newMessage:
    │   ├── id: "msg_789xyz"
    │   ├── text: "Based on our knowledge base, our business hours are..."
    │   ├── sender: "bot"
    │   ├── timestamp: "2025-01-26T10:17:50Z"
    │   └── metadata: {sources: [...], cached: true, turn_number: 1}
    └── uiState: {messages: [...], isLoading: false, error: null}

CACHE PERFORMANCE METRICS
├── Local Memory Cache
│   ├── hitRate: 85%
│   ├── ttl: 3600s
│   ├── memoryUsage: ~10MB
│   └── cacheSize: 100 entries
│
├── Gemini Cached Content
│   ├── costSavings: 90%
│   ├── ttl: 3600s
│   ├── reuseAcross: all sessions
│   └── discountApplied: true
│
├── FileSearchStore
│   ├── reuseAcross: all sessions
│   ├── creationCost: one-time
│   ├── performance: optimized RAG
│   └── storeId: "stores/xyz789abc123"
│
└── Session State
    ├── memoryPerSession: ~1MB
    ├── turnLimit: 5
    ├── implicitPrefixCaching: turns 2-5
    └── multiTurnSavings: additional 20-30%

COST ANALYSIS (PER REQUEST)
├── Without Caching
│   ├── system_prompt: 2500 tokens × $0.000075/1000 = $0.0001875
│   ├── user_message: 10 tokens × $0.000075/1000 = $0.00000075
│   └── total_per_request: $0.000188
│
├── With Caching
│   ├── turn_1_cache_miss: $0.000188
│   ├── turns_2_5_cache_hit: $0.0000188 each
│   └── total_5_turn_session: $0.0002632
│
└── Savings
    ├── per_request: 90% (after first)
    ├── per_session: 72%
    └── annual_estimated: $ thousands

ERROR HANDLING & FALLBACKS
├── Cache Miss → Generate new prompt
├── API Failure → Fallback store ID
├── DB Issues → In-memory session state
├── Network Issues → SSE reconnection (exponential backoff)
└── Gemini Failure → Direct model usage (no caching)
```

## Key Parameter Summary

### Critical Identifiers
- **sessionId**: "abc123-def456" (UUID v4)
- **cacheKey**: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6" (SHA256)
- **cached_content_id**: "cached_content_def456ghi789" (Gemini API)
- **file_search_store_id**: "stores/xyz789abc123" (Gemini API)

### Performance Parameters
- **TTL**: 3600 seconds (1 hour) for all caches
- **Cache Hit Rate**: >80% target for local cache
- **Cost Discount**: 90% for Gemini cached content
- **Session Turns**: 5-turn limit for optimal performance
- **Stream Delay**: 50ms between chunks
- **Retry Logic**: Exponential backoff for SSE

### Data Sizes
- **System Prompt**: ~2500 characters
- **Local Cache**: ~10MB for 100 prompts
- **Session Memory**: ~1MB per active session
- **RAG Results**: Variable, typically <50KB
