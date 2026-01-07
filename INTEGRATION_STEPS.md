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
- Gmail OAuth2 for email sending
- **Firebase Authentication** (NO Firestore) for user login
- PostgreSQL for ALL data (including OAuth credentials and user data)

**Architecture**:
- **Firebase Authentication**: User login/authentication (email/password, Google OAuth, etc.)
  - **NO Firestore** - Only Firebase Auth is used
  - Tokens verified on backend using Firebase Admin SDK
- **PostgreSQL (Railway)**: Stores ALL application data
  - `users` - User information linked to Firebase Auth UIDs
  - `email_oauth_credentials` - Gmail OAuth2 credentials
  - `human_agents` - Human agent information
  - `chat_feedback` - User feedback
  - All other application tables

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

## 🔧 STEP 2: Set Up Firebase Authentication (NO Firestore)

### 2.1 Create Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click **Add project** → Enter name: `KnowledgeBot`
3. **DO NOT enable Firestore** - We only need Authentication
4. Go to **Authentication** → **Get started**
5. Enable **Email/Password** sign-in method
6. (Optional) Enable **Google** sign-in for OAuth

### 2.2 Get Firebase Service Account

1. Go to **Project Settings** (gear icon) → **Service accounts**
2. Click **Generate new private key**
3. Download JSON file (e.g., `knowledgebot-firebase-adminsdk.json`)
4. **Keep this file secure** - it has admin access

### 2.3 Configure Firebase Auth

**Authentication Methods to Enable**:
- Email/Password (for admin and human agents)
- Google (optional, for OAuth login)

**Note**: We use Firebase Auth ONLY for authentication. All user data is stored in PostgreSQL.

---

## 🔧 STEP 3: Get Gmail OAuth2 Credentials

**Note**: OAuth credentials for email sending are stored in PostgreSQL, not Firebase.

### 3.1 Quick Method (OAuth2 Playground)

1. Go to [OAuth2 Playground](https://developers.google.com/oauthplayground/)
2. Click gear icon (⚙️) → Check **Use your own OAuth credentials**
3. Enter Client ID and Secret (from Google Cloud Console - see below if you don't have them)
4. In left panel: **Gmail API v1** → Select `https://www.googleapis.com/auth/gmail.send`
5. Click **Authorize APIs** → Sign in → Grant permissions
6. Click **Exchange authorization code for tokens**
7. Copy the **Refresh token**

### 3.2 Create OAuth Credentials (if needed)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create project → Enable Gmail API
3. **APIs & Services** → **Credentials** → **Create OAuth client ID**
4. Application type: **Web application**
5. Copy **Client ID** and **Client Secret**

### 3.3 Store Credentials in PostgreSQL

After getting Client ID, Secret, and Refresh Token, insert them into PostgreSQL:

```sql
UPDATE email_oauth_credentials 
SET 
    client_id = 'your-client-id.apps.googleusercontent.com',
    client_secret = 'GOCSPX-your-client-secret',
    refresh_token = 'your-refresh-token-here',
    updated_at = NOW()
WHERE id = 1;
```

**⚠️ These credentials are stored in PostgreSQL, not Firebase.**

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

# Note: OAuth credentials are stored in PostgreSQL, not environment variables
# Insert credentials into email_oauth_credentials table after deployment

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
- Replace `your-email@gmail.com` with Gmail address used for OAuth
- Replace API keys with actual keys
- Replace `https://widget.yourdomain.com` with your widget URL
- **OAuth credentials** (Client ID, Secret, Refresh Token) are stored in PostgreSQL `email_oauth_credentials` table, not environment variables

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

### Firebase Authentication
- [ ] Firebase project created
- [ ] Authentication enabled (Email/Password, Google optional)
- [ ] Service account JSON downloaded
- [ ] `FIREBASE_CREDENTIALS_JSON` or `FIREBASE_CREDENTIALS_PATH` set in Railway

### OAuth Credentials (for Email)
- [ ] Gmail OAuth2 credentials obtained (Client ID, Secret, Refresh Token)
- [ ] Credentials stored in PostgreSQL `email_oauth_credentials` table

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
- [ ] `FIREBASE_CREDENTIALS_JSON` (entire JSON as single-line string) OR `FIREBASE_CREDENTIALS_PATH` (path to JSON file)
- [ ] `SMTP_HOST=smtp.gmail.com`
- [ ] `SMTP_PORT=587`
- [ ] `SMTP_USER=your-email@gmail.com`
- [ ] `EMAIL_FROM=noreply@knowledgebot.com`
- [ ] `WIDGET_BASE_URL=https://widget.yourdomain.com`
- [ ] `GEMINI_API_KEY`
- [ ] `OPENAI_API_KEY`

### OAuth Credentials in PostgreSQL
- [ ] `email_oauth_credentials` table created (via migration)
- [ ] OAuth credentials inserted: `client_id`, `client_secret`, `refresh_token`

### Testing
- [ ] Configuration endpoint returns 200
- [ ] Feedback endpoint works
- [ ] Token usage endpoint works
- [ ] Human agent email sent successfully
- [ ] Frontend can connect to all endpoints

---

## 🐛 Troubleshooting

### OAuth Credentials Not Found
- Verify PostgreSQL table: `email_oauth_credentials`
- Check row exists: `SELECT * FROM email_oauth_credentials WHERE id = 1;`
- Verify field names: `client_id`, `client_secret`, `refresh_token`
- Check credentials are not empty strings

### Email Not Sending
- Check OAuth credentials in PostgreSQL: `SELECT * FROM email_oauth_credentials WHERE id = 1;`
- Verify refresh token is valid (not expired)
- Check `SMTP_USER` matches Gmail account used for OAuth
- Check Railway logs for OAuth errors
- Verify Gmail API is enabled in Google Cloud Console
- Verify credentials are properly inserted (not empty strings)

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

**OAuth Credentials**: Stored in PostgreSQL `email_oauth_credentials` table

**PostgreSQL**: ALL data including OAuth credentials (human_agents, chat_feedback, email_oauth_credentials, etc.)

---

## 🎯 Summary

1. **Run SQL migrations** on PostgreSQL (creates `users` and `email_oauth_credentials` tables)
2. **Set up Firebase Authentication** (NO Firestore)
   - Create Firebase project
   - Enable Email/Password authentication
   - Get service account JSON
3. **Get Gmail OAuth2 credentials** (Client ID, Secret, Refresh Token)
4. **Store OAuth credentials in PostgreSQL** (`email_oauth_credentials` table)
5. **Create Configuration Service** in Railway
6. **Set environment variables** (Database, Firebase Auth, SMTP, API keys)
7. **Update API Gateway** with `CONFIGURATION_SERVICE_URL`
8. **Deploy and test** all endpoints

**That's it!** Follow the checklist above to verify everything is working.

**Important**:
- **Firebase Auth**: Used ONLY for user authentication (login/signup)
- **NO Firestore**: All data stored in PostgreSQL
- **PostgreSQL**: Stores user data, OAuth credentials, and all application data

