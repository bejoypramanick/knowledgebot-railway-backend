# PostgreSQL MCP for Vector Search - Implementation Guide

**Phase 1 Implementation Detail**
**Estimated Effort:** 2-3 weeks
**Complexity:** Medium
**Risk Level:** Low (read-only operations)

---

## Architecture: Current → MCP

### Current Architecture
```python
# chatbot_orchestration/tools/vector_search_tool.py (lines 90-180)

async def search_knowledge_base(ctx: RunContext[ChatSessionDeps], query: str):
    """Search knowledge base using SQLAlchemy + pgvector."""

    # Step 1: Generate query embedding (Gemini)
    embedding = await generate_embedding(query)  # ~200ms

    # Step 2: Direct SQL query (SQLAlchemy)
    async with get_db_session() as db:
        result = await db.execute(text("""
            SELECT ... similarity ... FROM document_chunks
            WHERE ... embedding <-> %s ...
            ORDER BY score DESC LIMIT 10
        """), {"embedding": embedding})

    # Step 3: Format results for Pydantic AI
    # ... LLMLingua-2 compression, formatting ...

    return formatted_context
```

**Latency Breakdown (Current):**
- Embedding generation: ~200ms
- SQL query: ~100ms
- Context compression: ~50ms
- Formatting: ~20ms
- **Total: ~370ms**

### With PostgreSQL MCP
```
┌──────────────────┐
│  Pydantic AI     │
│  (Agent)         │
└────────┬─────────┘
         │
         │ MCP invoke: search_knowledge_base
         │
┌────────▼──────────────────────────────┐
│  PostgreSQL MCP Server (Railway)      │
│  ├─ Query validation (read-only)      │
│  ├─ Connection pooling                │
│  └─ Result serialization (JSON)       │
└────────┬──────────────────────────────┘
         │
         │ SQL query (pgvector)
         │
┌────────▼──────────────────┐
│  PostgreSQL Primary        │
│  (pgvector + document_chunks)
└───────────────────────────┘
```

**New Latency (Estimated):**
- Embedding generation: ~200ms (unchanged, still in-app)
- MCP client overhead: ~10ms
- MCP server deserialization: ~15ms
- SQL query: ~100ms
- MCP result serialization: ~20ms
- Formatting: ~20ms
- **Total: ~365ms** (no significant change, slightly faster due to shared pooling)

---

## Implementation Steps

### Step 1: Set Up PostgreSQL MCP Server

#### Option A: Use Anthropic Reference Implementation (Recommended)
```bash
# 1. Create new Railway service
railway service create postgres-mcp --image anthropic/postgres-mcp

# 2. Configure environment
railway env add PG_HOST="${RAILWAY_POSTGRES_HOST}"
railway env add PG_PORT="5432"
railway env add PG_USER="vector_mcp_readonly"
railway env add PG_PASSWORD="${VECTOR_MCP_PASSWORD}"
railway env add PG_READONLY_MODE="true"
railway env add PG_ALLOWED_SCHEMAS="public"
railway env add PG_ALLOWED_TABLES="document_chunks,chat_sessions"
```

#### Option B: Deploy Custom Go Implementation (Lower Memory)
```golang
// mcp-server/postgres/main.go
package main

import (
	"context"
	"database/sql"
	"github.com/anthropics/go-sdk/pkg/mcp"
	_ "github.com/lib/pq"
)

type PostgresMCP struct {
	db *sql.DB
}

func (pm *PostgresMCP) ExecuteQuery(ctx context.Context, query string, params []interface{}) ([]map[string]interface{}, error) {
	// Validate query is read-only
	if !isReadOnlyQuery(query) {
		return nil, errors.New("write operations not allowed")
	}

	// Execute with timeout
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	rows, err := pm.db.QueryContext(ctx, query, params...)
	// ... serialize results as JSON
	return results, nil
}
```

**Resource Efficiency (Go Implementation):**
- Memory: ~50-80MB (vs 200MB+ for Python)
- CPU: 5-10% at 10 q/s
- Startup time: <1 second

### Step 2: Create MCP Client Wrapper

**File:** `chatbot_orchestration/tools/mcp_vector_client.py` (NEW)

