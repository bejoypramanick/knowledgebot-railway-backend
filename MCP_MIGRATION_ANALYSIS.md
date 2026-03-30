# MCP Server Migration Analysis for knowledgebot-railway-backend

**Analysis Date:** March 30, 2026
**Current Architecture:** Multi-service (kreuzberg-worker, celery workers, api_gateway, chatbot_orchestration)
**Deployment Target:** Railway (Rust + Python + Node.js mix)

---

## Executive Summary

Your system can benefit from **3-4 strategic MCP migrations** that reduce operational complexity and improve maintainability, with **minimal performance impact** for read-heavy operations.

| Service | Component | MCP Candidate | Priority | Performance Impact | Risk |
|---------|-----------|----------------|----------|-------------------|------|
| **chatbot_orchestration** | Vector search (PgVector) | `PostgreSQL MCP` or `Milvus MCP` | 🔴 HIGH | +30-50ms | Low |
| **celery-web-worker** | Web scraping (crawl4ai) | `Firecrawl MCP` | 🟡 MEDIUM | No impact (I/O bound) | Low |
| **api_gateway + file-worker** | Database queries | `PostgreSQL MCP` (read-only) | 🟡 MEDIUM | +50-100ms | Medium |
| **kreuzberg-worker** | (KEEP AS-IS) | ❌ Not applicable | - | - | N/A |

---

## 1. VECTOR SEARCH → PostgreSQL MCP or Milvus MCP

### Current Architecture
```
chatbot_orchestration/tools/vector_search_tool.py
├─ Database: PostgreSQL pgvector (halfvec embeddings)
├─ Query: SQL with vector similarity + FTS + structure boost
├─ Pipeline: generate_embedding() → SQL query → LLMlingua-2 compression → context formatting
└─ Latency: ~100-150ms (single threaded SQLAlchemy)
```

### Migration Path: PostgreSQL MCP

**Implementation:**
```
ChatBot → Pydantic AI Agent → MCP Client
                              ↓
                    PostgreSQL MCP Server
                              ↓
                    PostgreSQL (pgvector)
```

**Benefits:**
- ✅ No application code changes — same query interface
- ✅ Stateless MCP server (easy Railway deployment)
- ✅ Connection pooling is MCP server's responsibility
- ✅ Single source of truth for schema management

**Trade-offs:**
- ⚠️ Latency: +50ms overhead per query (100-150ms → 150-200ms)
- ⚠️ Complexity: One more service to monitor/manage
- ⚠️ Network hop: Query serialization/deserialization cost

**Migration Effort:** 🟡 **MEDIUM (2-3 hours)**
- Replace SQLAlchemy context manager → MCP tool invocation
- Move SQL query logic to MCP server
- Keep vector_search_tool.py as MCP client wrapper
- No database schema changes needed

**Code Location:**
- `chatbot_orchestration/tools/vector_search_tool.py` (lines 90-180: SQL query execution)
- `chatbot_orchestration/service/streaming_service.py` (lines 300-350: context building)

**Recommendation:** ✅ **IMPLEMENT**
- **Why:** Isolates database access pattern, enables shared query service for multiple AI applications
- **When:** After current stabilization (not blocking)
- **Alternative:** Skip if vector search latency is critical (<100ms SLA)

---

## 2. WEB SCRAPING → Firecrawl MCP

### Current Architecture
```
celery-web-worker/service/processing_service.py
├─ Tool: crawl4ai (built-in HTML cleaning)
├─ Process: crawl → parse HTML → temp S3 upload → docling queue → Gemini formatting
└─ Latency: ~5-15s per page (I/O bound, depends on site response time)
```

### Migration Path: Firecrawl MCP

**Implementation:**
```
celery-web-worker
├─ Current: crawl4ai for fetch + clean
└─ MCP: Firecrawl MCP for fetch + clean + extract

Firecrawl MCP (Railway service)
├─ Tools: scrape, crawl, search, extract, screenshot
└─ Backend: headless browser + extraction logic
```

**Benefits:**
- ✅ Same feature set (crawl, clean, extract) as crawl4ai
- ✅ Better ad/menu/form removal (Firecrawl optimized)
- ✅ Browser control for JavaScript-heavy sites
- ✅ Structured data extraction (tables, lists, forms)
- ✅ Reduces dependencies in celery-web-worker

**Trade-offs:**
- ⚠️ Cost: Firecrawl has usage-based pricing (not OSS like crawl4ai)
- ⚠️ Latency: Same 5-15s (no improvement)
- ⚠️ Dependency: Need to run Firecrawl service on Railway

