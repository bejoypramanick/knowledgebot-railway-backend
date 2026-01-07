# Firebase OAuth Setup Guide for Gmail Email Service

This guide shows you how to use Firebase to manage Gmail OAuth2 credentials securely.

**⚠️ IMPORTANT**: Firebase is used **ONLY** for storing OAuth credentials. All application data (human agents, feedback, sessions) is stored in PostgreSQL (Railway).

## 📋 Why Use Firebase for OAuth?

- **Secure Storage**: OAuth credentials stored in Firebase Firestore (encrypted)
- **Easy Management**: Update credentials without redeploying
- **Centralized**: Manage credentials from Firebase Console
- **Audit Trail**: Track credential changes in Firebase
- **Separation of Concerns**: OAuth credentials separate from application data

## 🔧 Step 1: Set Up Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click **Add project** or select existing project
3. Follow the setup wizard
4. Enable **Firestore Database**:
   - Go to **Firestore Database** → **Create database**
   - Start in **Production mode** (or Test mode for development)
   - Choose a location

## 🔧 Step 2: Get Firebase Service Account

1. Go to **Project Settings** (gear icon) → **Service accounts**
2. Click **Generate new private key**
3. Download the JSON file (e.g., `knowledgebot-firebase-adminsdk.json`)
4. **IMPORTANT**: Keep this file secure - it has admin access

## 🔧 Step 3: Set Up Firestore Collection (OAuth Credentials Only)

**⚠️ NOTE**: This Firestore collection is ONLY for OAuth credentials. All application data (human agents, feedback, etc.) is stored in PostgreSQL.

1. Go to **Firestore Database** in Firebase Console
2. Create a collection: `email_config`
3. Create a document: `gmail_oauth`
4. Add these fields:
   ```
   client_id: "your-client-id.apps.googleusercontent.com"
   client_secret: "GOCSPX-your-client-secret"
   refresh_token: "your-refresh-token-here"
   ```

**This is the ONLY data stored in Firestore.** All other data uses PostgreSQL.

### Security Rules (Important!)

Add Firestore security rules to protect credentials:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Only allow server-side access (Firebase Admin SDK)
    match /email_config/{document} {
      allow read, write: if false; // Only Admin SDK can access
    }
  }
}
```

**Note**: These rules prevent client-side access. Only Firebase Admin SDK (server-side) can read/write.

## 🔧 Step 4: Get Gmail OAuth2 Credentials

Follow the steps in `GMAIL_OAUTH2_SETUP.md` to get:
- Client ID
- Client Secret
- Refresh Token

Then add them to Firestore as described in Step 3.

## 🔧 Step 5: Configure Railway Environment Variables

In your Railway **Configuration Service**, set these variables:

### Option A: Using Firebase Service Account JSON File

1. Upload the service account JSON to Railway:
   - Go to **Variables** tab
   - Add variable: `FIREBASE_CREDENTIALS_JSON`
   - Paste the entire JSON content (as a single-line string)

2. Set other variables:
```env
# Firebase Configuration
USE_FIREBASE_OAUTH=true
FIREBASE_PROJECT_ID=your-firebase-project-id

# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com
```

### Option B: Using Firebase Credentials File Path

If you store the JSON file in your repository (not recommended for production):

```env
USE_FIREBASE_OAUTH=true
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-credentials.json
FIREBASE_PROJECT_ID=your-firebase-project-id

# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com
```

### Option C: Using Google Cloud Default Credentials

If running on Google Cloud (Railway doesn't support this by default):

```env
USE_FIREBASE_OAUTH=true
FIREBASE_PROJECT_ID=your-firebase-project-id
# No credentials path needed - uses default credentials
```

## 🔧 Step 6: Update OAuth Credentials in Firestore

You can update OAuth credentials anytime without redeploying:

1. Go to Firebase Console → Firestore Database
2. Navigate to `email_config` → `gmail_oauth`
3. Update the fields:
   - `client_id`
   - `client_secret`
   - `refresh_token`
4. Changes take effect immediately (no restart needed)

## ✅ Verification

1. Check Railway logs for "Firebase initialized successfully"
2. Test sending an email (add a test human agent)
3. Verify email is received

## 🔄 Updating Credentials

### Update Refresh Token (if expired):

1. Generate new refresh token (see `GMAIL_OAUTH2_SETUP.md`)
2. Go to Firebase Console → Firestore
3. Update `email_config/gmail_oauth` document
4. Update `refresh_token` field
5. No restart needed - service will use new token on next email

### Update Client ID/Secret:

1. Get new credentials from Google Cloud Console
2. Update in Firestore: `email_config/gmail_oauth`
3. Update `client_id` and `client_secret` fields
4. No restart needed

## 🔒 Security Best Practices

1. **Never commit Firebase credentials to git**
   - Use Railway environment variables
   - Store JSON as environment variable, not file

2. **Restrict Firestore access**
   - Use security rules to prevent client access
   - Only Admin SDK should access credentials

3. **Rotate credentials periodically**
   - Update refresh token every 90 days
   - Regenerate service account keys if compromised

4. **Monitor access**
   - Check Firebase Console → Usage for access logs
   - Set up alerts for unusual activity

## 🐛 Troubleshooting

### "Firebase not initialized"

- Check `FIREBASE_CREDENTIALS_JSON` is set correctly
- Verify JSON is valid (no extra quotes or escaping issues)
- Check `FIREBASE_PROJECT_ID` matches your Firebase project

### "OAuth credentials not found in Firestore"

- Verify collection name: `email_config`
- Verify document name: `gmail_oauth`
- Check field names: `client_id`, `client_secret`, `refresh_token`
- Verify Firestore security rules allow Admin SDK access

### "Failed to obtain OAuth2 access token"

- Check credentials in Firestore are correct
- Verify refresh token is valid
- Check Gmail API is enabled in Google Cloud Console

## 📊 Firestore Document Structure

**This is the ONLY data in Firestore** - OAuth credentials only:

```
email_config (collection)
  └── gmail_oauth (document)
      ├── client_id: "xxxxx.apps.googleusercontent.com"
      ├── client_secret: "GOCSPX-xxxxx"
      └── refresh_token: "1//xxxxx"
```

## 📊 PostgreSQL Tables (Application Data)

All application data is stored in PostgreSQL (Railway):

- `human_agents` - Human agent information
- `human_agent_sessions` - Agent-customer chat sessions
- `chat_feedback` - User feedback on messages
- `token_usage_cache` - Token usage statistics
- `chatbot_configuration` - Chatbot settings
- `widget_configuration` - Widget settings

**Firebase is NOT used for application data storage.**

---

**Need Help?** Check Railway logs for detailed error messages.