```python
"""PostgreSQL MCP client wrapper for vector search."""
import json
import asyncio
from typing import List, Dict, Any, Optional
from pydantic_ai import RunContext
import httpx

from shared.otel_logger import get_otel_logger
from ..core.config import settings

logger = get_otel_logger("mcp_vector_client", "chatbot-orchestration")

class MCPVectorClient:
    """Client for PostgreSQL MCP server vector search."""

    def __init__(self):
        self.base_url = settings.MCP_VECTOR_SERVER_URL  # e.g., http://vector-mcp:8000
        self.timeout = httpx.Timeout(30.0)  # Generous timeout for queries

    async def search_vectors(
        self,
        embedding: List[float],
        session_id: str,
        limit: int = 10,
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors via MCP.

        Returns:
            List of chunks with similarity scores and metadata
        """
        query = {
            "tool": "execute_query",
            "params": {
                "query": """
                    SELECT
                        chunk_id,
                        document_id,
                        document_type,
                        content,
                        metadata,
                        1 - (embedding <=> %s::halfvec) as similarity_score,
                        source_name
                    FROM document_chunks
                    WHERE (
                        document_id IN (
                            SELECT source_id
                            FROM knowledge_base_assignments
                            WHERE session_id = %s
                        )
                    )
                    AND (1 - (embedding <=> %s::halfvec)) > %s
                    ORDER BY similarity_score DESC
                    LIMIT %s
                """,
                "params": [
                    json.dumps(embedding),  # halfvec format
                    session_id,
                    json.dumps(embedding),
                    threshold,
                    limit
                ]
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/mcp/invoke",
                    json=query
                )
                response.raise_for_status()

                results = response.json().get("results", [])

                logger.info(
                    f"📊 Vector search via MCP: {len(results)} results, "
                    f"top score {results[0]['similarity_score']:.3f}"
                    if results else "No results"
                )

                return results

        except httpx.TimeoutException:
            logger.error("❌ MCP vector search timeout (30s)")
            raise
        except Exception as e:
            logger.error(f"❌ MCP vector search failed: {e}")
            raise

# Singleton instance
mcp_vector_client = MCPVectorClient()
```

### Step 3: Update Vector Search Tool

**File:** `chatbot_orchestration/tools/vector_search_tool.py` (MODIFIED)

**Before (Direct SQLAlchemy):**
```python
async def search_knowledge_base(ctx: RunContext[ChatSessionDeps], query: str) -> str:
    """Search knowledge base and return formatted context."""

    # Generate embedding
    embedding = await generate_embedding(query)

    # Direct SQL query
    async with get_db_session() as db:
        result = await db.execute(text("""
            SELECT content, metadata, ... FROM document_chunks
            WHERE embedding <-> %s ...
        """), {"embedding": embedding})
        chunks = result.fetchall()

    # Format and compress
    return _format_context(chunks)
```

**After (MCP Client):**
```python
from .mcp_vector_client import mcp_vector_client

async def search_knowledge_base(ctx: RunContext[ChatSessionDeps], query: str) -> str:
    """Search knowledge base and return formatted context."""

    # Step 1: Generate embedding (unchanged)
    embedding = await generate_embedding(query)
    logger.info(f"🔍 Embedding generated: {len(embedding)} dims")

    # Step 2: Search via MCP (replaces SQLAlchemy)
    try:
        chunks = await mcp_vector_client.search_vectors(
            embedding=embedding,
            session_id=ctx.deps.session_id,
            limit=10,
            threshold=0.5
        )
        logger.info(f"✅ Retrieved {len(chunks)} chunks via MCP")
    except Exception as e:
        logger.error(f"❌ Vector search failed: {e}")
        # Fallback to empty context
        chunks = []

    # Step 3: Format and compress (unchanged)
    return _format_context(chunks)
```

**Key Changes:**
- ✅ Remove `async with get_db_session()` block
- ✅ Replace SQL execution with `mcp_vector_client.search_vectors()`
- ✅ Add fallback handling (empty context if MCP fails)
- ✅ Keep all formatting/compression logic unchanged

### Step 4: Update Settings & Configuration

**File:** `chatbot_orchestration/core/config.py` (ADD)

```python
# MCP Server configuration
MCP_VECTOR_SERVER_URL: str = Field(
    default="http://postgres-mcp:8000",
    description="PostgreSQL MCP server URL"
)
MCP_VECTOR_ENABLED: bool = Field(
    default=True,
    description="Enable MCP vector search (fallback to SQLAlchemy if False)"
)
```

**File:** `.env` (ADD)

```env
# PostgreSQL MCP Server
MCP_VECTOR_SERVER_URL=http://postgres-mcp:8000
MCP_VECTOR_ENABLED=true
```