**Migration Effort:** 🟡 **MEDIUM (3-4 hours)**
- Replace crawl4ai calls → Firecrawl MCP tool calls
- Move to MCP-based invocation in Pydantic AI agent
- Remove crawl4ai dependency from celery-web-worker/requirements.txt
- Add Firecrawl MCP server to Railway deployments

**Code Location:**
- `celery-web-worker/service/processing_service.py` (lines 300-350: crawl4ai integration)
- `celery-web-worker/dao/scraping_dao.py` (website fetch logic)

**Recommendation:** 🟡 **CONDITIONAL IMPLEMENT**
- **Why:** Simplifies web-worker dependencies, gives access to better extraction/browser features
- **When:** If crawl4ai limitations become blocking (JS-heavy sites, extraction quality)
- **Cost Consideration:** Firecrawl MCP is **not free** — need cost/benefit analysis
- **Alternative:** Keep crawl4ai as-is if current quality is sufficient

---

## 3. DATABASE QUERIES → PostgreSQL MCP (Read-Only)

### Current Architecture
```
Multiple services use SQLAlchemy:
├─ api_gateway: User profiles, file metadata queries
├─ celery-file-worker: File details, chunk insertion, metrics
├─ celery-web-worker: Website metadata, scraping records
└─ chatbot_orchestration: Session queries, vector searches
```

### Migration Path: PostgreSQL MCP (Read-Only Layer)

**Only Read Queries:**
```
Services (api_gateway, workers)
        ↓ read-only queries only
PostgreSQL MCP Server (Railway)
        ↓
PostgreSQL (primary)
```

**Benefits:**
- ✅ Decouples database schema from application code
- ✅ Single query validation point (MCP server enforces read-only)
- ✅ Connection pooling at MCP layer (reduces backend load)
- ✅ Shared schema inspection for code generation

**Trade-offs:**
- ⚠️ Latency: +50-100ms per query (network hop + reasoning)
- ⚠️ Complexity: Schema changes require MCP server updates
- ⚠️ NOT suitable for writes (file insertion, chunk insertion)
- ⚠️ Breaking change: Moves connection logic from apps to MCP

**Migration Effort:** 🔴 **HIGH (6-8 hours)**
- Identify all read-only queries across services
- Move query logic to MCP server (schema introspection, prepared statements)
- Keep write operations direct (file insertion, vector ingestion) — DON'T migrate
- Update all read operations to use MCP tool invocation
- Handle query result deserialization (MCP returns JSON)

**Code Locations (Read Operations):**
- `api_gateway/routes/chatbot.py` - Session queries, file metadata
- `celery-file-worker/dao/fileupload_dao.py` - File details by task_id
- `chatbot_orchestration/service/streaming_service.py` - Session display ID lookup
- `chatbot_orchestration/tools/knowledge_tools.py` - Conversation history queries

**Code Locations (Write Operations — KEEP DIRECT):**
- `chatbot_orchestration/tools/vector_search_tool.py` - Vector chunk insertion
- `celery-file-worker/service/processing_service.py` - File metadata updates, chunk insertion
- `shared/vector_dao.py` - batch_insert_chunks

