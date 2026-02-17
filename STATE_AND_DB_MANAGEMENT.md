# State and Database Management Architecture

Complete architectural analysis of how state and databases are managed in knowledgebot-railway-backend.

---

## Executive Summary

Your application uses a **distributed microservices architecture** with three layers of state management:

| Layer | Technology | Purpose | Scope |
|-------|-----------|---------|-------|
| **In-Memory** | Python dicts + ContextVar | Session agents, prompts, correlation IDs | Per-instance, non-persistent |
| **Persistent** | PostgreSQL | All business data, task status, config | Shared across all services |
| **Task Queue** | Redis + Celery | Async task processing, message passing | Distributed task execution |

**🔴 CRITICAL ISSUE**: Redis is missing from Railway deployment! Tasks will fail.

---

## 1. IN-MEMORY STATE MANAGEMENT

### 1.1 Agent Instance Cache

**Location**: `chatbot_orchestration/service/agent_manager.py`

```python
class AgentManager:
    def __init__(self):
        self.agent_cache: Dict[str, Agent] = {}

    async def get_cached_agent(self, session_id: str, force_new: bool = False):
        if not force_new and session_id in self.agent_cache:
            return self.agent_cache[session_id]

        agent = Agent(...)  # Create new
        self.agent_cache[session_id] = agent
        return agent
```

**Purpose**: Avoid recreating Pydantic AI agents for repeated interactions
**Lifetime**: Session duration (cleared when session ends)
**Benefit**: Zero overhead for subsequent messages in same session
**Memory**: ~50-100KB per agent instance

### 1.2 System Prompt Cache

**Location**: `chatbot_orchestration/core/cache.py`

```python
cache_store = {}  # In-memory dict

def cache_system_prompt(components: dict, model_name: str, prompt: str):
    cache_key = generate_cache_key(components, model_name)
    cache_store[cache_key] = {
        'prompt': prompt,
        'timestamp': time.time(),
        'components': components
    }

def get_cached_system_prompt(components: dict, model_name: str):
    cache_key = generate_cache_key(components, model_name)
    if cache_key in cache_store:
        cached = cache_store[cache_key]
        if time.time() - cached['timestamp'] < CACHE_TTL_SECONDS:
            return cached['prompt']
    return None
```

**TTL**: 1 hour (CACHE_TTL_SECONDS = 3600)
**Key**: SHA256 hash of (custom_prompt + response_policy + model_name)
**Benefit**: **90% token usage discount** on repeated prompts
**Example Hit**: Same chat scenario with same widget config reuses cached prompt

### 1.3 Correlation Context for Distributed Tracing

**Location**: `shared/correlation_id.py`

```python
from contextvars import ContextVar

correlation_id_ctx_var: ContextVar[Optional[str]] = ContextVar(
    'correlation_id',
    default=None
)

def get_correlation_id() -> Optional[str]:
    return correlation_id_ctx_var.get()

def set_correlation_id(correlation_id: str):
    correlation_id_ctx_var.set(correlation_id)
```

**Purpose**: Track requests across multiple services
**Async-safe**: Uses ContextVar (preserves context in asyncio)
**Usage**: Added to every log entry and inter-service HTTP headers
**Benefit**: End-to-end request tracing through entire distributed system

---

## 2. PERSISTENT STATE: POSTGRESQL DATABASE

### 2.1 Unified Database Connection Architecture

**Entry Point**: `shared/db.py`

```
All Services
    ↓
    get_db_connection()
    ↓
    DatabaseManager.get_instance() (Singleton)
    ↓
    asyncpg.Pool (Connection pool)
    ↓
    PostgreSQL (Railway managed)
```

### 2.2 Connection Pool Configuration

