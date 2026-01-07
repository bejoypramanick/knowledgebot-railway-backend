# Railway Configuration Guide - Chatbot Configuration Features

**VERY SPECIFIC STEP-BY-STEP INSTRUCTIONS FOR RAILWAY**

## 📋 Overview

You need to configure **5 services** in Railway:
1. **PostgreSQL Database** (existing)
2. **API Gateway** (existing - needs update)
3. **Configuration Service** (NEW - needs to be added)
4. **Chatbot Orchestration** (existing - needs update)
5. **Knowledgebase Ingestion** (existing - no changes)
6. **Website Scraping** (existing - no changes)

---

## 🔧 STEP 1: Run Database Migrations

### Option A: Using Railway CLI (Recommended)

1. **Install Railway CLI** (if not installed):
   ```bash
   npm i -g @railway/cli
   railway login
   ```

2. **Connect to your database**:
   ```bash
   cd "/Users/bejoypramanick/iCloud Drive (Archive) - 1/Desktop/globistaan/projects/knowledgebot-railway-backend"
   railway link  # Link to your Railway project
   railway connect  # Connect to PostgreSQL service
   ```

3. **Run migrations**:
   ```bash
   railway run psql $DATABASE_URL -f sql/chatbot_configuration_features.sql
   ```

### Option B: Using Railway Dashboard

1. Go to **Railway Dashboard** → Your Project
2. Click on your **PostgreSQL** service
3. Go to **Data** tab → **Query**
4. Copy the contents of `sql/chatbot_configuration_features.sql`
5. Paste and execute in the query editor

### Option C: Using External Tool (pgAdmin, DBeaver, etc.)

1. Get your database connection string from Railway:
   - Go to PostgreSQL service → **Variables** tab
   - Copy `DATABASE_URL` or `RAILWAY_POSTGRES_URL`
2. Connect using your tool
3. Run the SQL file: `sql/chatbot_configuration_features.sql`

**✅ Verification**: After running, verify tables exist:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('human_agents', 'chat_feedback', 'token_usage_cache');
```

---

## 🔧 STEP 2: Add Configuration Service to Railway

### 2.1 Create New Service

1. Go to **Railway Dashboard** → Your Project
2. Click **+ New** → **GitHub Repo** (or **Empty Service**)
3. If using GitHub:
   - Select your `knowledgebot-railway-backend` repository
   - Railway will auto-detect it
4. If using Empty Service:
   - Connect your GitHub repo manually

### 2.2 Configure Service Settings

1. **Service Name**: `configuration-service` (exact name, with hyphen)
2. **Settings** → **Build**:
   - **Root Directory**: `.` (dot - repository root) ⚠️ **CRITICAL**
   - **Dockerfile Path**: `services/configuration_service/Dockerfile`
3. **Settings** → **Networking**:
   - **Port**: `8004` (auto-detected from Dockerfile)
   - **Public Domain**: ❌ **NO** (Keep it private/internal)
4. **Settings** → **Resources**:
   - **CPU**: `0.5 vCPU` (default)
   - **Memory**: `512 MB` (default)

### 2.3 Set Environment Variables

Go to **Variables** tab → **RAW Editor** → Paste these:

```env
# Database Connection (REQUIRED)
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
# OR use this if DATABASE_URL doesn't work:
RAILWAY_POSTGRES_URL=${{PostgreSQL.DATABASE_URL}}
# OR use this:
POSTGRES_URL=${{PostgreSQL.DATABASE_URL}}

# Service Port (REQUIRED)
CONFIGURATION_SERVICE_PORT=8004
PORT=8004

# Email Configuration (REQUIRED for human agent emails)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com

# API Keys (REQUIRED)
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key
```

**⚠️ Important Notes:**
- Replace `your-email@gmail.com` with your actual Gmail
- Replace `your-gmail-app-password` with Gmail App Password (see Gmail setup below)
- Replace `your-gemini-api-key` and `your-openai-api-key` with actual keys
- Replace `https://widget.yourdomain.com` with your actual widget URL
- `${{PostgreSQL.DATABASE_URL}}` is Railway's variable reference syntax

### 2.4 Gmail App Password Setup

1. Go to **Google Account** → **Security**
2. Enable **2-Step Verification** (if not already enabled)
3. Go to **App Passwords**:
   - Click **Select app** → **Mail**
   - Click **Select device** → **Other (Custom name)**
   - Enter: "KnowledgeBot Railway"
   - Click **Generate**
4. Copy the 16-character password (no spaces)
5. Use this in `SMTP_PASSWORD` (NOT your regular Gmail password)

---

## 🔧 STEP 3: Update API Gateway Service

### 3.1 Add Environment Variable

1. Go to **API Gateway** service → **Variables** tab
2. Add this variable:

```env
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
```

### 3.2 Update API Gateway Code (if needed)

The API Gateway should automatically route to configuration service. Verify in `api_gateway/main.py` that it includes:

```python
CONFIGURATION_SERVICE_URL = os.getenv('CONFIGURATION_SERVICE_URL', 'http://configuration-service:8004')
```

If not present, you may need to add routing for the new endpoints.

---

## 🔧 STEP 4: Update Chatbot Orchestration Service

### 4.1 Verify Environment Variables

Go to **Chatbot Orchestration** service → **Variables** tab → Verify these exist:

```env
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
# OR
RAILWAY_POSTGRES_URL=${{PostgreSQL.DATABASE_URL}}
```

**No new variables needed** - the code changes are already in place to accept `system_prompt` and `response_policy` parameters.

---

## 🔧 STEP 5: Verify Service URLs in API Gateway

### 5.1 Check API Gateway Variables

