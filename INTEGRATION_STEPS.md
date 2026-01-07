# Integration Steps - Chatbot Configuration Features

**Complete step-by-step guide to integrate all new features.**

---

## 📋 Overview

This integration adds:
- Human agent email confirmation flow
- Feedback recording system
- Token usage API
- System prompt appending
- Response policy implementation
- Firebase OAuth for email (OAuth credentials only)
- PostgreSQL for all application data

**Architecture**:
- **Firebase**: Stores Gmail OAuth2 credentials ONLY (`email_config/gmail_oauth`)
- **PostgreSQL (Railway)**: Stores ALL application data (human agents, feedback, sessions, configuration)

---

## 🔧 STEP 1: Run Database Migrations

### 1.1 Connect to PostgreSQL

**Option A: Railway CLI**
```bash
cd "/Users/bejoypramanick/iCloud Drive (Archive) - 1/Desktop/globistaan/projects/knowledgebot-railway-backend"
railway link
railway connect  # Connect to PostgreSQL service
```

**Option B: Railway Dashboard**
1. Go to Railway Dashboard → Your Project
2. Click on **PostgreSQL** service
3. Go to **Data** tab → **Query**

**Option C: External Tool**
- Get `DATABASE_URL` from Railway PostgreSQL service → Variables
- Connect using pgAdmin, DBeaver, or psql

### 1.2 Run Migration SQL

Execute the SQL file: `sql/chatbot_configuration_features.sql`

This creates:
- `human_agents` table
- `human_agent_sessions` table
- `chat_feedback` table
- `token_usage_cache` table
- Updates `chatbot_configuration` table with new columns

**Verification**:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('human_agents', 'chat_feedback', 'token_usage_cache');
```

---

## 🔧 STEP 2: Set Up Firebase for OAuth (OAuth Credentials Only)

### 2.1 Create Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click **Add project** → Enter name: `KnowledgeBot Email Service`
3. Enable **Firestore Database**:
   - Go to **Firestore Database** → **Create database**
   - Start in **Production mode**
   - Choose location

### 2.2 Get Firebase Service Account

1. Go to **Project Settings** (gear icon) → **Service accounts**
2. Click **Generate new private key**
3. Download JSON file (e.g., `knowledgebot-firebase-adminsdk.json`)
4. **Keep this file secure** - it has admin access

### 2.3 Set Up Firestore Collection (OAuth Only)

1. Go to **Firestore Database**
2. Create collection: `email_config`
3. Create document: `gmail_oauth`
4. Add these fields:
   ```
   client_id: "your-client-id.apps.googleusercontent.com"
   client_secret: "GOCSPX-your-client-secret"
   refresh_token: "your-refresh-token-here"
   ```

**⚠️ This is the ONLY data in Firestore. All application data goes to PostgreSQL.**

### 2.4 Get Gmail OAuth2 Credentials

**Quick Method (OAuth2 Playground)**:
1. Go to [OAuth2 Playground](https://developers.google.com/oauthplayground/)
2. Click gear icon (⚙️) → Check **Use your own OAuth credentials**
3. Enter Client ID and Secret (from Google Cloud Console)
4. In left panel: **Gmail API v1** → Select `https://www.googleapis.com/auth/gmail.send`
5. Click **Authorize APIs** → Sign in → Grant permissions
6. Click **Exchange authorization code for tokens**
7. Copy the **Refresh token**

**If you need to create OAuth credentials**:
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create project → Enable Gmail API
3. **APIs & Services** → **Credentials** → **Create OAuth client ID**
4. Application type: **Web application**
5. Copy Client ID and Secret

---

## 🔧 STEP 3: Create Configuration Service in Railway

### 3.1 Create Service

1. Railway Dashboard → Your Project
2. Click **+ New** → **GitHub Repo** (select `knowledgebot-railway-backend`)
3. Service name: `configuration-service` (exact, with hyphen)

### 3.2 Configure Service Settings

1. **Settings** → **Build**:
   - **Root Directory**: `.` (dot - repository root) ⚠️ **CRITICAL**
   - **Dockerfile Path**: `services/configuration_service/Dockerfile`
2. **Settings** → **Networking**:
   - **Port**: `8004` (auto-detected)
   - **Public Domain**: ❌ **NO** (keep private/internal)
3. **Settings** → **Resources**:
   - **CPU**: `0.5 vCPU` (default)
   - **Memory**: `512 MB` (default)

### 3.3 Set Environment Variables

Go to **Variables** tab → **RAW Editor** → Paste:

```env
# Database Connection (REQUIRED)
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}

# Service Port (REQUIRED)
CONFIGURATION_SERVICE_PORT=8004
PORT=8004

# Firebase Configuration (REQUIRED - for OAuth credentials only)
FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"your-project-id","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"firebase-adminsdk-xxxxx@your-project.iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/..."}
FIREBASE_PROJECT_ID=your-firebase-project-id

# SMTP Configuration (REQUIRED)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com

# API Keys (REQUIRED)
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key
```

**⚠️ Important**:
- Replace `FIREBASE_CREDENTIALS_JSON` with entire JSON from service account file (as single-line string)
- Replace `your-firebase-project-id` with your Firebase project ID
- Replace `your-email@gmail.com` with Gmail address used for OAuth
- Replace API keys with actual keys
- Replace `https://widget.yourdomain.com` with your widget URL

---

## 🔧 STEP 4: Update API Gateway

### 4.1 Add Environment Variable

1. Go to **API Gateway** service → **Variables** tab
2. Add:
```env
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
```

### 4.2 Verify All Service URLs

