# Railway Deployment - Detailed Step-by-Step Instructions

Complete guide with exact clickable steps for setting up Redis and Celery workers on Railway.

---

## Prerequisites

Before starting, have these ready:
- [ ] Railway.com account
- [ ] Access to your Railway project
- [ ] PostgreSQL connection URL (should already be in Railway)
- [ ] Gemini API key
- [ ] Railway CLI installed: `npm install -g @railway/cli`

---

## Part 1: Verify Your Current Setup

### Step 1.1: Check Existing Services on Railway

1. **Go to Railway Dashboard**
   - Visit: https://railway.app
   - Click your project (knowledgebot or whatever you named it)

2. **View Current Services**
   - You should see these services already:
     - ✅ api_gateway
     - ✅ chatbot_orchestration
     - ✅ configuration
     - ✅ docling_service
     - ✅ health_monitoring
     - ✅ knowledgebase_ingestion
     - ✅ website_crawling

3. **Find Your PostgreSQL URL**
   - Click on any service (e.g., api_gateway)
   - Click "Variables" tab
   - Look for: `RAILWAY_POSTGRES_URL` or `DATABASE_URL`
   - **Copy this value** - you'll need it later
   - Example: `postgresql://user:password@host:port/dbname?sslmode=require`

4. **Find Your Gemini API Key**
   - Click "Variables" tab
   - Look for: `GEMINI_API_KEY`
   - **Copy this value** - you'll need it later

---

## Part 2: Deploy Redis Service

### Step 2.1: Create Redis Service

**Method A: Using Railway Dashboard (Recommended)**

1. **Go to your Railway Project**
   - https://railway.app → Your Project

2. **Click "New Service"**
   - Top right area, or click the "+" button
   - Select: "GitHub Repo"

3. **Configure Service**
   - **Repository**: Select `ecommbalaji/knowledgebot-railway-backend` (or your fork)
   - **Root Directory**: `redis`
   - **Service Name**: `redis`
   - Click "Deploy"

4. **Wait for Deployment**
   - This will take 3-5 minutes
   - Status should change from "Building" → "Success"
   - Go grab a coffee ☕

5. **Verify Redis Started**
   - Click on the "redis" service in the dashboard
   - Click "Logs" tab
   - Look for messages like:
     ```
     Ready to accept connections
     The server is now ready to accept connections
     ```

### Step 2.2: Alternative - Using Railway CLI

If you prefer command line:

```bash
cd knowledgebot-railway-backend

# Login to Railway
railway login

# Link to your project
railway link

# Deploy redis service
cd redis
railway up --name redis

# Wait for it to finish
# Status: "Success"
```

---

## Part 3: Deploy Celery File Worker

### Step 3.1: Create File Worker Service

**Using Railway Dashboard**

1. **Go to your Railway Project**
   - https://railway.app → Your Project

2. **Click "New Service"**
   - Select: "GitHub Repo"

3. **Configure Service**
   - **Repository**: `ecommbalaji/knowledgebot-railway-backend`
   - **Root Directory**: `celery-file-worker`
   - **Service Name**: `celery-file-worker`
   - Click "Deploy"

4. **Wait for Deployment**
   - Takes 3-5 minutes
   - Status should show "Success"

5. **Verify Worker Started**
   - Click on "celery-file-worker" service
   - Click "Logs" tab
   - Look for:
     ```
     [config]
     .> app:         knowledgebase_ingestion
     .> transport:   redis://...
     .> concurrency: 2

     [queues]
     .> file_processing

     celery@hostname ready.
     ```

---

## Part 4: Deploy Celery Web Worker

### Step 4.1: Create Web Worker Service

**Using Railway Dashboard**

1. **Go to your Railway Project**
   - https://railway.app → Your Project

2. **Click "New Service"**
   - Select: "GitHub Repo"

3. **Configure Service**
   - **Repository**: `ecommbalaji/knowledgebot-railway-backend`
   - **Root Directory**: `celery-web-worker`
   - **Service Name**: `celery-web-worker`
   - Click "Deploy"

4. **Wait for Deployment**
   - Takes 3-5 minutes
   - Status should show "Success"

5. **Verify Worker Started**
   - Click on "celery-web-worker" service
   - Click "Logs" tab
   - Look for:
     ```
     [config]
     .> app:         website_crawling
     .> transport:   redis://...
     .> concurrency: 1

     [queues]
     .> web_crawling

     celery@hostname ready.
     ```

---

## Part 5: Set Environment Variables

This is **CRITICAL** - the workers won't work without proper environment variables.