Go to **API Gateway** service → **Variables** tab → Verify ALL these exist:

```env
KNOWLEDGEBASE_INGESTION_URL=http://knowledgebase-ingestion:8001
WEBSITE_SCRAPING_URL=http://website-scraping:8002
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration:8003
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
API_GATEWAY_PORT=8000
API_GATEWAY_HOST=0.0.0.0
```

**⚠️ Important**: Service names use **hyphens** (`configuration-service`), not underscores.

---

## 🔧 STEP 6: Deploy and Verify

### 6.1 Deploy All Services

1. **Configuration Service**: Should auto-deploy after adding
2. **API Gateway**: May need manual redeploy if you added variables
3. **Chatbot Orchestration**: Should auto-deploy (code changes are in repo)

### 6.2 Check Service Health

1. Go to each service → **Deployments** tab
2. Verify latest deployment is **Active** and **Healthy**
3. Check **Logs** tab for any errors

### 6.3 Test Endpoints

Get your API Gateway public URL:
- Go to **API Gateway** service → **Settings** → **Networking**
- Copy the **Public Domain** (e.g., `api-gateway-production-c4c3.up.railway.app`)

**Test Configuration Service Health**:
```bash
curl https://your-api-gateway-url.up.railway.app/api/v1/configuration/chatbot
```

**Test New Endpoints**:
```bash
# Test feedback
curl -X POST https://your-api-gateway-url.up.railway.app/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"message_id": "test", "session_id": "test", "feedback": "positive"}'

# Test token usage
curl https://your-api-gateway-url.up.railway.app/api/v1/admin/token-usage
```

---

## 📋 Complete Environment Variables Checklist

### Configuration Service (NEW)
- [ ] `DATABASE_URL` or `RAILWAY_POSTGRES_URL` or `POSTGRES_URL`
- [ ] `CONFIGURATION_SERVICE_PORT=8004`
- [ ] `PORT=8004`
- [ ] `SMTP_HOST=smtp.gmail.com`
- [ ] `SMTP_PORT=587`
- [ ] `SMTP_USER=your-email@gmail.com`
- [ ] `SMTP_PASSWORD=your-app-password`
- [ ] `EMAIL_FROM=noreply@knowledgebot.com`
- [ ] `WIDGET_BASE_URL=https://widget.yourdomain.com`
- [ ] `GEMINI_API_KEY=your-key`
- [ ] `OPENAI_API_KEY=your-key`

### API Gateway (UPDATE)
- [ ] `CONFIGURATION_SERVICE_URL=http://configuration-service:8004` ← **ADD THIS**
- [ ] `KNOWLEDGEBASE_INGESTION_URL=http://knowledgebase-ingestion:8001`
- [ ] `WEBSITE_SCRAPING_URL=http://website-scraping:8002`
- [ ] `CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration:8003`
- [ ] `API_GATEWAY_PORT=8000`
- [ ] `API_GATEWAY_HOST=0.0.0.0`

### Chatbot Orchestration (VERIFY - No new vars needed)
- [ ] `GEMINI_API_KEY=your-key`
- [ ] `OPENAI_API_KEY=your-key`
- [ ] `DATABASE_URL` or `RAILWAY_POSTGRES_URL` (if using database features)

### Knowledgebase Ingestion (NO CHANGES)
- [ ] `GEMINI_API_KEY=your-key`

### Website Scraping (NO CHANGES)
- [ ] `GEMINI_API_KEY=your-key`

---

## 🐛 Troubleshooting

### Service Not Starting

1. **Check Logs**: Go to service → **Logs** tab
2. **Common Errors**:
   - `ModuleNotFoundError`: Check Root Directory is `.` (dot)
   - `Database connection failed`: Check `DATABASE_URL` variable
   - `SMTP authentication failed`: Check Gmail App Password

### Endpoints Return 404

1. **Check API Gateway routing**: Verify `CONFIGURATION_SERVICE_URL` is set
2. **Check service name**: Must be `configuration-service` (with hyphen)
3. **Check service is running**: Go to service → **Deployments** → Verify active

### Email Not Sending

1. **Check SMTP variables**: All 5 email variables must be set
2. **Verify Gmail App Password**: Must be 16 characters, no spaces
3. **Check logs**: Look for SMTP errors in Configuration Service logs
4. **Test SMTP connection**: Check if port 587 is accessible from Railway

### Database Errors

1. **Verify migrations ran**: Check if tables exist
2. **Check connection string**: Use `${{PostgreSQL.DATABASE_URL}}` syntax
3. **Verify permissions**: Database user needs CREATE TABLE permission

---

## ✅ Final Verification Checklist

- [ ] Database migrations completed successfully
- [ ] Configuration Service created and deployed
- [ ] All environment variables set in Configuration Service
- [ ] `CONFIGURATION_SERVICE_URL` added to API Gateway
- [ ] All services are healthy (green status)
- [ ] Test endpoints return 200 OK
- [ ] Email test successful (add a test human agent)
- [ ] Frontend can connect to all endpoints

---

## 📞 Quick Reference

**Service Names** (exact, case-sensitive):
- `api-gateway`
- `configuration-service` ← **NEW**
- `chatbot-orchestration`
- `knowledgebase-ingestion`
- `website-scraping`

**Ports**:
- API Gateway: `8000` (public)
- Configuration Service: `8004` (internal)
- Chatbot Orchestration: `8003` (internal)
- Knowledgebase Ingestion: `8001` (internal)
- Website Scraping: `8002` (internal)

**Root Directory**: `.` (dot) for ALL services

**Database Variable**: Use `${{PostgreSQL.DATABASE_URL}}` in Railway

---

**Need Help?** Check Railway logs or review error messages in the service logs tab.