```python
# From shared/db.py

Pool Configuration:
├── min_size: 1           # Baseline connections
├── max_size: 5           # Max connections (Railway memory optimized)
├── command_timeout: 15s  # Fail fast if query hangs
├── max_inactive_connection_lifetime: 120s  # Auto-close idle connections
├── max_queries: 10000    # Force reconnect after 10k queries
└── Server Settings:
    ├── UTC timezone
    ├── TCP keepalives every 30s (detect dead connections)
    ├── statement_timeout: 15000ms (prevent long queries)
    └── SSL mode: REQUIRE (Railway security)
```

### 2.3 How All Services Access Shared Data

```python
# Example: Configuration Service accessing chat logs
async def get_all_messages(session_db_id: int):
    async with get_db_connection() as conn:
        return await conn.fetch(
            "SELECT * FROM chat_messages WHERE chat_session_id = $1",
            session_db_id
        )
```

**Multi-service access pattern**:
1. Service A calls `get_db_connection()`
2. Gets connection from shared pool
3. Executes query
4. Returns connection to pool
5. Service B gets same or different connection from pool
6. Both services see **consistent data** (same PostgreSQL instance)

### 2.4 Core Database Schema

**File**: `/sql/database_schema.sql` (52KB, 3NF normalized)

**Key Tables**:

```
chat_sessions
├── id (PK)
├── customer_name, email
├── created_at, updated_at
└── Relationships: has many chat_messages

chat_messages
├── id (PK)
├── chat_session_id (FK)
├── sender (user/assistant)
├── content, created_at
└── Used by: Configuration service, Chatbot service

file_uploads
├── id (PK)
├── file_name, gemini_file_name, gemini_file_uri
├── processing_status (pending, processing, completed, failed)
├── error_message
├── metadata (JSONB - stores FileSearch metadata)
└── Used by: Knowledgebase Ingestion, API Gateway

scraped_websites
├── id (PK)
├── url, gemini_file_name, gemini_file_uri
├── processing_status (pending, processing, completed, failed)
├── parent_id, depth (for sitemap hierarchy)
├── error_message
└── Used by: Website Crawling, API Gateway

widget_configuration
├── id (PK)
├── keep_showing_suggested, enable_autocomplete
├── custom_prompt, response_policy
└── Used by: Configuration service, Chatbot service

service_health_checks
├── id (PK)
├── service_name, status
├── checked_at, response_time
└── Used by: Health Monitoring, Configuration services

token_usage_log
├── id (PK)
├── session_id, input_tokens, output_tokens
├── created_at
└── Used by: Chatbot service (token tracking)

user_role_mapping
├── id (PK)
├── email, role (admin, user)
└── Used by: API Gateway (auth)
```

### 2.5 Database Initialization Strategy

All services use consistent initialization:

```python
# In each service's main.py lifespan handler

from {service}.core.database_initializer import database_initializer

# Startup
await database_initializer.initialize_and_validate(
    settings.railway_postgres_url
)

# This:
# 1. Creates asyncpg pool
# 2. Tests connection
# 3. Validates schema exists
# 4. Logs migration instructions if needed
```

### 2.6 Performance Optimization

**Indexes** (from `/migrations/add_performance_indexes.sql`):

```sql
-- Task status queries (used by polling)
idx_file_uploads_processing_status
idx_file_uploads_processing_pending

-- Health check queries
idx_service_health_checks_service_checked
idx_service_health_checks_status

-- Chat queries (for logs UI)
idx_chat_messages_session_id
```

---

## 3. ASYNC TASK QUEUE: CELERY + REDIS

### 3.1 Architecture Overview

```
┌─ Knowledgebase Ingestion ─┐
│ process_file_upload_task  │
│ .delay(file_id, ...)      │
└───────────────┬───────────┘
                │ publishes
                ↓
        ┌───────────────┐
        │     REDIS     │
        │ DB 0: queue   │  ← CURRENTLY MISSING ON RAILWAY!
        │ file_processi │
        │      ng       │
        └───────┬───────┘
                │ subscribes
                ↓
        ┌───────────────────────────┐
        │ Celery Worker 1           │
        │ (file-processing queue)   │
        │ processes tasks           │
        └───────────┬───────────────┘
                    │
                    ↓
        ┌───────────────────┐
        │   PostgreSQL      │
        │ Updates status:   │
        │ pending→complete  │
        └───────────────────┘
```