Ensure these exist in API Gateway variables:
```env
KNOWLEDGEBASE_INGESTION_URL=http://knowledgebase-ingestion:8001
WEBSITE_SCRAPING_URL=http://website-scraping:8002
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration:8003
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
API_GATEWAY_PORT=8000
API_GATEWAY_HOST=0.0.0.0
```

---

## 🔧 STEP 5: Verify Chatbot Orchestration Service

### 5.1 Check Environment Variables

Go to **Chatbot Orchestration** service → **Variables** → Verify:
```env
GEMINI_API_KEY=your-key
OPENAI_API_KEY=your-key
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
```

**No new variables needed** - code already supports `system_prompt` and `response_policy`.

---

## 🔧 STEP 6: Deploy and Test

### 6.1 Deploy Services

1. **Configuration Service**: Should auto-deploy after creation
2. **API Gateway**: May need manual redeploy after adding variable
3. **Chatbot Orchestration**: Should auto-deploy (code changes in repo)

### 6.2 Check Service Health

1. Each service → **Deployments** tab → Verify **Active** and **Healthy**
2. Check **Logs** tab for errors

### 6.3 Test Endpoints

Get your API Gateway URL from Railway (e.g., `api-gateway-production-c4c3.up.railway.app`)

**Test Configuration**:
```bash
curl https://your-api-gateway.up.railway.app/api/v1/configuration/chatbot
```

**Test Feedback**:
```bash
curl -X POST https://your-api-gateway.up.railway.app/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"message_id": "test", "session_id": "test", "feedback": "positive"}'
```

**Test Token Usage**:
```bash
curl https://your-api-gateway.up.railway.app/api/v1/admin/token-usage
```

**Test Human Agent (requires Firebase OAuth setup)**:
```bash
curl -X POST https://your-api-gateway.up.railway.app/api/v1/admin/human-agents \
  -H "Content-Type: application/json" \
  -d '{"emails": ["test@example.com"]}'
```

---

## ✅ Checklist

### Database
- [ ] Database migrations executed successfully
- [ ] Tables created: `human_agents`, `chat_feedback`, `token_usage_cache`
- [ ] `chatbot_configuration` table updated with new columns

### Firebase
- [ ] Firebase project created
- [ ] Firestore database enabled
- [ ] Service account JSON downloaded
- [ ] Firestore collection `email_config/gmail_oauth` created
- [ ] OAuth credentials added to Firestore (client_id, client_secret, refresh_token)

### Railway Services
- [ ] Configuration Service created
- [ ] Root Directory set to `.` (dot)
- [ ] Dockerfile Path: `services/configuration_service/Dockerfile`
- [ ] All environment variables set in Configuration Service
- [ ] `CONFIGURATION_SERVICE_URL` added to API Gateway
- [ ] All services healthy and running

### Environment Variables (Configuration Service)
- [ ] `DATABASE_URL` or `RAILWAY_POSTGRES_URL`
- [ ] `CONFIGURATION_SERVICE_PORT=8004`
- [ ] `PORT=8004`
- [ ] `FIREBASE_CREDENTIALS_JSON` (entire JSON as single-line string)
- [ ] `FIREBASE_PROJECT_ID`
- [ ] `SMTP_HOST=smtp.gmail.com`
- [ ] `SMTP_PORT=587`
- [ ] `SMTP_USER=your-email@gmail.com`
- [ ] `EMAIL_FROM=noreply@knowledgebot.com`
- [ ] `WIDGET_BASE_URL=https://widget.yourdomain.com`
- [ ] `GEMINI_API_KEY`
- [ ] `OPENAI_API_KEY`

### Testing
- [ ] Configuration endpoint returns 200
- [ ] Feedback endpoint works
- [ ] Token usage endpoint works
- [ ] Human agent email sent successfully
- [ ] Frontend can connect to all endpoints

---

## 🐛 Troubleshooting

### Firebase Not Initializing
- Check `FIREBASE_CREDENTIALS_JSON` is valid JSON (no extra quotes)
- Verify JSON is complete (all fields present)
- Check `FIREBASE_PROJECT_ID` matches Firebase project

### OAuth Credentials Not Found
- Verify Firestore collection: `email_config`
- Verify document: `gmail_oauth`
- Check field names: `client_id`, `client_secret`, `refresh_token`
- Verify Firestore security rules allow Admin SDK access

### Email Not Sending
- Check Firebase OAuth credentials in Firestore
- Verify refresh token is valid (not expired)
- Check `SMTP_USER` matches Gmail account used for OAuth
- Check Railway logs for OAuth errors
- Verify Gmail API is enabled in Google Cloud Console

### Database Errors
- Verify migrations ran successfully
- Check `DATABASE_URL` is set correctly
- Verify database user has CREATE TABLE permissions
- Check Railway logs for connection errors

### Endpoints Return 404
- Verify `CONFIGURATION_SERVICE_URL` in API Gateway
- Check service name is `configuration-service` (with hyphen)
- Verify service is running (check deployments)
- Check API Gateway routing configuration

---

## 📚 Quick Reference

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

**Root Directory**: `.` (dot) for ALL services

**Database Variable**: `${{PostgreSQL.DATABASE_URL}}` in Railway

**Firebase**: OAuth credentials ONLY in `email_config/gmail_oauth`

**PostgreSQL**: ALL application data (human_agents, chat_feedback, etc.)

---

## 🎯 Summary

1. **Run SQL migrations** on PostgreSQL
2. **Set up Firebase** for OAuth credentials (Firestore: `email_config/gmail_oauth`)
3. **Create Configuration Service** in Railway
4. **Set environment variables** (Firebase, Database, SMTP, API keys)
5. **Update API Gateway** with `CONFIGURATION_SERVICE_URL`
6. **Deploy and test** all endpoints

**That's it!** Follow the checklist above to verify everything is working.

