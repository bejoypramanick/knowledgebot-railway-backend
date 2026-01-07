# Complete Integration Guide - KnowledgeBot Backend

**Step-by-step guide to set up and integrate all backend services.**

---

## 📋 Overview

This guide covers the complete setup for:
- **Firebase Authentication + Firestore** - User authentication and user data
- **PostgreSQL (Railway)** - Business data (OAuth credentials, human agents, feedback, etc.)
- **Gmail OAuth2** - Email sending for human agent notifications
- **Configuration Service** - Chatbot and widget configuration management
- **Chatbot Orchestration** - AI chat processing with system prompts and response policies

**Architecture**:
- **Firebase Auth**: User login/authentication (email/password, Google OAuth)
- **Firestore**: User data (`users` collection) + Email OAuth credentials (`email_config/gmail_oauth`)
- **PostgreSQL**: Business data (human agents, feedback, configuration)
- **Railway**: Hosting for all backend services

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
- `human_agents` table - Human agent management
- `human_agent_sessions` table - Agent-customer chat sessions
- `chat_feedback` table - User feedback on chat responses
- `token_usage_cache` table - LLM token usage tracking
- Updates `chatbot_configuration` table with new columns (response_policy, system_prompt, selected_persona)

**Note**: Email OAuth credentials are stored in Firestore, not PostgreSQL.

**Verification**:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('human_agents', 'chat_feedback', 'token_usage_cache');
```

---

## 🔧 STEP 2: Set Up Firebase Authentication and Firestore

### 2.1 Create Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click **Add project** → Enter name: `KnowledgeBot`
3. Enable **Firestore Database**:
   - Go to **Firestore Database** → **Create database**
   - Start in **Production mode** (or Test mode for development)
   - Choose location (closest to your users)
4. Go to **Authentication** → **Get started**
5. Enable **Email/Password** sign-in method
6. (Optional) Enable **Google** sign-in for OAuth

### 2.2 Get Firebase Service Account

1. Go to **Project Settings** (gear icon) → **Service accounts**
2. Click **Generate new private key**
3. Download JSON file (e.g., `knowledgebot-firebase-adminsdk.json`)
4. **Keep this file secure** - it has admin access

### 2.3 Configure Firestore Security Rules

Go to **Firestore Database** → **Rules** and add:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Users collection - users can read/write their own data
    match /users/{userId} {
      allow read: if request.auth != null && request.auth.uid == userId;
      allow write: if request.auth != null && request.auth.uid == userId;
      // Admins can read/write any user
      allow read, write: if request.auth != null && 
        get(/databases/$(database)/documents/users/$(request.auth.uid)).data.role == 'admin';
    }
    
    // Email config - only Admin SDK can access (server-side only)
    match /email_config/{document} {
      allow read, write: if false; // Only Admin SDK can access
    }
    
    // Deny all other access by default
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

**Note**: These rules ensure users can only access their own data, and admins can access all user data.

### 2.4 Configure Firebase Auth

**Authentication Methods to Enable**:
- Email/Password (for admin and human agents)
- Google (optional, for OAuth login)

**Note**: User data is stored in Firestore `users` collection, linked to Firebase Auth UIDs.

---

## 🔧 STEP 3: Get Gmail OAuth2 Credentials and Store in Firestore

**Note**: OAuth credentials for email sending are stored in Firestore.

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

### 3.3 Store Credentials in Firestore

After getting Client ID, Secret, and Refresh Token, store them in Firestore:

1. Go to **Firestore Database** in Firebase Console
2. Create collection: `email_config`
3. Create document: `gmail_oauth`
4. Add these fields:
   - `client_id`: `your-client-id.apps.googleusercontent.com`
   - `client_secret`: `GOCSPX-your-client-secret`
   - `refresh_token`: `your-refresh-token-here`

**⚠️ These credentials are stored in Firestore, not PostgreSQL.**

---

## 🔧 STEP 4: Create Configuration Service in Railway

### 4.1 Create Service

1. Railway Dashboard → Your Project
2. Click **+ New** → **GitHub Repo** (select `knowledgebot-railway-backend`)
3. Service name: `configuration-service` (exact, with hyphen)

### 4.2 Configure Service Settings

1. **Settings** → **Build**:
   - **Root Directory**: `.` (dot - repository root) ⚠️ **CRITICAL**
   - **Dockerfile Path**: `services/configuration_service/Dockerfile`
2. **Settings** → **Networking**:
   - **Port**: `8004` (auto-detected)
   - **Public Domain**: ❌ **NO** (keep private/internal)
3. **Settings** → **Resources**:
   - **CPU**: `0.5 vCPU` (default)
   - **Memory**: `512 MB` (default)

### 4.3 Set Environment Variables

Go to **Variables** tab → **RAW Editor** → Paste:

```env
# Database Connection (REQUIRED)
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}