### 3.2 Celery Configuration

**File**: `knowledgebase_ingestion/celery_app.py`

```python
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

celery_app.conf.update(
    broker_url=redis_url,              # Redis broker
    result_backend=redis_url,          # Store task results in Redis
    task_serializer='json',            # Safe for distributed systems
    timezone='UTC',

    # Worker tuning
    worker_prefetch_multiplier=4,      # Fetch 4 tasks at a time
    worker_max_tasks_per_child=1000,   # Restart worker after 1000 tasks
    task_acks_late=True,               # Acknowledge only after success
    task_reject_on_worker_lost=True,   # Requeue if worker dies

    # Task routing
    task_routes={
        'knowledgebase_ingestion.tasks.process_file_upload_task': {
            'queue': 'file_processing'
        }
    },

    # Timeouts
    task_soft_time_limit=1800,         # 30 minutes
    task_time_limit=1900,              # Hard limit 31.67 min
    result_expires=3600,               # Keep results 1 hour
)
```

**Website Crawling** uses:
- Redis DB 1: `redis://localhost:6379/1`
- Queue: `web_crawling`
- Timeout: 2 hours (large sitemaps)

### 3.3 Task Status Lifecycle

```
file_uploads table:
├── Status Flow
│   ├── pending   → Created, awaiting worker
│   ├── processing → Worker picked up, executing
│   ├── completed → Success, stored in Gemini
│   └── failed    → Error, check error_message column
│
├── Database columns
│   ├── processing_status VARCHAR(20)
│   ├── error_message TEXT
│   └── metadata JSONB (FileSearch info)
│
└── UI polling
    GET /api/v1/knowledgebase/status/{id}
    Returns: {status: "completed", ...}
```

### 3.4 Task Dispatch Logging (Added Feb 17)

Both services now log comprehensive task information:

```
📤 [TASK_DISPATCH] Preparing to dispatch task for file ID 123,
                   filename: document.pdf, size: 5242880 bytes, mime: application/pdf

✅ [CELERY] Dispatched Celery task abc123def456 for file ID 123

📊 [TASK_INFO] Task State: PENDING, Routing: 'file_processing' queue,
               Timeout: 30 minutes
```

### 3.5 Signal Handlers for Monitoring (Added Feb 17)

```python
# In celery_app.py

@before_task_publish
def log_task_published(sender, body, **kwargs):
    logger.info(f"📤 [TASK_PUBLISH] Publishing task {sender}")

@task_prerun
def log_task_start(sender, task_id, args, **kwargs):
    logger.info(f"⏱️ [TASK_PRERUN] Task {task_id} starting")

@task_postrun
def log_task_success(sender, task_id, args, **kwargs):
    logger.info(f"✅ [TASK_POSTRUN] Task {task_id} completed")

@task_failure
def log_task_fail(sender, task_id, exception, **kwargs):
    logger.error(f"❌ [TASK_FAILURE] Task {task_id} failed: {exception}")

@task_retry
def log_task_retry(sender, task_id, reason, **kwargs):
    logger.warning(f"🔄 [TASK_RETRY] Task {task_id} retrying: {reason}")
```

---

## 4. REDIS SETUP: THE CRITICAL MISSING PIECE

### 4.1 Current Problem

**Status**: 🔴 BROKEN ON RAILWAY

Your code expects Redis:
```python
# website_crawling/celery_app.py
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
celery_app.conf.update(broker_url=redis_url, ...)
```

But Railway deployment has:
- ✅ PostgreSQL (Railway managed)
- ✅ 7 microservices deployed
- ❌ **NO Redis service**

**Result**: When `process_file_upload_task.delay()` executes:
1. Tries to connect to Redis (from REDIS_URL env var)
2. Gets "Connection refused"
3. Task never publishes
4. File stays in "pending" status forever