### Step 5: Add Fallback Strategy (Resilience)

**File:** `chatbot_orchestration/tools/vector_search_tool.py` (ADD)

```python
async def search_knowledge_base_with_fallback(
    ctx: RunContext[ChatSessionDeps],
    query: str
) -> str:
    """Search with automatic fallback to direct SQLAlchemy if MCP fails."""

    # Try MCP path first
    if settings.MCP_VECTOR_ENABLED:
        try:
            return await search_knowledge_base_via_mcp(ctx, query)
        except Exception as e:
            logger.warning(f"⚠️ MCP failed, falling back to SQLAlchemy: {e}")

    # Fallback to direct SQLAlchemy (existing implementation)
    return await search_knowledge_base_via_sqlalchemy(ctx, query)

async def search_knowledge_base_via_mcp(ctx: RunContext[ChatSessionDeps], query: str) -> str:
    """MCP-based search (new path)."""
    embedding = await generate_embedding(query)
    chunks = await mcp_vector_client.search_vectors(
        embedding=embedding,
        session_id=ctx.deps.session_id,
        limit=10
    )
    return _format_context(chunks)

async def search_knowledge_base_via_sqlalchemy(ctx: RunContext[ChatSessionDeps], query: str) -> str:
    """Direct SQLAlchemy search (fallback path)."""
    # ... existing implementation
    pass
```

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_mcp_vector_client.py` (NEW)

```python
import pytest
from unittest.mock import AsyncMock, patch
from chatbot_orchestration.tools.mcp_vector_client import MCPVectorClient

@pytest.mark.asyncio
async def test_search_vectors_success():
    """Test successful vector search via MCP."""
    client = MCPVectorClient()

    with patch('httpx.AsyncClient.post') as mock_post:
        mock_post.return_value.json.return_value = {
            "results": [
                {
                    "chunk_id": "chunk-1",
                    "content": "Test content",
                    "similarity_score": 0.85
                }
            ]
        }

        results = await client.search_vectors(
            embedding=[0.1, 0.2, 0.3],
            session_id="session-1",
            limit=10
        )

        assert len(results) == 1
        assert results[0]["similarity_score"] == 0.85

@pytest.mark.asyncio
async def test_search_vectors_timeout():
    """Test timeout handling."""
    client = MCPVectorClient()

    with patch('httpx.AsyncClient.post') as mock_post:
        mock_post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            await client.search_vectors(
                embedding=[0.1, 0.2, 0.3],
                session_id="session-1"
            )
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_vector_search_tool_with_mcp(mcp_server_url):
    """Test vector search tool using real MCP server."""
    settings.MCP_VECTOR_SERVER_URL = mcp_server_url
    settings.MCP_VECTOR_ENABLED = True

    # Create test data in database
    # ... insert test chunks ...

    # Call tool
    result = await search_knowledge_base_with_fallback(
        ctx=mock_context,
        query="test query"
    )

    # Verify results
    assert "Source" in result
    assert len(result) > 0
```

### Load Tests

```python
# tests/load_test_vector_search.py

import asyncio
import time
from statistics import mean, stdev

async def load_test_vector_search(num_queries=100, concurrency=10):
    """Load test vector search with 100 queries at 10 concurrent."""

    queries = ["test query 1", "test query 2"] * 50
    latencies = []

    async def run_query(query):
        start = time.time()
        try:
            await search_knowledge_base_with_fallback(ctx, query)
            latencies.append((time.time() - start) * 1000)
        except Exception as e:
            print(f"Query failed: {e}")

    # Run with concurrency limit
    semaphore = asyncio.Semaphore(concurrency)
    async def bounded_query(query):
        async with semaphore:
            await run_query(query)

    await asyncio.gather(*[bounded_query(q) for q in queries])

    print(f"Total queries: {len(latencies)}")
    print(f"Mean latency: {mean(latencies):.1f}ms")
    print(f"Stdev: {stdev(latencies):.1f}ms")
    print(f"P99: {sorted(latencies)[int(len(latencies)*0.99)]:.1f}ms")