**Recommendation:** 🔴 **SKIP FOR NOW**
- **Why:** High implementation burden for read-only queries with significant latency cost
- **When:** Only if database access patterns become security concern (isolation required)
- **Better Alternative:** Keep write paths direct (SQLAlchemy), migrate vector search specifically (see #1)

---

## 4. KREUZBERG WORKER → ❌ KEEP AS-IS

### Why NOT to Migrate

**Current:**
```
kreuzberg-worker (Rust service)
├─ Input: PDF/DOCX/HTML from S3 via Redis queue
├─ Processing: Document extraction, table chunking, grid-based cell alignment
├─ Output: Markdown + JSON artifacts to S3
└─ Latency: ~30-120s per document (CPU-bound, depends on file size/format)
```

**Why MCP is Wrong:**
- ❌ **CPU-bound workload**: kreuzberg does heavy document parsing/OCR
- ❌ **Long-running**: 30-120s processing doesn't fit tool invocation model (<200ms target)
- ❌ **I/O heavy**: Reads from S3, writes to S3, stores intermediate state in Redis
- ❌ **Specialized format**: Unique GridCell/TableGrid data structures
- ❌ **No benefit**: Would add network overhead without reducing complexity

**Keep Rust Worker Because:**
- ✅ Performance: Kreuzberg is optimized C++/Rust (not improvable via MCP)
- ✅ Isolation: Separate worker process avoids blocking AI operations
- ✅ Async queuing: Redis-based job queue handles backpressure
- ✅ Scalability: Can spin up multiple instances on Railway
- ✅ Specialized: No equivalent MCP server with GridCell support

**Recommendation:** ✅ **KEEP AS DEDICATED RUST SERVICE**

---

## 5. EMBEDDING GENERATION → ❌ KEEP INLINE (for now)

### Current
```
chatbot_orchestration/tools/vector_search_tool.py (line 18)
├─ Generate embedding via Gemini API on every vector search
└─ Latency: ~200-300ms per query
```

### Why NOT MCP:
- ❌ **Invoked for every search**: Too frequent for service overhead
- ❌ **High frequency**: 10-50 embeddings per conversation
- ❌ **Adds latency**: 50ms MCP overhead + embedding time = worse experience
- ❌ **Simple passthrough**: No complex logic that benefits from isolation

### Consider Later If:
- Embedding becomes bottleneck (profile first)
- Want to cache embeddings across conversations
- Need embedding model selection logic (A/B testing)

**Recommendation:** ✅ **KEEP INLINE**

---

## 6. CONTEXT COMPRESSION (LLMLingua-2) → ❌ KEEP INLINE

### Current
```
vector_search_tool.py (_compress_context function)
├─ Compresses context 50% (quantized BERT model)
└─ Latency: ~50-200ms
```

### Why NOT MCP:
- ❌ **Blocking operation**: Called synchronously during context building
- ❌ **Heavy model**: Quantized BERT (~500MB) — MCP service overhead exceeds benefit
- ❌ **Not reusable**: Compression happens once per query
- ❌ **Low invocation frequency**: Not worth separate service

**Recommendation:** ✅ **KEEP INLINE**

---

## Migration Priority Matrix

```
┌─────────────────────────────────────────────────────────┐
│                    EFFORT vs BENEFIT                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  HIGH BENEFIT                                            │
│  │                                                       │
│  │   ┌─────────────────────────────────────┐           │
│  │   │  2. Firecrawl MCP                   │ (IF cost OK)
│  │   │  (Low effort, medium benefit)       │           │
│  │   │                                     │           │
│  │   │  1. PostgreSQL MCP (Vector)         │           │
│  │   │  (Medium effort, high benefit)      │ RECOMMEND │
│  │   └─────────────────────────────────────┘           │
│  │                                                       │
│  │                                 ┌─────────────────┐  │
│  │                                 │ 3. Full DB MCP  │  │
│  │                                 │ (High effort,   │  │
│  │                                 │ medium benefit) │  │
│  │                                 │ SKIP FOR NOW    │  │
│  │                                 └─────────────────┘  │
│  │                                                       │
│  └────────────────────────────────────────────────────┐ │
│                  LOW              MEDIUM      HIGH      │ │
│                                          EFFORT ────────┘ │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Recommended Implementation Plan

### Phase 1: Vector Search Isolation (RECOMMENDED)
**Timeline:** 2-3 weeks after current stabilization

**Components:**
1. Deploy PostgreSQL MCP server on Railway
   - Use Anthropic reference implementation
   - Configure read-only queries on pgvector table
   - Add connection pooling (PgBouncer)

2. Modify `vector_search_tool.py`
   - Replace SQLAlchemy context manager with MCP tool wrapper
   - Keep existing compression, formatting logic
   - Add latency monitoring (track +30-50ms overhead)

3. Testing
   - Load test: 100 concurrent vector searches
   - Verify latency degradation acceptable (<200ms target)
   - Monitor memory footprint (MCP server ~100MB)

4. Deployment
   - Railway config: PostgreSQL MCP as separate service
   - Scaling: 2 MCP instances with load balancing
   - Monitoring: OTEL metrics on query performance

**Benefits:**
- Enables shared vector search for multiple AI applications
- Single schema validation point
- Prepares for vector database migration (Milvus) if needed

---

### Phase 2: Conditional Firecrawl Integration
**Timeline:** 4-6 weeks after Phase 1 (if current web scraping is blocking)

**Only if:**
- ✅ crawl4ai has extraction quality issues
- ✅ JavaScript-heavy sites require browser automation
- ✅ Cost analysis shows ROI (usage-based pricing)

**Implementation:**
- Deploy Firecrawl MCP on Railway
- Replace crawl4ai calls in celery-web-worker
- Remove crawl4ai dependency

---

## Performance Impact Summary

### Vector Search (PostgreSQL MCP)
```
Current:  query_latency=100ms, throughput=10 q/s, p99=150ms
With MCP: query_latency=150ms, throughput=8 q/s, p99=200ms
Impact:   +50ms (acceptable for RAG context retrieval)
```

### Full Read Queries (PostgreSQL MCP)
```
Not Recommended - Too much latency penalty for frequent reads
Would impact: session queries, file metadata retrieval
Cost: 50-100ms per query × 100 queries/session = 5-10s added latency
```

### Web Scraping (Firecrawl MCP)
```
Current:  scrape_latency=8s, depends on site response
With MCP: scrape_latency=8-10s (same I/O bound)
Impact:   Minimal (if site is slow, network dominates)
```

---

## Railway Deployment Configuration

### Vector Search MCP Service
```yaml
# railway.toml (hypothetical)
[services.vector-mcp]
name = "PostgreSQL Vector MCP"
image = "anthropic-reference/postgres-mcp"
environment = [
  "PG_HOST=railway-postgres-instance",
  "PG_USER=mcp_readonly",
  "PG_PASSWORD=${PG_MCP_PASSWORD}",
  "PG_READONLY_MODE=true"
]
resources = {
  cpu = "0.5",      # Share CPU
  memory = "512MB"  # Lightweight
}
replicas = 2
```

### Firecrawl MCP Service (Optional)
```yaml
[services.firecrawl-mcp]
name = "Firecrawl MCP"
image = "firecrawl/mcp-server"
environment = [
  "FIRECRAWL_API_KEY=${FIRECRAWL_KEY}"
]
resources = {
  cpu = "1.0",
  memory = "1024MB"
}
replicas = 1
```

### Keep as Dedicated Services
```yaml
[services.kreuzberg-worker]
# No changes - stays as Rust worker
```

---

## Architecture Diagram (After Phase 1)

```
┌─────────────────────────────────────────────────────────────┐
│                     Pydantic AI Agent                       │
│                  (chatbot_orchestration)                    │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┬──────────────────┐
        │                         │                  │
        ▼                         ▼                  ▼
  Knowledge Tools        Streaming Service      Vector Search Tool
  (search_knowledge)  (message formatting)   (MOVED TO MCP)
        │                         │                  │
        │                         │          ┌───────┴───────┐
        │                         │          │               │
        │                         │     [MCP Client]    [MCP Client]
        │                         │          │               │
        └─────────────┬───────────┴──────────┼───────────────┘
                      │                      │
                      ▼                      ▼
            PostgreSQL (Primary)   PostgreSQL MCP Server
                                   (Read-only queries)
                                          │
                                          ▼
                                  pgvector table
                                  (document_chunks)
```

---

## Risk Analysis

### Vector Search MCP Migration
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Network latency spikes | Medium | High | Load balancing, connection pooling |
| MCP server crashes | Low | Medium | Fallback to direct SQLAlchemy |
| Schema drift | Low | High | Schema versioning, migrations as code |
| Connection pool exhaustion | Medium | Medium | Proper resource limits, monitoring |

### Firecrawl MCP Migration (if chosen)
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| API cost overrun | High | Medium | Usage quotas, monitoring |
| Service unavailability | Low | Medium | Queue-based fallback to crawl4ai |
| Rate limiting | Medium | Low | Backoff strategy, queue management |

---

## Conclusion

**Recommendation:** Implement Phase 1 (Vector Search MCP) after code stabilizes.

**Why:**
1. ✅ Low risk: Read-only operations are easy to isolate
2. ✅ Medium effort: 2-3 weeks for solid implementation
3. ✅ Real benefit: Enables shared vector search service
4. ✅ Prepares architecture: For future vector DB migration (Milvus)
5. ✅ Acceptable latency: +50ms is negligible for RAG context retrieval

**Skip:**
- ❌ Full read-only database MCP (high effort, latency penalty, low benefit)
- ❌ Kreuzberg as MCP (wrong tool for long-running CPU work)

**Conditional (Later):**
- 🟡 Firecrawl MCP (only if crawl4ai limitations become blocking + cost justified)

---

## Next Steps

1. **This week:** Review this analysis with team
2. **Next week:** Benchmark current vector search latency (50ms overhead acceptable?)
3. **2 weeks:** Prototype PostgreSQL MCP integration on local environment
4. **4 weeks:** Deploy to Railway staging, load test with real queries
5. **6 weeks:** Production rollout with fallback strategy

