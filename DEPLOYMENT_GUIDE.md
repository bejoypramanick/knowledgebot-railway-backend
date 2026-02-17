# Complete Deployment Guide - 8 Requirement Enhancement Project

## Pre-Deployment Checklist

- [x] All code committed to git
- [x] Backend enhancements completed (health monitoring, system prompt, performance data)
- [x] Frontend enhancements completed (ChatLog WhatsApp UI, KB cards mobile)
- [ ] Database migrations tested locally
- [ ] Environment variables documented
- [ ] All services health checks verified
- [ ] Monitoring and alerts configured

---

## Phase 1: Database Setup

### Step 1: Run Database Migrations

```bash
# Connect to production database
export DATABASE_URL="your_railway_postgres_url"

# Run the service_health_checks migration
psql $DATABASE_URL < migrations/add_service_health_checks.sql

# Verify table creation
psql $DATABASE_URL -c "SELECT table_name FROM information_schema.tables WHERE table_name='service_health_checks';"
```

Expected output:
```
 table_name
----------------------
 service_health_checks
(1 row)
```

### Step 2: Verify Database Indexes

```bash
# Check indexes were created
psql $DATABASE_URL -c "SELECT indexname FROM pg_indexes WHERE tablename='service_health_checks';"
```

Expected output:
```
                          indexname
------------------------------------------------------------
 idx_service_health_checks_service_checked
 idx_service_health_checks_checked_at
 idx_service_health_checks_status
 idx_service_health_checks_status_checked
(4 rows)
```

---

## Phase 2: Environment Variables Configuration

### Backend Services - Required Environment Variables

#### All Services
```bash
# Database
DATABASE_URL="postgresql://user:password@host:5432/dbname"
DATABASE_URL="postgresql://user:password@host:5432/dbname"

# Gemini/AI
GEMINI_API_KEY="your_gemini_api_key"
```

#### API Gateway
```bash
# Port
API_GATEWAY_PORT=8000

# Service URLs
CONFIGURATION_SERVICE_URL="https://configuration-service.railway.app"
CHATBOT_ORCHESTRATION_URL="https://chatbot-orchestration.railway.app"
KNOWLEDGEBASE_INGESTION_URL="https://knowledgebase-ingestion.railway.app"
WEBSITE_CRAWLING_URL="https://website-crawling.railway.app"
DOCLING_SERVICE_URL="https://docling-service.railway.app"
HEALTH_MONITORING_URL="https://health-monitoring.railway.app"
```

#### Website Crawling Service
```bash
# Port
WEBSITE_SCRAPING_PORT=8002

# Docling Configuration
DOCLING_ENABLED_FOR_WEBSITES=true
DOCLING_SERVICE_URL="https://docling-service.railway.app"
DOCLING_WEBSITE_TIMEOUT_SECONDS=300
DOCLING_WEBSITE_FALLBACK_TO_RAW=true
```

#### Docling Service
```bash
# Port
DOCLING_PORT=8004

# Model Cache (use volume mounts)
DOCLING_CACHE_DIR="/models/huggingface"
EASYOCR_CACHE_DIR="/models/easyocr"
```

#### Health Monitoring Service (NEW)
```bash
# Port
HEALTH_MONITORING_PORT=8006

# Database
DATABASE_URL="postgresql://user:password@host:5432/dbname"

# Service URLs to Monitor
API_GATEWAY_URL="https://api-gateway.railway.app"
CONFIGURATION_SERVICE_URL="https://configuration-service.railway.app"
CHATBOT_ORCHESTRATION_URL="https://chatbot-orchestration.railway.app"
KNOWLEDGEBASE_INGESTION_URL="https://knowledgebase-ingestion.railway.app"
WEBSITE_CRAWLING_URL="https://website-crawling.railway.app"
DOCLING_SERVICE_URL="https://docling-service.railway.app"

# Health Check Configuration
HEALTH_CHECK_INTERVAL_SECONDS=300
HEALTH_CHECK_TIMEOUT_SECONDS=10
```

#### Configuration Service
```bash
# Port
CONFIGURATION_PORT=8001

# Health Monitoring Service
HEALTH_MONITORING_URL="https://health-monitoring.railway.app"
```

### Frontend - Environment Variables

```bash
# .env or .env.production
VITE_API_GATEWAY_URL="https://api-gateway.railway.app"
VITE_WEBSOCKET_URL="wss://api-gateway.railway.app/ws"
VITE_HEALTH_MONITORING_URL="https://health-monitoring.railway.app"
```

---

## Phase 3: Service Deployment Order

### Deployment Priority

1. **Database Migration First** (before any service)
   ```bash
   psql $DATABASE_URL < migrations/add_service_health_checks.sql
   ```

2. **Deploy Health Monitoring Service** (new service)
   - This service monitors all other services
   - Should be running before other services are updated

3. **Deploy Configuration Service** (updated with health monitoring integration)
   - Needs HEALTH_MONITORING_URL environment variable
   - Provides real performance data

