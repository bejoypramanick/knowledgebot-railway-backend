# Environment Variables Configuration Guide

This document lists all required and optional environment variables for the dAIlogue system.

## 🔴 CRITICAL - Required for All Services

### Database
```bash
DATABASE_URL=postgresql://user:password@host:port/database
```
- **Required by**: All services
- **Description**: PostgreSQL database connection string
- **Example**: `postgresql://postgres:password@postgres.railway.internal:5432/railway`

### Redis (Main Instance)
```bash
REDIS_URL=redis://default:password@host:port/0
```
- **Required by**: All services
- **Description**: Main Redis instance for Celery, sessions, and Pub/Sub
- **Note**: The system uses different databases (0-4) for different purposes:
  - DB 0: Celery file processing tasks
  - DB 1: Celery web crawling tasks
  - DB 2: Docling document conversion
  - DB 3: Session storage
  - DB 4: Agent SSE Pub/Sub events

### Firebase Authentication
```bash
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}
```
- **Required by**: API Gateway
- **Description**: Firebase Admin SDK credentials for authentication
- **Note**: FIREBASE_CREDENTIALS_JSON should be the entire service account JSON as a string

### Gemini AI
```bash
GEMINI_API_KEY=your-gemini-api-key
GEMINI_FILE_SEARCH_STORE_NAME=knowledgebot-search-store
```
- **Required by**: Chatbot Orchestration, Knowledge Base Ingestion, Celery Workers
- **Description**: Google Gemini API key and file search store name

---

## 🟡 Service-Specific Redis URLs

### File Processing Worker
```bash
FILE_REDIS_URL=redis://default:password@host:port/0
```
- **Required by**: Celery File Worker
- **Description**: Redis DB 0 for file processing tasks
- **Default**: Falls back to REDIS_URL with /0

### Web Crawling Worker
```bash
WEB_REDIS_URL=redis://default:password@host:port/1
```
- **Required by**: Celery Web Worker
- **Description**: Redis DB 1 for web crawling tasks
- **Default**: Falls back to REDIS_URL with /1

### Docling Document Conversion
```bash
DOCLING_SERVE_ENG_RQ_REDIS_URL=redis://default:password@host:port/2
```
- **Required by**: Docling Worker (if enabled)
- **Description**: Redis DB 2 for Docling RQ queue
- **Note**: Only needed if DOCLING_ENABLED=true

---

## 🟢 Optional Configuration

### Railway Storage (S3-compatible)
```bash
RAILWAY_BUCKET_NAME=your-bucket-name
RAILWAY_REGION=us-west-1
RAILWAY_STORAGE_URL=https://s3.us-west-1.amazonaws.com
RAILWAY_STORAGE_ACCESS_KEY=your-access-key
RAILWAY_STORAGE_SECRET_KEY=your-secret-key
```
- **Required by**: Widget Configuration (for image uploads)
- **Description**: S3-compatible storage for uploaded images
- **Note**: Only needed if using widget image upload feature

### Service URLs (Internal Communication)
```bash
KNOWLEDGEBASE_INGESTION_URL=http://knowledge-base.railway.internal:8080
CHATBOT_ORCHESTRATION_URL=http://chatbot.railway.internal:8080
CONFIGURATION_SERVICE_URL=http://configuration.railway.internal:8080
```
- **Required by**: API Gateway, Services
- **Description**: Internal Railway URLs for service-to-service communication
- **Default**: Uses Railway internal DNS

### Port Configuration
```bash
PORT=8080
API_GATEWAY_PORT=8080
CONFIGURATION_PORT=8080
CHATBOT_ORCH_PORT=8080
KB_INGESTION_PORT=8080
HEALTH_MONITORING_PORT=8080
```
- **Description**: Service-specific ports
- **Default**: Railway sets PORT automatically, service-specific ports fall back to PORT

### Database Connection Pool
```bash
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=3
DB_POOL_RECYCLE=3600
DB_STATEMENT_TIMEOUT=60000
DB_CONNECT_TIMEOUT=10
DB_COMMAND_TIMEOUT=20
```
- **Description**: PostgreSQL connection pool settings
- **Default**: Shown above

### Celery Worker Concurrency
```bash
CELERY_FILE_CONCURRENCY=10
CELERY_WEB_CONCURRENCY=10
```
- **Description**: Number of concurrent workers for Celery
- **Default**: 10 for gevent pool

### File Upload Constraints
```bash
MAX_FILE_SIZE_MB=100
ALLOWED_FILE_EXTENSIONS=pdf,docx,txt,md,html
```
- **Description**: File upload limits
- **Default**: 100MB, common document types

### Docling Configuration
```bash
DOCLING_ENABLED=true
DOCLING_TIMEOUT_SECONDS=1800
DOCLING_RQ_QUEUE_NAME=convert
DOCLING_RQ_JOB_TIMEOUT_MINUTES=60
DOCLING_POLL_INITIAL_DELAY=2
DOCLING_POLL_MAX_INTERVAL=30
```
- **Description**: Docling document conversion settings
- **Default**: Shown above

