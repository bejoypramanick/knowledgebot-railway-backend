# Railway Environment Variables Configuration Guide

This document outlines all environment variables needed for each microservice on Railway, updated for the 7-migration library refactoring.

---

## Redis Configuration Model

Redis now uses a single base URL plus purpose-specific DB number variables.
The old per-purpose full Redis URLs are removed.

```bash
REDIS_URL=redis://default:password@redis.railway.internal:6379

FILE_TASK_QUEUE_REDIS_DB=0
WEB_TASK_QUEUE_REDIS_DB=1
SESSION_STORE_REDIS_DB=2
AGENT_EVENTS_REDIS_DB=3
AGENT_ASSIGNMENT_CACHE_REDIS_DB=4
WIDGET_ACCESS_CACHE_REDIS_DB=4
CITATION_CACHE_REDIS_DB=4
CHAT_STORE_REDIS_DB=6
UI_DATA_CACHE_REDIS_DB=7
TENANT_AUTH_CACHE_REDIS_DB=8
```

Use env var names based on purpose in the code:
- `SESSION_STORE_REDIS_DB` for login/session cookies in the API gateway
- `AGENT_EVENTS_REDIS_DB` for SSE/pubsub events
- `FILE_TASK_QUEUE_REDIS_DB` for file worker queues
- `WEB_TASK_QUEUE_REDIS_DB` for web crawl worker queues
- `AGENT_ASSIGNMENT_CACHE_REDIS_DB` for agent assignment cache
- `WIDGET_ACCESS_CACHE_REDIS_DB` for widget availability/origin cache
- `CITATION_CACHE_REDIS_DB` for citation lookup cache
- `CHAT_STORE_REDIS_DB` for hot chat transcript storage
- `UI_DATA_CACHE_REDIS_DB` for UI screen cache
- `TENANT_AUTH_CACHE_REDIS_DB` for tenant auth/profile cache

---

## 📋 Common Variables (All Services)

These variables should be set for ALL services:

### Database
```
DATABASE_URL=postgresql://user:password@localhost:5432/knowledgebot
# OR (preferred for Railway)
RAILWAY_POSTGRES_URL=postgresql://user:password@railway.internal:5432/knowledgebot
```

### Logging & OpenTelemetry
```
LOG_LEVEL=INFO
# Set to true to export OTel spans (disabled by default on Railway)
OTEL_SPAN_EXPORTER_ENABLED=false

# Shared Redis base URL
REDIS_URL=redis://default:password@redis.railway.internal:6379
```

### API Keys
```
GEMINI_API_KEY=your-gemini-api-key-here
# Required for OpenAI embeddings
OPENAI_API_KEY=your-openai-api-key-here
```

### Default Server Config
```
API_GATEWAY_PORT=8000
API_GATEWAY_HOST=0.0.0.0
```

---

## 🌐 Service-Specific Configuration

### **API Gateway** (`api_gateway/`)

**Purpose:** Authentication, routing, rate limiting, session management

**Environment Variables:**

```bash
# Database (required)
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Redis Session Storage (required)
REDIS_URL=redis://default:password@redis.railway.internal:6379
SESSION_STORE_REDIS_DB=2

# Service URLs (for proxying)
CONFIGURATION_SERVICE_URL=http://configuration.railway.internal:8080
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration.railway.internal:8080
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080
ADMIN_SERVICE_URL=http://localhost:8000

# API Keys
GEMINI_API_KEY=your-gemini-key

# Firebase (optional - if using Firebase auth)
FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-key.json

# Rate Limiting (hardcoded in code, but can be monitored)
# /chatbot/chat/stream: 50 requests/minute
# /chatbot/validate-chat: 100 requests/minute
# /auth/verify: 100 requests/minute

# Server Config
API_GATEWAY_PORT=8000
API_GATEWAY_HOST=0.0.0.0
```

**New in Migrations:**
- Uses `structlog>=24.4.0` (added to requirements)
- Uses `slowapi>=0.1.8` for rate limiting (added to requirements)
- Redis factory uses standard Redis client initialization

---