```

**Expected Results:**
- Mean latency: 150-200ms (50ms overhead acceptable)
- P99: <300ms
- Error rate: <0.5%

---

## Deployment on Railway

### 1. Create MCP Service

```yaml
# railway.toml
[services.vector-mcp]
name = "PostgreSQL Vector MCP"
buildCommand = "go build -o bin/mcp-server ./cmd/main.go"
startCommand = "./bin/mcp-server"
environment = [
  "PG_HOST=${{ services.postgres.PGHOST }}",
  "PG_PORT=${{ services.postgres.PGPORT }}",
  "PG_USER=vector_mcp_readonly",
  "PG_PASSWORD=${MCP_PASSWORD}",
  "PG_DATABASE=${{ services.postgres.PGDATABASE }}"
]
resources = {
  cpu = "0.5",
  memory = "512MB"
}
```

### 2. Create Database User (Read-Only)

```sql
-- Run on Railway PostgreSQL
CREATE USER vector_mcp_readonly WITH PASSWORD 'secure_password_here';
GRANT CONNECT ON DATABASE knowledgebase TO vector_mcp_readonly;
GRANT USAGE ON SCHEMA public TO vector_mcp_readonly;
GRANT SELECT ON document_chunks TO vector_mcp_readonly;
GRANT SELECT ON chat_sessions TO vector_mcp_readonly;
```

### 3. Update chatbot_orchestration Environment

```env
# Add to railway.json
MCP_VECTOR_SERVER_URL=http://vector-mcp.railway.internal:8000
MCP_VECTOR_ENABLED=true
```

### 4. Network Configuration

```yaml
# railway.toml - Network policies
[networks]
[[networks.rules]]
source = "chatbot_orchestration"
destination = "vector-mcp"
protocol = "tcp"
ports = [8000]

[[networks.rules]]
source = "vector-mcp"
destination = "postgres"
protocol = "tcp"
ports = [5432]
```

---

## Monitoring & Observability

### Metrics to Track

```python
# chatbot_orchestration/tools/mcp_vector_client.py

from prometheus_client import Counter, Histogram, Gauge

# Metrics
mcp_search_duration = Histogram(
    'mcp_vector_search_duration_ms',
    'Time to complete MCP vector search',
    buckets=[50, 100, 200, 500]
)

mcp_search_errors = Counter(
    'mcp_vector_search_errors_total',
    'Total MCP vector search errors',
    labelnames=['error_type']
)

mcp_server_health = Gauge(
    'mcp_server_health',
    'MCP server health (1=healthy, 0=unhealthy)'
)

# In search_vectors():
with mcp_search_duration.time():
    try:
        results = await client.post(...)
    except Exception as e:
        mcp_search_errors.labels(error_type=type(e).__name__).inc()
        raise
```

### Health Check Endpoint

```python
# Add to MCP server

@app.get("/health")
async def health_check():
    """MCP server health check."""
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "timestamp": datetime.utcnow()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}, 503
```

### OTEL Tracing

```python
# In mcp_vector_client.py

from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def search_vectors(...):
    with tracer.start_as_current_span("mcp_vector_search") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("query_limit", limit)

        results = await client.post(...)

        span.set_attribute("result_count", len(results))
        if results:
            span.set_attribute("top_score", results[0]["similarity_score"])

        return results
```

---

## Rollback Plan

If MCP integration causes issues:

1. **Immediate:** Set `MCP_VECTOR_ENABLED=false` in env
   ```bash
   railway env add MCP_VECTOR_ENABLED=false
   # Auto-fallback to SQLAlchemy
   ```

2. **Quick fix:** Restart chatbot_orchestration service (uses fallback)
   ```bash
   railway service restart chatbot-orchestration
   ```

3. **Full rollback:** Remove MCP client code, redeploy
   ```bash
   git revert <commit-with-mcp-changes>
   git push
   ```

---

## Timeline

| Week | Task | Owner | Status |
|------|------|-------|--------|
| 1 | Design review, setup PostgreSQL MCP on local | Dev | 📋 |
| 2 | Implement MCP client, unit tests | Dev | 📋 |
| 3 | Integration tests, load test | QA | 📋 |
| 4 | Deploy to Railway staging | DevOps | 📋 |
| 5 | Staging validation, performance baseline | QA | 📋 |
| 6 | Production rollout with monitoring | DevOps | 📋 |

---

## Success Criteria

✅ MCP vector search latency within 200ms (p99)
✅ Error rate <0.5% (same as current SQLAlchemy)
✅ Memory footprint <100MB per MCP instance
✅ Supports 100+ concurrent queries
✅ Automatic fallback to SQLAlchemy on MCP failure
✅ Zero impact on chat quality/relevance
✅ Cost neutral or better (pooling benefits)