### Logging
```bash
LOG_LEVEL=INFO
RAILWAY_ENVIRONMENT=production
RAILWAY_SERVICE_NAME=api-gateway
RAILWAY_PROJECT_NAME=dailogue
```
- **Description**: Logging configuration
- **Default**: INFO level, Railway sets environment variables automatically

---

## 📋 Quick Setup Checklist

### Minimum Required (to get started):
- [ ] `DATABASE_URL` - PostgreSQL connection
- [ ] `REDIS_URL` - Redis connection (will auto-configure DBs 0-4)
- [ ] `FIREBASE_PROJECT_ID` - Firebase project ID
- [ ] `FIREBASE_CREDENTIALS_JSON` - Firebase service account JSON
- [ ] `GEMINI_API_KEY` - Google Gemini API key

### Recommended (for full functionality):
- [ ] `FILE_REDIS_URL` - Explicit Redis DB 0 for file tasks
- [ ] `WEB_REDIS_URL` - Explicit Redis DB 1 for web tasks
- [ ] `GEMINI_FILE_SEARCH_STORE_NAME` - File search store name
- [ ] `RAILWAY_BUCKET_NAME` - S3 bucket for image uploads
- [ ] `RAILWAY_STORAGE_ACCESS_KEY` - S3 access key
- [ ] `RAILWAY_STORAGE_SECRET_KEY` - S3 secret key

### Optional (for advanced features):
- [ ] `DOCLING_SERVE_ENG_RQ_REDIS_URL` - Docling Redis DB 2
- [ ] `DOCLING_ENABLED` - Enable Docling conversion
- [ ] Service-specific URLs (if not using Railway internal DNS)
- [ ] Custom port configurations
- [ ] Database pool settings
- [ ] File upload constraints

---

## 🚨 Common Issues

### Issue: "REDIS_URL environment variable not set"
**Solution**: Set `REDIS_URL` in Railway dashboard for all services

### Issue: "No sessions visible in chat log"
**Possible causes**:
1. Database not connected - check `DATABASE_URL`
2. No sessions created yet - test chatbot widget first
3. Authentication issue - check Firebase credentials
4. Redis not connected - check `REDIS_URL`

### Issue: "Session storage requires Redis"
**Solution**: Set `REDIS_URL` in API Gateway service

### Issue: "Celery tasks not processing"
**Solution**: 
- Set `FILE_REDIS_URL` for file worker
- Set `WEB_REDIS_URL` for web worker
- Ensure workers are running

### Issue: "Widget images not uploading"
**Solution**: Configure Railway Storage environment variables:
- `RAILWAY_BUCKET_NAME`
- `RAILWAY_STORAGE_ACCESS_KEY`
- `RAILWAY_STORAGE_SECRET_KEY`
- `RAILWAY_STORAGE_URL`
- `RAILWAY_REGION`

---

## 🔧 Railway Setup Instructions

### 1. Add Redis Database
1. Go to Railway dashboard
2. Click "New" → "Database" → "Add Redis"
3. Copy the `REDIS_URL` from Redis service variables
4. Add `REDIS_URL` to all services that need it

### 2. Add PostgreSQL Database
1. Go to Railway dashboard
2. Click "New" → "Database" → "Add PostgreSQL"
3. Copy the `DATABASE_URL` from PostgreSQL service variables
4. Add `DATABASE_URL` to all services

### 3. Configure Firebase
1. Go to Firebase Console → Project Settings → Service Accounts
2. Generate new private key (downloads JSON file)
3. Copy the entire JSON content
4. Add to Railway as `FIREBASE_CREDENTIALS_JSON`
5. Add `FIREBASE_PROJECT_ID` from the JSON

### 4. Configure Gemini
1. Get API key from Google AI Studio
2. Add as `GEMINI_API_KEY` to all services
3. Set `GEMINI_FILE_SEARCH_STORE_NAME` (optional, defaults to "knowledgebot-search-store")

### 5. Configure Railway Storage (Optional)
1. Go to Railway dashboard → Storage
2. Create new bucket or use existing
3. Copy credentials and add to services

---

## 📝 Notes

- Railway automatically sets `PORT` for each service
- Railway internal DNS works automatically (e.g., `postgres.railway.internal`)
- Redis databases 0-4 are automatically configured from `REDIS_URL`
- Service-specific Redis URLs (`FILE_REDIS_URL`, `WEB_REDIS_URL`) are optional but recommended for clarity
- All services share the same PostgreSQL database
- All services share the same Redis instance (different databases)

---

## 🔍 Debugging

To check if environment variables are set correctly:

```bash
# In Railway service logs, look for:
# - "✅ Redis connected" or "❌ REDIS_URL not set"
# - "✅ Database connected" or "❌ DATABASE_URL not set"
# - "✅ Firebase initialized" or "❌ Firebase credentials not found"
```

Check the `/health` endpoint of each service to verify configuration.