### Step 5.1: Get Redis Internal URL

1. **Click on "redis" service in dashboard**

2. **Click "Variables" tab**

3. **Look for connection info**
   - Railway will show the Redis connection details
   - Default internal URL format: `redis://redis.railway.internal:6379`
   - You may need to copy from logs or service page

4. **Note the URLs**
   - For file worker: `redis://redis.railway.internal:6379/0`
   - For web worker: `redis://redis.railway.internal:6379/1`

### Step 5.2: Set Variables on File Worker

1. **Click "celery-file-worker" service**

2. **Click "Variables" tab**

3. **Add each variable (click "New Variable")**

   **Variable 1:**
   - Key: `REDIS_URL`
   - Value: `redis://redis.railway.internal:6379/0`
   - Click "Add"

   **Variable 2:**
   - Key: `RAILWAY_POSTGRES_URL`
   - Value: (paste the URL you copied earlier from api_gateway)
   - Example: `postgresql://user:pass@host:5432/db?sslmode=require`
   - Click "Add"

   **Variable 3:**
   - Key: `GEMINI_API_KEY`
   - Value: (paste your Gemini API key)
   - Click "Add"

4. **Restart Service**
   - Service should auto-restart after variables are saved
   - Watch logs to see it reconnect to Redis

### Step 5.3: Set Variables on Web Worker

Repeat the same process for web worker:

1. **Click "celery-web-worker" service**

2. **Click "Variables" tab**

3. **Add each variable**

   **Variable 1:**
   - Key: `REDIS_URL`
   - Value: `redis://redis.railway.internal:6379/1` ← **Note: DB 1, not 0!**
   - Click "Add"

   **Variable 2:**
   - Key: `RAILWAY_POSTGRES_URL`
   - Value: (same as file worker)
   - Click "Add"

   **Variable 3:**
   - Key: `GEMINI_API_KEY`
   - Value: (same as file worker)
   - Click "Add"

4. **Restart Service**
   - Service should auto-restart

### Step 5.4: Verify Environment Variables on Existing Services

Update your **existing services** to use Redis (if not already set):

**For knowledgebase_ingestion:**
1. Click "knowledgebase_ingestion" service
2. Click "Variables" tab
3. Add/Update:
   - Key: `REDIS_URL`
   - Value: `redis://redis.railway.internal:6379/0`
4. Save

**For website_crawling:**
1. Click "website_crawling" service
2. Click "Variables" tab
3. Add/Update:
   - Key: `REDIS_URL`
   - Value: `redis://redis.railway.internal:6379/1`
4. Save

---

## Part 6: Verify All Services Are Running

### Step 6.1: Check Dashboard Status

1. **Go to Railway project dashboard**

2. **Verify all services show "Success":**
   - [ ] api_gateway - Success
   - [ ] chatbot_orchestration - Success
   - [ ] configuration - Success
   - [ ] docling_service - Success
   - [ ] health_monitoring - Success
   - [ ] knowledgebase_ingestion - Success
   - [ ] website_crawling - Success
   - [ ] **redis** - Success ✨ NEW
   - [ ] **celery-file-worker** - Success ✨ NEW
   - [ ] **celery-web-worker** - Success ✨ NEW

If any show "Build Failed" or "Crashed":
- Click the service
- Click "Logs"
- Look for error messages
- Common fixes:
  - Missing environment variables → Add them
  - Redis not running → Deploy Redis first
  - Wrong service order → Deploy Redis before workers

### Step 6.2: Check Redis Connection

1. **Click "redis" service**
2. **Click "Logs" tab**
3. **Look for:**
   ```
   Ready to accept connections
   ```

### Step 6.3: Check File Worker Connection to Redis

1. **Click "celery-file-worker" service**
2. **Click "Logs" tab**
3. **Look for:**
   ```
   ✅ [REDIS] Connection test successful
   ```
   OR
   ```
   celery@hostname ready.
   ```

If you see:
```
❌ [REDIS] Connection test failed - Connection refused
```
→ Redis not running or REDIS_URL is wrong

### Step 6.4: Check Web Worker Connection to Redis

1. **Click "celery-web-worker" service**
2. **Click "Logs" tab**
3. **Look for:**
   ```
   ✅ [REDIS] Connection test successful
   ```
   OR
   ```
   celery@hostname ready.
   ```

---

## Part 7: Test File Upload

Now test if everything works!

### Step 7.1: Upload a Test File

1. **Go to your knowledgebot UI**
   - Visit your API Gateway URL
   - Go to the "Upload Files" section

2. **Upload a small test file**
   - PDF, DOCX, or HTML file
   - Something under 10MB for quick testing

