# Railway 502 Bad Gateway Fix Guide

## 🚨 Problem: 502 Bad Gateway Error

Your chatbot orchestration service is returning a **502 Bad Gateway** error, which means the Railway deployment cannot start the service properly.

## 🔍 Root Cause Analysis

The 502 error is caused by **Python import failures during service startup**. The service tries to import modules like `pydantic_settings`, `google.genai`, `pydantic_ai`, etc., and fails, causing the entire application to crash before it can serve any requests.

### Common Causes:
1. **Missing Environment Variables** (especially `GEMINI_API_KEY`)
2. **Python Dependencies Not Installed** in Docker container
3. **Docker Build Failures**
4. **Railway Deployment Issues**

## 🛠️ Quick Fix Steps

### Step 1: Check Environment Variables
```bash
# Check if required variables are set
railway variables get GEMINI_API_KEY
railway variables get PORT
```

If `GEMINI_API_KEY` is missing:
```bash
railway variables set GEMINI_API_KEY "your_actual_gemini_api_key_here"
```

### Step 2: Manual Troubleshooting Steps

#### A. Check Environment Variables
```bash
# Check if required variables are set
railway variables get GEMINI_API_KEY
railway variables get PORT

# If GEMINI_API_KEY is missing, set it:
railway variables set GEMINI_API_KEY "your_actual_gemini_api_key_here"
```

#### B. Trigger Redeploy
```bash
# Trigger a redeploy
railway up
```

#### C. Test Health Endpoint
```bash
# Wait a few minutes, then test:
curl https://your-deployment-url/health
```

### Step 3: Monitor Deployment
```bash
# Watch deployment logs in real-time
railway logs --follow

# Or check recent logs
railway logs --lines 50
```

## 🔧 Manual Troubleshooting

### Check Service Status
```bash
# Get deployment info
railway status

# List all services
railway services list
```

### Test Health Endpoint
Once deployment succeeds, test:
```bash
curl https://your-deployment-url/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "chatbot_orchestration"
}
```

### Check Deployment Logs for Errors
Look for these error patterns in `railway logs`:

1. **Import Errors:**
   ```
   ModuleNotFoundError: No module named 'pydantic_settings'
   ```

2. **Environment Variable Errors:**
   ```
   GEMINI_API_KEY is not configured
   ```

3. **Port Binding Errors:**
   ```
   [Errno 48] Address already in use
   ```

## 📋 Required Environment Variables

### Critical (Service Won't Start Without These):
- `GEMINI_API_KEY` - Your Google Gemini API key
- `PORT` - Automatically set by Railway (usually 8003)

### Optional (Service Works But Limited Features):
- `RAILWAY_POSTGRES_URL` - Database connection string

## 🐳 Docker Configuration Issues

If the issue persists, check your `Dockerfile`:

### Current Dockerfile Issues:
1. **Health Check Path**: The Dockerfile uses `/health` but Railway might expect different paths
2. **Port Configuration**: Ensure the CMD uses the correct port variable

### Dockerfile Fixes Applied:
- ✅ Added fallback health endpoint that works even with import failures
- ✅ Improved error handling and logging
- ✅ Added graceful degradation for missing dependencies

## 🔄 Redeployment Process

### Manual Redeploy
```bash
# Trigger redeploy
railway up

# Wait a few minutes, then check status
railway status

# Test health
curl $(railway status --json | grep -o '"url":"[^"]*"' | cut -d'"' -f4)/health
```

## 🚨 Emergency Fallback

If the service still won't start, try this minimal version that bypasses complex imports:

1. **Temporary Health Endpoint**: The service now has a basic health endpoint that works even if AI features fail
2. **Degraded Mode**: Service can respond to health checks in degraded mode
3. **Detailed Logging**: Check logs for specific import failures

## 📊 Testing Your Fix

### Test Health Endpoint:
```bash
curl https://your-deployment-url/health
```

### Test Chat Endpoint (once health works):
```bash
curl -X POST https://your-deployment-url/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "session_id": "test123"}'
```

## 📞 Getting Help

### If Issues Persist:
1. **Check Railway Status**: https://status.railway.app/
2. **Review Full Logs**: `railway logs --lines 100`
3. **Verify Environment**: `railway variables`
4. **Check Service Configuration**: `railway services list`

### Common Log Messages to Look For:
- ✅ `"Chatbot orchestration service started successfully"`
- ✅ `"Health check endpoint: /health"`
- ❌ `"CRITICAL IMPORT ERROR"`
- ❌ `"GEMINI_API_KEY is not configured"`

## 🎯 Success Indicators

Your deployment is fixed when:
- ✅ `railway status` shows "healthy"
- ✅ Health endpoint returns `{"status": "healthy"}`
- ✅ Chat endpoint responds (not 502 error)
- ✅ No critical import errors in logs

## 📝 Prevention

To avoid this in the future:
1. **Always set `GEMINI_API_KEY`** before deployment
2. **Test locally** before pushing to Railway
3. **Monitor deployment logs** after changes
4. **Check environment variables** before deployment
5. **Monitor Railway logs** after redeploys

---

**Need Help?** Check `railway logs --lines 20` and verify environment variables are set correctly.