### **Chatbot Orchestration** (`chatbot_orchestration/`)

**Purpose:** AI agent orchestration, RAG, chat streaming

**Environment Variables:**

```bash
# Database
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Redis (required for SSE events and caches)
REDIS_URL=redis://default:password@redis.railway.internal:6379
AGENT_EVENTS_REDIS_DB=3
CHAT_STORE_REDIS_DB=6
AGENT_ASSIGNMENT_CACHE_REDIS_DB=4
CITATION_CACHE_REDIS_DB=4

# Service URLs
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080
WEBSITE_CRAWLING_URL=http://web-crawling.railway.internal:8080

# AI Models
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key
CHATBOT_MODEL=gemini-2.5-flash-lite
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_PROVIDER=openai

# RAG Configuration
ENABLE_CITATIONS=true
ENABLE_RERANKING=false
ENABLE_CONTEXT_COMPRESSION=false
ENABLE_SEMANTIC_CACHING=true

# Server Config
API_GATEWAY_PORT=8000
API_GATEWAY_HOST=0.0.0.0
```

**New in Migrations:**
- Uses `structlog>=24.4.0` for logging
- Uses `slowapi>=0.1.8` for endpoint rate limiting
- Uses `tenacity>=8.2.2` for retry logic (already in requirements)

---

### **Celery File Worker** (`celery-file-worker/`)

**Purpose:** Async file processing (uploads, docling conversion, table extraction)

**Environment Variables:**

```bash
# Database
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Redis (required - Celery broker + task queues)
REDIS_URL=redis://default:password@redis.railway.internal:6379
FILE_TASK_QUEUE_REDIS_DB=0

# Storage (S3-compatible, Railway Volumes)
RAILWAY_BUCKET_NAME=knowledgebot-files
RAILWAY_REGION=us-east-1
RAILWAY_STORAGE_URL=https://s3.railway.internal
RAILWAY_STORAGE_ACCESS_KEY=your-s3-access-key
RAILWAY_STORAGE_SECRET_KEY=your-s3-secret-key
RAILWAY_VOLUME_NAME=/app/data

# AI/Processing
GEMINI_API_KEY=your-gemini-key
CHATBOT_MODEL=gemini-2.5-flash-lite

# Kreuzberg Integration (optional)
KREUZBERG_ENABLED=true
KREUZBERG_API_URL=http://kreuzberg.railway.internal:8000

# Processing Configuration
CHONKIE_CHUNK_SIZE=1024
CHONKIE_CHUNK_OVERLAP=100
CHONKIE_THRESHOLD=0.5
CHONKIE_SKIP_WINDOW=5

# Logging
LOG_LEVEL=INFO
```

**New in Migrations:**
- Uses `structlog>=24.4.0` for logging
- Uses `tenacity>=8.2.2` for database retry (already in requirements)
- Inline retry logic now uses Tenacity decorators

---

### **Celery Web Worker** (`celery-web-worker/`)

**Purpose:** Async web scraping (crawl4ai + docling + table extraction)

**Environment Variables:**

```bash
# Database
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Redis (required - Celery broker)
REDIS_URL=redis://default:password@redis.railway.internal:6379
WEB_TASK_QUEUE_REDIS_DB=1

# Storage (S3-compatible)
RAILWAY_BUCKET_NAME=knowledgebot-files
RAILWAY_REGION=us-east-1
RAILWAY_STORAGE_URL=https://s3.railway.internal
RAILWAY_STORAGE_ACCESS_KEY=your-s3-access-key
RAILWAY_STORAGE_SECRET_KEY=your-s3-secret-key

# AI/Processing
GEMINI_API_KEY=your-gemini-key
CHATBOT_MODEL=gemini-2.5-flash-lite

# Kreuzberg Integration
KREUZBERG_ENABLED=true
KREUZBERG_API_URL=http://kreuzberg.railway.internal:8000

# Service URLs
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080

# Logging
LOG_LEVEL=INFO
```

**New in Migrations:**
- Uses `structlog>=24.4.0` for logging
- Unified docling processing (same as file-worker)

---