3. **Note the file ID from response**
   - API should return something like:
     ```json
     {
       "file_id": 123,
       "status": "pending"
     }
     ```

### Step 7.2: Watch File Worker Process It

1. **Go to Railway dashboard**

2. **Click "celery-file-worker" service**

3. **Click "Logs" tab**

4. **Watch for task messages:**
   ```
   📋 [TASK] Starting Celery task for file ID 123
   🔄 [CELERY] Starting processing for file ID 123: test.pdf
   ✅ [CELERY] File ID 123 processing completed successfully
   ✅ [TASK] Celery task completed for file ID 123
   ```

   This should appear within **2-5 minutes**

### Step 7.3: Verify File Status Changed

1. **Check the database or API**
   ```
   GET /api/v1/knowledgebase/status/123
   ```

2. **Response should show:**
   ```json
   {
     "id": 123,
     "processing_status": "completed",
     "gemini_file_uri": "...uploaded to Gemini..."
   }
   ```

3. **Or query database directly**
   ```sql
   SELECT id, file_name, processing_status FROM file_uploads WHERE id = 123;
   ```
   Should show: `id=123, status='completed'`

---

## Part 8: Test Website Scraping

### Step 8.1: Add a Test Website

1. **Go to your knowledgebot UI**
   - Go to "Crawl Websites" section

2. **Add a simple website**
   - Start with a small site (10-20 pages)
   - Example: `https://example.com`
   - Or your own site

3. **Note the website ID from response**
   ```json
   {
     "website_id": 456,
     "status": "pending"
   }
   ```

### Step 8.2: Watch Web Worker Process It

1. **Go to Railway dashboard**

2. **Click "celery-web-worker" service**

3. **Click "Logs" tab**

4. **Watch for task messages:**
   ```
   📋 [TASK] Starting Celery task for website ID 456
   🔄 [CELERY] Starting scraping for website ID 456: https://example.com
   ✅ [CELERY] Website ID 456 scraped successfully
   ✅ [TASK] Celery task completed for website ID 456
   ```

   This should appear within **5-30 minutes** depending on site size

### Step 8.3: Verify Website Status Changed

1. **Check the API**
   ```
   GET /api/v1/webcrawl/status/456
   ```

2. **Response should show:**
   ```json
   {
     "id": 456,
     "url": "https://example.com",
     "processing_status": "completed"
   }
   ```

3. **Or query database**
   ```sql
   SELECT id, url, processing_status FROM scraped_websites WHERE id = 456;
   ```
   Should show: `id=456, status='completed'`

---

## Part 9: Verify Search Works

### Step 9.1: Search for Uploaded File

1. **Go to your chatbot UI**

2. **Search for content from the file you uploaded**
   - Example: If you uploaded a PDF about "machine learning"
   - Search: "machine learning"

3. **Should see results from your uploaded file**
   - Results should include the file as a source

### Step 9.2: Search for Website Content

1. **Search for content from the website you scraped**
   - Example: If you scraped "example.com"
   - Search: content that appears on example.com

2. **Should see results from the website**
   - Results should include the website as a source

---

## Part 10: Monitor in Production

### Step 10.1: Daily Monitoring

**Every morning, check:**

1. **All services running**
   - Dashboard should show all "Success"

2. **No recent errors**
   - Click each service → Logs
   - Look for any `[ERROR]` messages

3. **Queue depth**
   - Healthy: Queue depth = 0
   - If depth > 0: Tasks are processing

### Step 10.2: Check Specific Service Logs

**File Worker Health:**
```
Railway Dashboard → celery-file-worker → Logs
Look for:
- "celery@hostname ready" (healthy)
- No "ERROR" messages (good)
- New task logs appearing (active)
```

**Web Worker Health:**
```
Railway Dashboard → celery-web-worker → Logs
Look for:
- "celery@hostname ready" (healthy)
- No "ERROR" messages (good)
- New task logs appearing (active)
```

**Redis Health:**
```
Railway Dashboard → redis → Logs
Look for:
- No error messages
- "Ready to accept connections"
```

### Step 10.3: Monitor Performance

**Check if tasks are completing:**

1. **Upload a file**
2. **Check file-worker logs**
3. **Verify it shows "completed" within 5 minutes**

**If tasks are stuck:**

1. **Check Redis connection**
   - Verify REDIS_URL environment variable
   - Verify Redis service is running

2. **Check worker logs for errors**
   - Look for connection errors
   - Look for timeout errors

3. **Restart the worker**
   - Click service → Click "..." → "Redeploy"