4. **Deploy Other Backend Services** (in any order, all updated)
   - API Gateway
   - Chatbot Orchestration (updated prompt)
   - Website Crawling
   - Docling Service
   - Knowledgebase Ingestion

5. **Deploy Frontend** (React app)
   - All API endpoints should be available first

### Railway Deployment Steps

#### For Health Monitoring Service

```bash
# 1. Create service on Railway
railway init
railway link health-monitoring-service

# 2. Set environment variables
railway variables set \
  DATABASE_URL=$DATABASE_URL \
  HEALTH_CHECK_INTERVAL_SECONDS=300 \
  HEALTH_CHECK_TIMEOUT_SECONDS=10 \
  API_GATEWAY_URL=https://api-gateway.railway.app \
  CONFIGURATION_SERVICE_URL=https://configuration-service.railway.app \
  CHATBOT_ORCHESTRATION_URL=https://chatbot-orchestration.railway.app \
  KNOWLEDGEBASE_INGESTION_URL=https://knowledgebase-ingestion.railway.app \
  WEBSITE_CRAWLING_URL=https://website-crawling.railway.app \
  DOCLING_SERVICE_URL=https://docling-service.railway.app

# 3. Deploy
railway up

# 4. Get service URL
railway domains
```

#### For Configuration Service (Updated)

```bash
# 1. Link to existing service
railway link configuration-service

# 2. Update environment variables
railway variables set \
  HEALTH_MONITORING_URL=https://health-monitoring.railway.app

# 3. Deploy
railway up
```

#### For Other Services

Update environment variables to point to health monitoring service, then redeploy:

```bash
railway up
```

---

## Phase 4: Verification Steps

### Health Monitoring Service Verification

```bash
# 1. Check if service is running
curl https://health-monitoring.railway.app/health

# Expected response:
# {"status":"healthy","service":"health-monitoring","timestamp":"2025-02-06T..."}

# 2. Check all services status
curl https://health-monitoring.railway.app/api/v1/health/services

# Expected response:
# {
#   "timestamp": "2025-02-06T...",
#   "services": {
#     "api_gateway": {"status": "healthy", "response_time_ms": 45, ...},
#     "configuration": {"status": "healthy", ...},
#     ...
#   }
# }

# 3. Check uptime report
curl "https://health-monitoring.railway.app/api/v1/health/uptime?days=30"

# 4. Check SLA compliance
curl https://health-monitoring.railway.app/api/v1/health/sla-compliance

# 5. Check system health summary
curl https://health-monitoring.railway.app/api/v1/health/summary
```

### Performance Screen Verification

```bash
# 1. Verify API returns real data
curl -H "Authorization: Bearer $TOKEN" \
  https://api-gateway.railway.app/api/v1/configuration/performance-metrics

# Expected response includes:
# {
#   "user_satisfaction": 4.25,
#   "satisfaction_over_time": [...],
#   "uptime_percentage": 99.87,
#   "total_interactions": 1234,
#   ...
# }
```

### ChatLog UI Verification

```bash
# 1. Visual verification (manual)
# - Check ChatLog component displays WhatsApp green bubbles for users
# - Check bot/agent messages display white/dark bubbles
# - Check message input has green send button
# - Verify date separators appear between messages on different days
# - Test on mobile (iPhone), tablet, and desktop

# 2. Check responsive design
# - Mobile: 1 column KB cards
# - Tablet: 2 columns KB cards
# - Desktop: 3-4 columns KB cards

# 3. Check KB cards
# - Filename/URL only in header
# - Metadata in body
# - Actions in footer
```

### Website Scraping Verification

```bash
# 1. Test scraping endpoint
curl -X POST https://api-gateway.railway.app/api/v1/gateway/website-crawling \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 5,
    "max_depth": 2,
    "replace_existing": false
  }'

# 2. Verify Docling integration
# - Check that HTML is converted to markdown
# - Check that Docling processing time is logged
# - Verify fallback works when Docling is disabled
```

### System Prompt Verification

```bash
# 1. Test guardrails
# - Try to request medical advice → should be escalated
# - Try to request PII access → should be blocked
# - Try prompt injection → should be detected

# 2. Test formatting
# - Send code snippet → should be formatted with syntax highlighting
# - Send request for table → should format as markdown table
# - Send request with links → should format as [text](url)
```

---

## Phase 5: Production Monitoring

### Setup Monitoring Alerts

#### Critical Alerts to Configure

1. **Service Down Alert**
   - Condition: Any service health status = "down" for > 5 minutes
   - Action: Page on-call engineer

2. **SLA Breach Alert**
   - Condition: System uptime < 99.5% in any 30-minute window
   - Action: Notify team

3. **High Error Rate Alert**
   - Condition: Error rate > 5% in last hour
   - Action: Notify team

4. **Response Time Alert**
   - Condition: P95 response time > 5 seconds
   - Action: Notify team

5. **Database Connection Alert**
   - Condition: Failed database connections > 10 in last 5 minutes
   - Action: Page on-call engineer

### Setup Logging