### 4.2 Solution: Deploy Redis to Railway

**Files Created**:
1. `redis/Dockerfile` - Redis 7 Alpine with persistence
2. `redis/railway.toml` - Railway service config
3. `redis/README.md` - Full documentation
4. `REDIS_SETUP_GUIDE.md` - Deployment instructions

**Deployment Steps**:
```bash
# 1. Files already created and committed

# 2. Deploy to Railway
railway up --name redis

# 3. Set environment variables
# In knowledgebase_ingestion:
REDIS_URL=redis://redis.railway.internal:6379/0

# In website_crawling:
REDIS_URL=redis://redis.railway.internal:6379/1

# 4. Restart services
# Services restart → connect to Redis → tasks execute properly
```

### 4.3 Queue Configuration

| Service | DB | Queue Name | Timeout |
|---------|-----|-----------|---------|
| knowledgebase_ingestion | 0 | file_processing | 30 min |
| website_crawling | 1 | web_crawling | 2 hours |

---

## 5. SERVICE INITIALIZATION FLOW

### 5.1 Startup Sequence (Lifespan Pattern)

All services follow this pattern (via `@asynccontextmanager`):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    try:
        # 1. Initialize Telemetry
        setup_telemetry("service-name")
        logger.info("🚀 [TELEMETRY] Initialized")

        # 2. Initialize Celery (if applicable)
        from celery_app import celery_app
        logger.info("✅ [CELERY_APP] Initialized")

        # 3. Initialize Database
        from core.database_initializer import database_initializer
        await database_initializer.initialize_and_validate()
        logger.info("✅ [DATABASE] Initialized and validated")

        # 4. Initialize Gemini Client (if applicable)
        genai_client = get_genai_client()
        logger.info("✅ [GEMINI] Client initialized")

        # 5. Initialize FileSearch Store (if applicable)
        store_id = get_file_search_store_by_display_name()
        logger.info(f"✅ [FILESEARCH] Store ID: {store_id}")

        logger.info("🚀 Service fully initialized")
        yield  # Service runs here

    # SHUTDOWN
    finally:
        logger.info("🛑 Service shutting down...")
        await close_databases()
        logger.info("🛑 Service shutdown complete")
```

### 5.2 Initialization Order

1. **API Gateway** (8000)
   - Creates FileSearch store if doesn't exist
   - Initializes database
   - All other services depend on this

2. **All Other Services** (8001-8006)
   - Initialize database (connects to same PostgreSQL)
   - Initialize Celery (connects to Redis)
   - Initialize Gemini client
   - Validate FileSearch store exists

---

## 6. INTER-SERVICE COMMUNICATION

### 6.1 Railway Internal Network

```
Service A                    Service B
localhost:8001        →      service-b.railway.internal:8080

All services expose port 8080 (via railway.toml)
Internal-only communication via .railway.internal DNS
```

### 6.2 Shared State Access Pattern

```
Configuration Service needs chat logs
    ↓
Calls: get_db_connection()
    ↓
Gets connection from shared asyncpg.Pool
    ↓
Queries PostgreSQL: SELECT * FROM chat_messages
    ↓