---

## Part 11: Troubleshooting

### Problem: Workers Show "Build Failed"

**Check the build logs:**
1. Click the service
2. Click "Deployments" tab
3. Click the failed deployment
4. Click "Build Logs"

**Common causes:**
- Missing `railway.toml` file
- Wrong directory path in `railway.toml`
- Dockerfile not found

**Solution:**
- Verify files exist: `git log --oneline` should show your commits
- Check that `celery-file-worker/railway.toml` exists
- Check that `celery-web-worker/railway.toml` exists

### Problem: Workers Show "Success" But Logs Show "Connection Refused"

**Check Redis:**
1. Click "redis" service
2. Verify it shows "Success"
3. Check logs for errors

**Check environment variables:**
1. Click worker service
2. Click "Variables"
3. Verify REDIS_URL is set correctly
4. Format: `redis://redis.railway.internal:6379/0` (or `/1`)

**Fix:**
1. Update REDIS_URL variable
2. Click "Redeploy" on worker

### Problem: Tasks Not Processing (Queue Growing)

**Check if workers are alive:**
```
Railway Dashboard → celery-file-worker → Logs
Should see: "celery@hostname ready"
```

**Check if Redis has tasks:**
1. Click any existing service with Redis access
2. Connect to Railway database
3. Check queue depth

**Check worker logs for errors:**
```
Look for: [ERROR] or [FAILED] messages
Common: ImportError, ModuleNotFoundError, timeout
```

**Fix:**
1. Restart worker: Service → "..." → "Redeploy"
2. Check all environment variables are set
3. Verify Redis is running

### Problem: Timeouts (Tasks Running > 30 min for files)

**Check file worker logs:**
```
Look for: "Task timeout" or "deadline exceeded"
```

**Causes:**
- Very large file (> 100MB)
- Slow network
- Docling service not responding

**Solutions:**
1. Try with smaller file first
2. Check Docling service is running
3. Increase timeout in knowledgebase_ingestion/celery_app.py (if needed)

---

## Part 12: Quick Reference - Environment Variables

**Copy-paste these exactly:**

### File Worker (celery-file-worker)
```
REDIS_URL=redis://redis.railway.internal:6379/0
RAILWAY_POSTGRES_URL=(copy from api_gateway Variables)
GEMINI_API_KEY=(your gemini api key)
```

### Web Worker (celery-web-worker)
```
REDIS_URL=redis://redis.railway.internal:6379/1
RAILWAY_POSTGRES_URL=(copy from api_gateway Variables)
GEMINI_API_KEY=(your gemini api key)
```

### Existing Services (update if not set)

**knowledgebase_ingestion:**
```
REDIS_URL=redis://redis.railway.internal:6379/0
```

**website_crawling:**
```
REDIS_URL=redis://redis.railway.internal:6379/1
```

---

## Part 13: Expected Timelines

### Deployment Timeline

| Step | Time | Status |
|------|------|--------|
| Deploy Redis | 3-5 min | Building → Success |
| Deploy File Worker | 3-5 min | Building → Success |
| Deploy Web Worker | 3-5 min | Building → Success |
| Set Variables | 1 min | Variables saved |
| **Total** | **~15-20 min** | All running |

### Task Processing Timeline

| Task | Time | Notes |
|------|------|-------|
| Upload file | 2-5 min | Depends on file size |
| Status update | 1-2 sec | After task completes |
| Website single page | 2-5 min | Depends on page size |
| Website 10 pages | 15-30 min | Concurrent crawling |
| Website 50 pages | 1-1.5 hours | Large sitemap |

---

## Part 14: Success Checklist

After completing all steps:

- [ ] Redis service shows "Success"
- [ ] celery-file-worker shows "Success"
- [ ] celery-web-worker shows "Success"
- [ ] All services have REDIS_URL set
- [ ] Logs show "celery@hostname ready"
- [ ] Logs show "✅ [REDIS] Connection test successful"
- [ ] Upload test file → Status changes to "completed"
- [ ] Add test website → Status changes to "completed"
- [ ] Search finds uploaded file content
- [ ] Search finds website content
- [ ] No error messages in logs
- [ ] Queue depth = 0 (all tasks processed)

When all checkmarks are done → ✅ **FULLY DEPLOYED!**

---

## Summary

You now have:
1. ✅ Redis service for message broker
2. ✅ File worker for async file processing
3. ✅ Web worker for async website scraping
4. ✅ All environment variables configured
5. ✅ All services running and connected
6. ✅ Tested and verified working

**Everything is working end-to-end!** 🎉
