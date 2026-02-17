# Health Monitoring Service - Railway Setup Guide

## Current Status

The health monitoring service is deployed on Railway but has three critical issues preventing it from working:

### Issues Fixed ✅

1. **Metadata Type Mismatch** (FIXED in commit bf3f615)
   - Error: `invalid input for query argument $6: {'endpoint': '/health'} (expected str, got dict)`
   - Root Cause: metadata dict was passed directly to PostgreSQL asyncpg
   - Fix: Convert metadata dict to JSON string before insertion
   - Status: ✅ COMMITTED & AWAITING DEPLOYMENT

2. **Service URL Validation** (FIXED in commit 3594c20)
   - Error: "Request URL is missing an 'http://' or 'https://' protocol"
   - Root Cause: Service URL might be empty/None, causing invalid URL construction
   - Fix: Added validation to check if service URL is configured before making request
   - Status: ✅ COMMITTED & AWAITING DEPLOYMENT

3. **Configuration Service Database Schema Error** (FIXED in commit 3594c20)
   - Error: "column sa.assignee_type does not exist"
   - Root Cause: Query referenced non-existent column in session_assignments table
   - Fix: Updated query to join with user_role_mapping and roles tables correctly
   - Status: ✅ COMMITTED & AWAITING DEPLOYMENT

### Issues Remaining ❌

1. **DATABASE_URL Not Configured** (CRITICAL)
   - Error: "Database URL not configured - health checks will not be persisted"
   - Root Cause: Environment variable `DATABASE_URL` or `DATABASE_URL` not set in Railway
   - Impact: Health checks run every 5 minutes but are NOT stored in database
   - Fix: See Railway Setup Instructions below

---

## Railway Setup Instructions

### Step 1: Verify Service is Running

1. Go to https://railway.app → Select your project
2. Click on `health-monitoring-service`
3. Check "Deployments" tab to see if service is deployed
4. Check "Logs" tab to see startup messages

**Expected log output:**
```
🚀 Health Monitoring Service starting...
✅ Database initialized
✅ Health check scheduler started (interval: 300s)
✅ Health Monitoring Service started successfully
```

**Actual log output (currently):**
```
🚀 Health Monitoring Service starting...
⚠️ Database URL not configured - health checks will not be persisted
✅ Health check scheduler started (interval: 300s)
```

### Step 2: Configure DATABASE_URL Environment Variable

The health_monitoring service needs access to the PostgreSQL database to store health check records.

**Option A: Use Railway's Built-in PostgreSQL**

1. Go to Railway Dashboard → Your Project
2. Check if you have a PostgreSQL service already created
3. Click on the PostgreSQL service
4. Go to "Variables" tab
5. Copy the `DATABASE_URL` value
6. Go back to `health-monitoring-service`
7. Click "Variables" tab
8. Add new variable:
   - **Name:** `DATABASE_URL`
   - **Value:** Paste the PostgreSQL DATABASE_URL from step 5
9. Click "Deploy" to restart with new environment variable

**Option B: Use Environment Variable from PostgreSQL Service**

1. In your Railway project, you should have a PostgreSQL service connected
2. Go to health-monitoring-service → Variables
3. Add variable by clicking "Add Variable"
4. Instead of copying the URL, you can reference it directly:
   - **Name:** `DATABASE_URL`
   - **Value:** Use the reference to PostgreSQL's DATABASE_URL

### Step 3: Verify Database Connection

After adding the DATABASE_URL variable:

1. Click "Deploy" to apply changes
2. Go to "Logs" tab
3. Wait for deployment to complete
4. Check logs for this message:
   ```
   ✅ Database initialized
   ```

If you see this instead:
```
❌ Failed to create DB pool: ...
```

Then the DATABASE_URL is incorrect or the database is unreachable. Check:
- DATABASE_URL format is correct (should start with `postgresql://`)
- PostgreSQL service is running and accessible
- Firewall rules allow connection from health-monitoring service

### Step 4: Verify Health Checks Are Being Stored

1. After database is connected, wait for the first health check cycle (5 minutes)
2. Check logs for health check messages:
   ```
   🔍 Running health checks...
   ✅ api_gateway: healthy (45ms)
   ✅ configuration: healthy (52ms)
   ✅ chatbot_orchestration: healthy (38ms)
   ✅ knowledgebase_ingestion: healthy (41ms)
   ✅ website_crawling: healthy (48ms)
   ✅ docling_service: healthy (55ms)
   ✅ Health checks completed
   ```

3. Connect to the PostgreSQL database and verify records:
   ```sql
   SELECT COUNT(*) FROM service_health_checks;
   SELECT * FROM service_health_checks ORDER BY checked_at DESC LIMIT 10;
   ```

---

## Service Configuration

### Service URLs (Configured in config.py)

The health monitoring service monitors these services:

| Service | Default URL | Health Endpoint |
|---------|-------------|-----------------|
| API Gateway | `http://api-gateway.railway.internal:8080` | `/health` |
| Chatbot Orchestration | `http://chatbot-orchestration.railway.internal:8080` | `/health` |
| Configuration | `http://configuration.railway.internal:8080` | `/api/v1/configuration/health` |
| Knowledge Base | `http://knowledge-base.railway.internal:8080` | `/health` |
| Website Crawling | `http://web-crawling.railway.internal:8080` | `/health` |
| Docling Service | `http://docling.railway.internal:8080` | `/health` |

**Note:** These use Railway's internal service discovery (`.railway.internal` DNS). They should work automatically within Railway's network.

### Health Check Interval

- **Default:** 300 seconds (5 minutes)
- **Environment Variable:** `HEALTH_CHECK_INTERVAL_SECONDS`
- **Can be overridden in Railway Variables**

---

## API Endpoints

### Health Check Status

**GET** `/health`
```bash
curl https://health-monitoring-<random-id>.railway.app/health
```

Response:
```json
{
  "status": "healthy",
  "service": "health-monitoring",
  "version": "1.0.0"
}
```

### Get All Services Status

**GET** `/api/v1/health/services`
```bash
curl https://health-monitoring-<random-id>.railway.app/api/v1/health/services
```

Response:
```json
{
  "timestamp": "2025-02-06T12:34:56.789Z",
  "services": {
    "api_gateway": {
      "status": "healthy",
      "response_time_ms": 45,
      "checked_at": "2025-02-06T12:34:50.123Z",
      "error_message": null
    },
    "configuration": {...},
    "chatbot_orchestration": {...},
    ...
  }
}
```

### Get Uptime Report

**GET** `/api/v1/health/uptime?days=30`
```bash
curl "https://health-monitoring-<random-id>.railway.app/api/v1/health/uptime?days=30"
```

Response:
```json
{
  "period": "30 days",
  "start_date": "2025-01-07T12:34:56.789Z",
  "end_date": "2025-02-06T12:34:56.789Z",
  "average_uptime_percentage": 99.87,
  "services": {
    "api_gateway": 99.95,
    "configuration": 99.80,
    "chatbot_orchestration": 99.90,
    ...
  }
}
```

### Get Chart Data

**GET** `/api/v1/health/chart-data?interval=day`
```bash
curl "https://health-monitoring-<random-id>.railway.app/api/v1/health/chart-data?interval=day"
```

Response:
```json
{
  "chart_data": [
    {
      "date": "2025-02-05",
      "api_gateway": 99.95,
      "configuration": 99.80,
      "chatbot_orchestration": 99.90,
      ...
    },
    {
      "date": "2025-02-06",
      "api_gateway": 99.98,
      "configuration": 99.85,
      "chatbot_orchestration": 99.95,
      ...
    }
  ]
}
```

---

## Troubleshooting

### Problem: "Database URL not configured"

**Solution:**
1. Go to health-monitoring-service → Variables
2. Verify `DATABASE_URL` is set
3. If not set, add it from your PostgreSQL service
4. Click Deploy to restart the service

### Problem: "Failed to create DB pool: connection refused"

**Solution:**
1. Verify DATABASE_URL format is correct (should start with `postgresql://`)
2. Verify PostgreSQL service is running (check its status in Railway)
3. Verify firewall rules allow internal connections
4. Try restarting the PostgreSQL service

### Problem: Health checks running but no data appears in dashboard

**Solution:**
1. Check if health checks are being inserted:
   ```sql
   SELECT COUNT(*) FROM service_health_checks;
   ```
2. Check logs for insert errors in health_monitoring-service
3. Verify metadata is being stored correctly (fixed in latest commit)

### Problem: "Connection refused" for service URLs

**Solution:**
1. Verify all services are running in Railway
2. Verify service names in config.py match Railway service names
3. Check if services have correct health endpoints
4. Look at logs in health-monitoring-service to see which service is failing

---

## Database Schema

The health monitoring service uses this table:

```sql
CREATE TABLE IF NOT EXISTS service_health_checks (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    response_time_ms INTEGER,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    metadata JSONB,
    CONSTRAINT idx_service_checked
        UNIQUE (service_name, checked_at)
);

-- Indexes for efficient queries
CREATE INDEX idx_service_checked_time
    ON service_health_checks(service_name, checked_at DESC);
CREATE INDEX idx_checked_at
    ON service_health_checks(checked_at DESC);
```

---

## Next Steps

1. **Add DATABASE_URL to health-monitoring-service variables** (CRITICAL)
2. **Deploy and verify in logs** that "Database initialized" appears
3. **Wait for first health check cycle** (5 minutes)
4. **Check database** to see health check records being stored
5. **Use uptime data in Performance Dashboard** (ChatbotPerformance.tsx)

Once the health monitoring service is storing data, the ChatbotPerformance screen will show real uptime metrics instead of placeholders.