# Service Port (REQUIRED)
CONFIGURATION_SERVICE_PORT=8004
PORT=8004

# Firebase Authentication and Firestore (REQUIRED)
FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"your-project-id","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"firebase-adminsdk-xxxxx@your-project.iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/..."}
# OR use file path instead:
# FIREBASE_CREDENTIALS_PATH=/path/to/service-account.json

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
- Replace `FIREBASE_CREDENTIALS_JSON` with entire JSON from service account file (as single-line string, escape newlines with `\n`)
- Replace `your-email@gmail.com` with Gmail address used for OAuth
- Replace API keys with actual keys
- Replace `https://widget.yourdomain.com` with your widget URL
- **OAuth credentials** (Client ID, Secret, Refresh Token) are stored in PostgreSQL `email_oauth_credentials` table, not environment variables

---

## 🔧 STEP 5: Update API Gateway

### 5.1 Add Environment Variable

1. Go to **API Gateway** service → **Variables** tab
2. Add:
```env
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
```

### 5.2 Verify All Service URLs

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

## 🔧 STEP 6: Verify Chatbot Orchestration Service

### 6.1 Check Environment Variables

Go to **Chatbot Orchestration** service → **Variables** → Verify:
```env
GEMINI_API_KEY=your-key
OPENAI_API_KEY=your-key
DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
```

**No new variables needed** - code already supports `system_prompt` and `response_policy`.

---

## 🔧 STEP 7: Deploy and Test

### 7.1 Deploy Services

1. **Configuration Service**: Should auto-deploy after creation
2. **API Gateway**: May need manual redeploy after adding variable
3. **Chatbot Orchestration**: Should auto-deploy (code changes in repo)

### 7.2 Check Service Health

1. Each service → **Deployments** tab → Verify **Active** and **Healthy**
2. Check **Logs** tab for errors

### 7.3 Test Endpoints

Get your API Gateway URL from Railway (e.g., `api-gateway-production-c4c3.up.railway.app`)

**Test Configuration**:
```bash
curl https://your-api-gateway.up.railway.app/api/v1/configuration/chatbot
```

**Test Authentication**:
```bash
curl -X POST https://your-api-gateway.up.railway.app/api/v1/auth/verify-token \
  -H "Content-Type: application/json" \
  -d '{"id_token": "your-firebase-token"}'
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

**Test Human Agent**:
```bash
curl -X POST https://your-api-gateway.up.railway.app/api/v1/admin/human-agents \
  -H "Content-Type: application/json" \
  -d '{"emails": ["test@example.com"]}'
