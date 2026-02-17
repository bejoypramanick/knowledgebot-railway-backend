# Railway Setup - Quick Start (5 Steps)

Ultra-fast reference guide. For detailed instructions, see `RAILWAY_DETAILED_SETUP.md`.

---

## ⚡ Quick Summary

You need to deploy **3 services** to Railway in this order:
1. **Redis** (message broker)
2. **celery-file-worker** (file processing)
3. **celery-web-worker** (website scraping)

Then set **3 environment variables** on each worker.

---

## 🚀 The 5 Steps

### STEP 1: Deploy Redis (5 minutes)

```
1. Go to: https://railway.app (your project)
2. Click: "New Service"
3. Select: "GitHub Repo"
4. Set:
   - Repository: your-repo/knowledgebot-railway-backend
   - Root Directory: redis
   - Service Name: redis
5. Click: "Deploy"
6. Wait: 3-5 minutes until Status = "Success"
```

✅ **Verify:** Click redis → Logs → Should see "Ready to accept connections"

---

### STEP 2: Deploy File Worker (5 minutes)

```
1. Go to: https://railway.app (your project)
2. Click: "New Service"
3. Select: "GitHub Repo"
4. Set:
   - Repository: your-repo/knowledgebot-railway-backend
   - Root Directory: celery-file-worker
   - Service Name: celery-file-worker
5. Click: "Deploy"
6. Wait: 3-5 minutes until Status = "Success"
```

✅ **Verify:** Click celery-file-worker → Logs → Should see "celery@" message

---

### STEP 3: Deploy Web Worker (5 minutes)

```
1. Go to: https://railway.app (your project)
2. Click: "New Service"
3. Select: "GitHub Repo"
4. Set:
   - Repository: your-repo/knowledgebot-railway-backend
   - Root Directory: celery-web-worker
   - Service Name: celery-web-worker
5. Click: "Deploy"
6. Wait: 3-5 minutes until Status = "Success"
```

✅ **Verify:** Click celery-web-worker → Logs → Should see "celery@" message

---

### STEP 4: Set Environment Variables (3 minutes)

**Get these values first:**

From **api_gateway** service (Variables tab):
- Copy: `RAILWAY_POSTGRES_URL`
- Copy: `GEMINI_API_KEY`

---

#### 4A: File Worker Variables

Click: **celery-file-worker** → Variables

Add these **3 variables:**

| Key | Value |
|-----|-------|
| `REDIS_URL` | `redis://redis.railway.internal:6379/0` |
| `RAILWAY_POSTGRES_URL` | (paste from api_gateway) |
| `GEMINI_API_KEY` | (paste from api_gateway) |

💾 **Save** → Service auto-restarts

---

#### 4B: Web Worker Variables

Click: **celery-web-worker** → Variables

Add these **3 variables:**

| Key | Value |
|-----|-------|
| `REDIS_URL` | `redis://redis.railway.internal:6379/1` ← **DB 1!** |
| `RAILWAY_POSTGRES_URL` | (paste from api_gateway) |
| `GEMINI_API_KEY` | (paste from api_gateway) |

💾 **Save** → Service auto-restarts

---

#### 4C: Existing Services (If not set)

**knowledgebase_ingestion:**
- Click service → Variables
- Add: `REDIS_URL` = `redis://redis.railway.internal:6379/0`

**website_crawling:**
- Click service → Variables
- Add: `REDIS_URL` = `redis://redis.railway.internal:6379/1`

---

### STEP 5: Test It Works (2 minutes)

#### Test File Upload:
```
1. Go to your UI
2. Upload a small file (< 10MB)
3. Watch file-worker logs (should process in 2-5 min)
4. Status should change to "completed"
5. File appears in search ✅
```

#### Test Website Scraping:
```
1. Go to your UI
2. Add a website URL
3. Watch web-worker logs (should process in 5-30 min)
4. Status should change to "completed"
5. Website appears in search ✅
```

---

## ⏱️ Timeline

| Step | Time | Total |
|------|------|-------|
| Deploy Redis | 5 min | 5 min |
| Deploy File Worker | 5 min | 10 min |
| Deploy Web Worker | 5 min | 15 min |
| Set Variables | 3 min | 18 min |
| Test | 5 min | 23 min |

**Total: ~25 minutes** ✅

---

## ✅ Verification Checklist

After all steps, verify:

- [ ] All 3 services show "Success" status
- [ ] No red errors in any logs
- [ ] File worker logs show "celery@" message
- [ ] Web worker logs show "celery@" message
- [ ] File upload → status changes to "completed"
- [ ] Website add → status changes to "completed"
- [ ] Search shows file and website results

When all checked → **FULLY WORKING!** 🎉

---

## 🆘 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Service shows "Build Failed" | Check repo path is correct |
| Workers show "Success" but logs say "connection refused" | Check REDIS_URL variable is set correctly |
| Tasks not processing | Verify all 3 variables are set on workers |
| Tasks slow | Check if large file/website, check logs for errors |

For more help → See `RAILWAY_DETAILED_SETUP.md`

---

## 📍 Important Notes

⚠️ **DO NOT:**
- Mix up the REDIS_URL databases (File=0, Web=1)
- Skip setting environment variables
- Deploy workers before Redis

✅ **DO:**
- Deploy in order: Redis → File Worker → Web Worker
- Copy-paste environment values exactly
- Wait for each service to show "Success" before next step

---

## 🎯 Key Values Reference

**These are examples - copy from YOUR Railway dashboard:**

```
REDIS_URL (File Worker) = redis://redis.railway.internal:6379/0
REDIS_URL (Web Worker)  = redis://redis.railway.internal:6379/1
RAILWAY_POSTGRES_URL    = postgresql://user:pass@host:5432/db?sslmode=require
GEMINI_API_KEY          = AIzaSyD... (your actual key)
```

---

## 📚 Full Documentation

For detailed instructions with screenshots:
- 📖 `RAILWAY_DETAILED_SETUP.md` - Step-by-step with explanations
- 📖 `DEPLOYMENT_READY.md` - Overall architecture
- 📖 `celery-file-worker/README.md` - File worker specifics
- 📖 `celery-web-worker/README.md` - Web worker specifics

---

## 🎉 You're All Set!

Everything you need is deployed and configured.

**Next:** Follow the 5 steps above and you're done! 🚀