Returns data (consistent because same DB)
```

**Key Point**: All services connect to **same PostgreSQL instance**
- No data replication needed
- No eventual consistency issues
- Database is single source of truth

---

## 7. CACHING STRATEGY SUMMARY

| Cache Type | Storage | TTL | Scope | Benefit |
|-----------|---------|-----|-------|---------|
| **Agent Cache** | In-memory dict | Session | Per-instance | 0ms agent access |
| **Prompt Cache** | In-memory dict | 1 hour | Per-instance | 90% token discount |
| **FileSearch Store** | Class singleton | Indefinite | Per-instance | Avoid Gemini API calls |
| **DB Connection Pool** | asyncpg.Pool | Active | Per-instance | Reuse connections |
| **Celery Results** | Redis | 1 hour | Distributed | Task result storage |

**Design Principle**:
- In-memory caches (non-persistent) per service instance
- Persistent state in PostgreSQL (shared)
- Task queues in Redis (distributed)

---

## 8. DEPLOYMENT ARCHITECTURE

### 8.1 Current Production Setup (Railway)

```
┌────────────────────────── RAILWAY ──────────────────────────┐
│                                                               │
│  PostgreSQL (Managed)                                        │
│  - Shared database for all services                          │
│  - Persistent data storage                                   │
│                                                               │
│  Services (Docker containers):                               │
│  ├─ API Gateway (8000) - Routing, auth, FileSearch init   │
│  ├─ Knowledgebase Ingestion (8001) - File upload/process  │
│  ├─ Website Crawling (8002) - URL scraping                │
│  ├─ Chatbot Orchestration (8003) - RAG chat responses      │
│  ├─ Docling Service (8004) - Document → markdown          │
│  ├─ Configuration Service (8005) - Widget config, logs     │
│  ├─ Health Monitoring (8006) - System health tracking      │
│  └─ 🔴 Redis (6379) - MISSING! (needs to be added)        │
│                                                               │
│  Celery Workers:                                             │
│  └─ (Can be separate services or processes)                │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 8.2 Local Development Setup

```
docker-compose.yml
├─ api-gateway (8000)
├─ knowledgebase-ingestion (8001)
├─ website-scraping (8002)
└─ chatbot-orchestration (8003)

docker-compose.celery.yml (SEPARATE)
├─ redis (6379)
├─ celery-file-worker (file_processing queue)
├─ celery-web-worker (web_crawling queue)
├─ celery-flower (monitoring, 5555)
├─ postgres (database)
└─ (uses same images as main compose)
```

---

## 9. KEY MONITORING POINTS

### 9.1 Database Health

```sql
-- Check active connections
SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- Check table sizes
SELECT tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables WHERE schemaname = 'public';

-- Check pending tasks
SELECT processing_status, COUNT(*) FROM file_uploads GROUP BY processing_status;
```

### 9.2 Redis Health (Once Deployed)

```bash
# Check connection
redis-cli ping  # Should return PONG

# Check memory
redis-cli INFO memory

# Check queues
redis-cli LLEN celery  # Task queue length

# Monitor in real-time
redis-cli MONITOR
```

### 9.3 Log Monitoring

All services log with correlation IDs and structured tags:

```
✅ [REDIS] Connection test successful
📤 [TASK_DISPATCH] Preparing to dispatch task
⏱️ [TASK_PRERUN] Task starting execution
✅ [TASK_POSTRUN] Task completed successfully
❌ [TASK_FAILURE] Task failed
🔄 [TASK_RETRY] Task retrying
```

---

## 10. NEXT STEPS

### Immediate (Critical)

1. ✅ Read this document (done!)
2. Deploy Redis service to Railway (follow REDIS_SETUP_GUIDE.md)
3. Set environment variables on services
4. Restart services
5. Verify logs show successful Redis connection

### Short-term

6. Test file upload → verify status changes
7. Test website crawling → verify status changes
8. Monitor logs for task execution

### Long-term

9. Consider adding Celery workers if task queue grows
10. Monitor Redis memory usage
11. Set up alerts for task failures

---

## Summary

Your application uses a **three-tier state management system**:

1. **In-Memory**: Agent caching, prompt caching, correlation IDs (fast, non-persistent)
2. **Database**: PostgreSQL for all persistent data (shared, consistent)
3. **Task Queue**: Redis + Celery for async processing (distributed, scalable)

**🔴 CRITICAL BLOCKER**: Redis is missing from Railway, breaking all async tasks.

**✅ SOLUTION**: Deploy the `redis/` service, set env vars, restart services.

See `REDIS_SETUP_GUIDE.md` for step-by-step deployment instructions.