### **Knowledgebase Ingestion** (`knowledgebase_ingestion/`)

**Purpose:** Knowledge base indexing, RAG document management

**Environment Variables:**

```bash
# Database
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Storage (S3-compatible)
RAILWAY_BUCKET_NAME=knowledgebot-files
RAILWAY_REGION=us-east-1
RAILWAY_STORAGE_URL=https://s3.railway.internal
RAILWAY_STORAGE_ACCESS_KEY=your-s3-access-key
RAILWAY_STORAGE_SECRET_KEY=your-s3-secret-key

# Service URLs
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080
WEBSITE_CRAWLING_URL=http://web-crawling.railway.internal:8080
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration.railway.internal:8080

# AI
GEMINI_API_KEY=your-gemini-key
CHATBOT_MODEL=gemini-2.5-flash-lite

# Logging
LOG_LEVEL=INFO
```

**New in Migrations:**
- Uses `structlog>=24.4.0` for logging
- Uses `tenacity>=8.2.2` for retry logic

---

### **Health Monitoring** (`health_monitoring/`)

**Purpose:** Service health checks, monitoring dashboard

**Environment Variables:**

```bash
# Database (optional - for storing metrics)
DATABASE_URL=postgresql://...
RAILWAY_POSTGRES_URL=postgresql://railway.internal:5432/...

# Service URLs to Monitor
API_GATEWAY_URL=http://api-gateway.railway.internal:8080
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration.railway.internal:8080
CONFIGURATION_SERVICE_URL=http://configuration.railway.internal:8080
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080
WEBSITE_CRAWLING_URL=http://web-crawling.railway.internal:8080
KREUZBERG_API_URL=http://kreuzberg.railway.internal:8000

# Health Check Configuration
HEALTH_MONITOR_ENABLED=true
HEALTH_CHECK_ENABLED=true
HEALTH_CHECK_INTERVAL_SECONDS=300
HEALTH_CHECK_TIMEOUT_SECONDS=10
HEALTH_MONITORING_PORT=8006

# Logging
LOG_LEVEL=INFO
```

**New in Migrations:**
- Uses `structlog>=24.4.0` for logging
- Uses `tenacity>=8.2.2` for retry logic

---

## 🔴 **Redis Database Allocation**

With Migration 1 (Redis Factory), the following Redis databases are used:

| DB | Purpose | Env Var | Service(s) |
|---|---------|---------|-----------|
| 0 | File Worker Celery Queue | `FILE_REDIS_URL` | celery-file-worker |
| 1 | Web Worker Celery Queue | `WEB_REDIS_URL` | celery-web-worker |
| 2 | Sessions | `SESSION_REDIS_URL` | api_gateway |
| 3 | Pub/Sub (SSE events) | `PUBSUB_REDIS_URL` | chatbot_orchestration, redis_pubsub_manager |
| 4 | Agent Cache + Widget Config | `AGENT_CACHE_REDIS_URL` | derived from PUBSUB_REDIS_URL with /4 suffix |
| 5 | Session UUID Cache | (internal) | derived from PUBSUB_REDIS_URL with /5 suffix |
| 6 | Chat Store | `CHAT_STORE_REDIS_URL` | redis_chat_store (derived from PUBSUB_REDIS_URL with /6 suffix) |
| 8 | Tenant Auth/Profile Cache | `TENANT_AUTH_CACHE_REDIS_URL` | shared auth/profile cache, derived from PUBSUB_REDIS_URL or SESSION_REDIS_URL with /8 suffix |

**Strategy:**
- Primary Redis URL: `PUBSUB_REDIS_URL=redis://default:password@redis.railway.internal:6379/3`
- Other databases (4, 5, 6, 8) are derived automatically by appending `/N` to base URL
- This reduces configuration complexity from 7 env vars to 3 main ones

---

## 📦 **New Dependencies (Post-Migration)**

All services should have these added to their `requirements.txt`:

```
# Logging (Migration 2)
structlog>=24.4.0

# Retry Logic (Migration 4) - Already present
tenacity>=8.2.2

# Rate Limiting (Migration 5) - API Gateway, Chatbot Orchestration
slowapi>=0.1.8
limits>=3.5.0

# Base Settings (Migration 6) - Implicit, no new dependency

# PII Detection (Migration 7) - OPTIONAL, commented out by default
# presidio-analyzer>=2.2.0
# presidio-anonymizer>=2.2.0
```

---

## ✅ **Verification Checklist**

Before deploying to Railway, verify:

- [ ] Database: Both `DATABASE_URL` and `RAILWAY_POSTGRES_URL` set (API Gateway prefers `RAILWAY_POSTGRES_URL`)
- [ ] Redis: `PUBSUB_REDIS_URL` is properly configured with `/3` suffix
- [ ] Service URLs: All `*_URL` vars point to correct Railway internal addresses (`.railway.internal`)
- [ ] API Keys: `GEMINI_API_KEY` is set and valid
- [ ] Storage: S3 credentials set (`RAILWAY_STORAGE_*`)
- [ ] Firebase: `FIREBASE_PROJECT_ID` and credentials set (if using auth)
- [ ] Ports: API services use port `8000` (or configured via `API_GATEWAY_PORT`)
- [ ] Logging: `LOG_LEVEL` set appropriately (default: `INFO`)

---

## 🚀 **Railway Deployment Notes**

### Service Staggering Order
Start services in this order to avoid cold-start timeouts:

1. **PostgreSQL** - Wait 30 seconds for DB to stabilize
2. **Redis** - Wait 10 seconds
3. **Configuration Service** - Let it warm up first
4. **API Gateway, Chatbot Orchestration** - Critical path
5. **Celery Workers** - File and Web workers
6. **Health Monitoring** - Last
7. **Kreuzberg** (if using) - Can start anytime after step 2

### Connection Pool Settings (Defaults)
```
DB_POOL_SIZE=3                    # Min connections (low for serverless)
DB_POOL_MAX_OVERFLOW=2            # Burst connections
DB_POOL_RECYCLE=3600              # Recycle stale connections
DB_CONNECT_TIMEOUT=60             # Cold-start resilience
DB_COMMAND_TIMEOUT=20             # Statement timeout
DB_SSL_MODE=auto                  # Auto-detect (disable for .railway.internal)
```

---

## 🔗 **Environment Variable Dependencies**

```
API_GATEWAY depends on:
  ├─ DATABASE_URL or RAILWAY_POSTGRES_URL
  ├─ SESSION_REDIS_URL
  ├─ CONFIGURATION_SERVICE_URL
  ├─ CHATBOT_ORCHESTRATION_URL
  ├─ FIREBASE_PROJECT_ID (if auth enabled)
  └─ GEMINI_API_KEY

CHATBOT_ORCHESTRATION depends on:
  ├─ DATABASE_URL or RAILWAY_POSTGRES_URL
  ├─ PUBSUB_REDIS_URL
  ├─ GEMINI_API_KEY
  └─ KNOWLEDGEBASE_INGESTION_URL

CELERY_FILE_WORKER depends on:
  ├─ DATABASE_URL or RAILWAY_POSTGRES_URL
  ├─ FILE_REDIS_URL
  ├─ RAILWAY_BUCKET_NAME
  ├─ GEMINI_API_KEY
  └─ KREUZBERG_ENABLED

...and so on for other services
```

---

## 📝 **Configuration Best Practices**

1. **Internal URLs:** Always use `.railway.internal` for service-to-service communication (faster, no SSL issues)
2. **Database Selection:** Prefer `RAILWAY_POSTGRES_URL` (internal) over `DATABASE_URL` (public)
3. **Redis Fallback:** DB 4, 5, 6 are auto-derived from `PUBSUB_REDIS_URL` - don't set separately
4. **Secrets Management:** Use Railway's secret management, not `.env` files
5. **Structlog:** No config needed (uses defaults), but logs are now JSON-formatted
6. **Rate Limiting:** Hardcoded in decorators, monitor 429 responses if needed

---

**Last Updated:** After 7-migration library refactoring
**Status:** ✅ All services compatible with new dependencies