```

---

## ✅ Complete Checklist

### Database
- [ ] Database migrations executed successfully
- [ ] Tables created: `human_agents`, `chat_feedback`, `token_usage_cache`
- [ ] `chatbot_configuration` table updated with new columns

### Firebase Authentication and Firestore
- [ ] Firebase project created
- [ ] Firestore Database enabled
- [ ] Firestore security rules configured
- [ ] Authentication enabled (Email/Password, Google optional)
- [ ] Service account JSON downloaded
- [ ] `FIREBASE_CREDENTIALS_JSON` or `FIREBASE_CREDENTIALS_PATH` set in Railway

### Gmail OAuth2
- [ ] Gmail OAuth2 credentials obtained (Client ID, Secret, Refresh Token)
- [ ] Firestore collection `email_config` created
- [ ] Firestore document `gmail_oauth` created with credentials
- [ ] Gmail API enabled in Google Cloud Console

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
- [ ] `FIREBASE_CREDENTIALS_JSON` (entire JSON as single-line string) OR `FIREBASE_CREDENTIALS_PATH`
- [ ] `SMTP_HOST=smtp.gmail.com`
- [ ] `SMTP_PORT=587`
- [ ] `SMTP_USER=your-email@gmail.com`
- [ ] `EMAIL_FROM=noreply@knowledgebot.com`
- [ ] `WIDGET_BASE_URL=https://widget.yourdomain.com`
- [ ] `GEMINI_API_KEY`
- [ ] `OPENAI_API_KEY`

### Testing
- [ ] Configuration endpoint returns 200
- [ ] Authentication endpoint works
- [ ] Feedback endpoint works
- [ ] Token usage endpoint works
- [ ] Human agent email sent successfully
- [ ] Frontend can connect to all endpoints

---

## 🐛 Troubleshooting

### Firebase Not Initializing
- Check `FIREBASE_CREDENTIALS_JSON` is valid JSON (no extra quotes)
- Verify JSON is complete (all fields present)
- Check JSON is properly escaped (newlines as `\n`)
- Verify service account has Firestore permissions

### OAuth Credentials Not Found
- Verify Firestore collection: `email_config`
- Verify document: `gmail_oauth`
- Check field names: `client_id`, `client_secret`, `refresh_token`
- Check credentials are not empty strings
- Verify Firestore security rules allow Admin SDK access

### Email Not Sending
- Check OAuth credentials in Firestore: `email_config/gmail_oauth` document
- Verify refresh token is valid (not expired)
- Check `SMTP_USER` matches Gmail account used for OAuth
- Check Railway logs for OAuth errors
- Verify Gmail API is enabled in Google Cloud Console
- Verify credentials are properly set in Firestore (not empty strings)
- Check Firestore security rules allow Admin SDK access

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

### Authentication Errors
- Verify Firebase credentials are set correctly
- Check Firestore security rules are configured
- Verify user exists in Firebase Auth
- Check Railway logs for Firebase initialization errors

---

## 📚 Quick Reference

**Service Names** (exact, case-sensitive):
- `api-gateway`
- `configuration-service`
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

**Database Variable**: `${{PostgreSQL.DATABASE_URL}}` in Railway

**Firebase**: Authentication + Firestore for user data and OAuth credentials

**PostgreSQL**: Business data (human agents, feedback, configuration)

---

## 🎯 Summary

1. **Run SQL migrations** on PostgreSQL
2. **Set up Firebase Authentication and Firestore**
   - Create Firebase project
   - Enable Firestore Database
   - Configure Firestore security rules
   - Enable Email/Password authentication
   - Get service account JSON
3. **Get Gmail OAuth2 credentials** (Client ID, Secret, Refresh Token)
4. **Store OAuth credentials in Firestore** (`email_config/gmail_oauth` document)
5. **Create Configuration Service** in Railway
6. **Set environment variables** (Database, Firebase Auth/Firestore, SMTP, API keys)
7. **Update API Gateway** with `CONFIGURATION_SERVICE_URL`
8. **Deploy and test** all endpoints

**That's it!** Follow the checklist above to verify everything is working.

**Important**:
- **Firebase Auth**: User authentication (login/signup)
- **Firestore**: Stores user data (`users` collection) and OAuth credentials (`email_config/gmail_oauth`)
- **PostgreSQL**: Stores business data (human agents, feedback, configuration)
