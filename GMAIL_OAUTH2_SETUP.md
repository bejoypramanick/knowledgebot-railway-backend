# Gmail OAuth2 Setup Guide

This guide shows you how to set up Gmail OAuth2 authentication using Client ID, Client Secret, and Refresh Token. This is more secure than App Passwords because you can revoke access at any time.

## 📋 Prerequisites

1. A Google Account
2. Access to Google Cloud Console
3. A Gmail account to use for sending emails

## 🔧 Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Enter project name: `KnowledgeBot Email Service`
4. Click **Create**
5. Wait for project creation (takes a few seconds)

## 🔧 Step 2: Enable Gmail API

1. In your Google Cloud project, go to **APIs & Services** → **Library**
2. Search for **Gmail API**
3. Click on **Gmail API**
4. Click **Enable**

## 🔧 Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**
3. If prompted, configure OAuth consent screen first:
   - **User Type**: External (unless you have Google Workspace)
   - Click **Create**
   - **App name**: `KnowledgeBot Email Service`
   - **User support email**: Your email
   - **Developer contact information**: Your email
   - Click **Save and Continue**
   - **Scopes**: Click **Add or Remove Scopes**
     - Search for `gmail.send`
     - Check **.../auth/gmail.send**
     - Click **Update** → **Save and Continue**
   - **Test users**: Add your Gmail address
   - Click **Save and Continue** → **Back to Dashboard**

4. Now create OAuth Client ID:
   - **Application type**: **Web application**
   - **Name**: `KnowledgeBot SMTP`
   - **Authorized redirect URIs**: 
     - Add: `http://localhost:8080/oauth2callback` (for testing)
     - Add: `https://your-domain.com/oauth2callback` (if you have a domain)
   - Click **Create**
5. **IMPORTANT**: Copy these values immediately (you won't see them again):
   - **Client ID**: `xxxxx.apps.googleusercontent.com`
   - **Client Secret**: `GOCSPX-xxxxx`

## 🔧 Step 4: Generate Refresh Token

You need to generate a refresh token using the OAuth2 flow. Here's how:

### Option A: Using Python Script (Recommended)

1. Create a file `generate_refresh_token.py`:

```python
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes required for sending emails
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_refresh_token():
    creds = None
    
    # Create credentials.json with your Client ID and Secret
    # Format:
    # {
    #   "web": {
    #     "client_id": "YOUR_CLIENT_ID",
    #     "client_secret": "YOUR_CLIENT_SECRET",
    #     "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    #     "token_uri": "https://oauth2.googleapis.com/token",
    #     "redirect_uris": ["http://localhost:8080/oauth2callback"]
    #   }
    # }
    
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    print(f"Refresh Token: {creds.refresh_token}")
    return creds.refresh_token

if __name__ == '__main__':
    get_refresh_token()
```

2. Create `credentials.json`:
```json
{
  "web": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost:8080/oauth2callback"]
  }
}
```

3. Install required packages:
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

4. Run the script:
```bash
python generate_refresh_token.py
```

5. A browser window will open - sign in with your Gmail account
6. Grant permissions
7. Copy the **Refresh Token** from the output

### Option B: Using OAuth2 Playground (Easier)

1. Go to [OAuth2 Playground](https://developers.google.com/oauthplayground/)
2. Click the gear icon (⚙️) in top right
3. Check **Use your own OAuth credentials**
4. Enter your **Client ID** and **Client Secret**
5. In the left panel, find **Gmail API v1**
6. Select **https://www.googleapis.com/auth/gmail.send**
7. Click **Authorize APIs**
8. Sign in and grant permissions
9. Click **Exchange authorization code for tokens**
10. Copy the **Refresh token** (long string)

## 🔧 Step 5: Configure Railway Environment Variables

In your Railway **Configuration Service**, set these variables:

```env
# Gmail OAuth2 Credentials (REQUIRED)
GMAIL_OAUTH2_CLIENT_ID=your-client-id.apps.googleusercontent.com
GMAIL_OAUTH2_CLIENT_SECRET=GOCSPX-your-client-secret
GMAIL_OAUTH2_REFRESH_TOKEN=your-refresh-token-here

# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com
```

**⚠️ Important Notes:**
- `SMTP_USER` should be the Gmail address you authorized
- `GMAIL_OAUTH2_REFRESH_TOKEN` is the long token you generated
- Keep these credentials secure - never commit them to git

## ✅ Verification

After setting up, test the email service:

1. Add a test human agent in the admin panel
2. Check if confirmation email is received
3. Check Railway logs for any OAuth2 errors

## 🔒 Security Best Practices

1. **Never commit credentials to git** - Use Railway environment variables
2. **Rotate credentials periodically** - Generate new tokens every 90 days
3. **Revoke access if compromised** - Go to Google Account → Security → Third-party access
4. **Use separate Gmail account** - Don't use your personal email for production

## 🐛 Troubleshooting

### "Invalid Grant" Error
- Refresh token may have expired
- Generate a new refresh token
- Make sure you're using the correct Gmail account

### "Access Denied" Error
- Check OAuth consent screen is published (or you're a test user)
- Verify scopes include `gmail.send`
- Check the Gmail account has granted permissions

### "Authentication Failed" Error
- Verify Client ID and Secret are correct
- Check SMTP_USER matches the authorized Gmail account
- Ensure refresh token is valid

## 📚 Additional Resources

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth2 for Gmail](https://developers.google.com/gmail/api/auth/about-auth)
- [Google Cloud Console](https://console.cloud.google.com/)

---

**Need Help?** Check Railway logs for detailed error messages.