```bash
# All services should log to:
# - Standard output (stdout)
# - OpenTelemetry traces
# - Structured JSON logs with:
#   - timestamp
#   - service_name
#   - log_level (INFO, WARNING, ERROR)
#   - message
#   - correlation_id
#   - user_email (if applicable)

# View logs in Railway:
railway logs

# Filter logs:
railway logs | grep ERROR
railway logs | grep correlation_id:xyz
```

### Dashboard Setup

Create monitoring dashboard with:

1. **System Health**
   - Service uptime (%) by service
   - Overall system uptime (%)
   - SLA compliance status

2. **Performance Metrics**
   - Total interactions (last 30 days)
   - User satisfaction (last 30 days)
   - AI handled vs human handoff ratio
   - Average engagement time

3. **API Performance**
   - Request count by endpoint
   - Error rate by endpoint
   - Response time distribution

4. **Health Checks**
   - Last health check time by service
   - Health check response times
   - Failed health checks (30 days)

---

## Phase 6: Rollback Plan

If issues occur, follow this rollback plan:

### Rollback Health Monitoring Service
```bash
# Stop health monitoring service
railway disable health-monitoring

# Existing services will continue without health monitoring
# Performance screen will show previous data
```

### Rollback Frontend
```bash
# Redeploy previous version
git checkout <previous-commit-hash>
npm run build
railway up
```

### Rollback Backend Services
```bash
# Redeploy previous version for specific service
railway link <service-name>
git checkout <previous-commit-hash>
railway up
```

### Rollback Database
```bash
# WARNING: Only do this if absolutely necessary
# Backup current state first
psql $DATABASE_URL -c "BEGIN; TRUNCATE service_health_checks; COMMIT;"

# Or restore from backup:
# psql $DATABASE_URL < backup.sql
```

---

## Phase 7: Post-Deployment Validation

### User-Facing Features

- [ ] ChatLog displays WhatsApp-style message bubbles
- [ ] Message input has green send button
- [ ] Knowledge base cards are responsive on mobile
- [ ] Performance screen shows real traffic data
- [ ] Performance screen shows real feedback data
- [ ] Performance screen shows real uptime data
- [ ] Website scraping works end-to-end with Docling
- [ ] Human-in-loop session assignment works
- [ ] System prompt guardrails prevent dangerous operations
- [ ] Feedback collection works and appears in performance screen

### Backend Services

- [ ] Health monitoring service checks all services every 5 minutes
- [ ] Health monitoring API returns correct uptime percentages
- [ ] Performance metrics API returns real data
- [ ] System prompt includes guardrails and formatting
- [ ] Website scraping with Docling integration works
- [ ] All services respond to health check endpoints

### System Stability

- [ ] No service errors in logs in first 30 minutes
- [ ] Health monitoring service runs reliably for first hour
- [ ] Performance screen data updates correctly
- [ ] Database performance is acceptable (no slow queries)
- [ ] Memory usage is stable on all services

---

## Support and Troubleshooting

### Common Issues

**Issue**: Health monitoring shows "down" for a service
- Check service logs: `railway logs --service=<service-name>`
- Verify service URL in health monitoring env vars
- Ensure service has `/health` endpoint

**Issue**: Performance screen shows old/no data
- Check performance API: `curl https://api-gateway.railway.app/api/v1/configuration/performance-metrics`
- Verify database connection: `psql $DATABASE_URL -c "SELECT COUNT(*) FROM chat_feedback;"`
- Check health monitoring is running: `curl https://health-monitoring.railway.app/health`

**Issue**: Docling integration fails
- Check Docling service health: `curl https://docling-service.railway.app/health`
- Verify `DOCLING_ENABLED_FOR_WEBSITES=true`
- Check Docling logs for model loading errors

**Issue**: ChatLog WhatsApp UI not displaying correctly
- Clear browser cache and reload
- Check that frontend was deployed with latest changes
- Verify theme preference in local storage

---

## Success Criteria

✅ **Deployment is successful when:**
1. All services report "healthy" status
2. Health monitoring runs background checks every 5 minutes
3. Performance screen displays real data (not placeholders)
4. ChatLog displays WhatsApp-style UI
5. Knowledge base cards are mobile-optimized
6. Website scraping with Docling works end-to-end
7. System prompt guardrails are enforced
8. No errors in logs for first 24 hours
9. User satisfaction data appears in performance screen
10. All E2E integration tests pass

---

## Estimated Deployment Time

- Database migration: 5 minutes
- Environment variable setup: 10 minutes
- Health monitoring service deployment: 15 minutes
- Configuration service deployment: 10 minutes
- Other services deployment: 20 minutes
- Frontend deployment: 10 minutes
- Verification: 30 minutes
- **Total: ~100 minutes (1.5-2 hours)**

---

## Contacts and Escalation

- **Service Issues**: Check logs at `railway logs`
- **Database Issues**: Check Railway Postgres dashboard
- **Frontend Issues**: Check browser console and network tab
- **Performance Issues**: Check metrics dashboard and service logs

---

**Last Updated**: 2025-02-06
**Deployment Version**: Complete 8-Requirement Implementation
