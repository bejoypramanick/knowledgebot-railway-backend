# Convert Current Setup to Serverless - Exact Changes

Go from $25/month to $0-5/month by making these simple changes.

---

## ⚡ TL;DR - What You Do

1. **Get free Redis from Upstash** (5 min)
2. **Update REDIS_URL** in Railway (2 min)
3. **Add 1 line to railway.toml files** (1 min)
4. **Deploy** (5 min)

**Total: 13 minutes | Savings: $20-25/month**

---

## 🎯 The Changes

### Change 1: Replace Railway Redis with Upstash Redis

**WHERE:**
- Everything that used Railway Redis

**WHAT TO DO:**

1. Go to: https://upstash.com
2. Sign up (free, takes 1 minute)
3. Create Redis database (select **Free tier**)
4. Copy the Redis URL
5. Use it instead of Railway Redis

**EXAMPLE:**
```
Old: redis://redis.railway.internal:6379/0
New: redis://default:xxxxx@us1-yyyyy.upstash.io:6379/0
```

---

### Change 2: Update Environment Variables

**WHERE:**
- Every service that uses REDIS_URL

**SERVICES TO UPDATE:**
- knowledgebase_ingestion
- website_crawling
- celery-file-worker
- celery-web-worker

**WHAT TO DO:**

```
Old Value:  redis://redis.railway.internal:6379/0
New Value:  redis://default:AXxxxx@us1-yyyy.upstash.io:6379/0
            (Copy from Upstash dashboard)
```

**IN RAILWAY:**
1. Click service → Variables
2. Find REDIS_URL
3. Replace value with Upstash URL
4. Save (auto-restart)

---

### Change 3: Make Workers Serverless

**WHERE:**
- `celery-file-worker/railway.toml`
- `celery-web-worker/railway.toml`

**WHAT TO DO:**

Find this section:
```toml
[deploy]
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 1 --max-tasks-per-child=500"

restartPolicyType = "ON_FAILURE"
```

Add ONE line:
```toml
[deploy]
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 1 --max-tasks-per-child=500"

function = true  ← ADD THIS LINE

restartPolicyType = "ON_FAILURE"
```

That's it!

---

## 📝 Exact File Changes

### File: `celery-file-worker/railway.toml`

**CURRENT:**
```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."
watchPaths = ["celery-file-worker/"]

[deploy]
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2 --max-tasks-per-child=1000"

restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

healthcheckTimeout = 300
```

**NEW (Only change = add `function = true`):**
```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."
watchPaths = ["celery-file-worker/"]

[deploy]
startCommand = "celery -A knowledgebase_ingestion.celery_app worker -Q file_processing -l info -c 2 --max-tasks-per-child=1000"

function = true  ← ADD THIS

restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

healthcheckTimeout = 300
```

---

### File: `celery-web-worker/railway.toml`

**CURRENT:**
```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."
watchPaths = ["celery-web-worker/"]

[deploy]
startCommand = "celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 1 --max-tasks-per-child=100"

restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

healthcheckTimeout = 300
```

**NEW (Only change = add `function = true`):**
```toml
[build]
dockerfilePath = "Dockerfile.celery"
rootDirectory = ".."
watchPaths = ["celery-web-worker/"]

[deploy]
startCommand = "celery -A website_crawling.celery_app worker -Q web_crawling -l info -c 1 --max-tasks-per-child=100"

function = true  ← ADD THIS

restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

healthcheckTimeout = 300
```

---

## 🚀 Step-by-Step Implementation

### Step 1: Delete the Redis service (SAVE MONEY!)

```
Railway Dashboard → redis service
Click "..." → Delete service
Confirm deletion
```

**Save: $5/month**

---

### Step 2: Sign up for Upstash Redis (FREE)

```
1. Visit: https://upstash.com
2. Click "Sign Up"
3. Use Google/GitHub login
4. Create Database:
   - Name: knowledgebot-redis
   - Region: Closest to you
   - Plan: FREE (important!)
5. Click "Create Database"
6. Wait ~30 seconds
```

---

### Step 3: Get Upstash Redis URL

```
1. Upstash Dashboard → Click your database
2. Click "Connect"
3. Copy the connection string
4. Format: redis://default:xxxxx@us1-yyyyy.upstash.io:6379

This is your REDIS_URL!
```

---

### Step 4: Update Environment Variables

**For EACH service below:**

#### knowledgebase_ingestion
```
Railway → knowledgebase_ingestion → Variables
REDIS_URL = redis://default:xxxxx@us1-yyyyy.upstash.io:6379/0
Click Save (auto-restart)
```

#### website_crawling
```
Railway → website_crawling → Variables
REDIS_URL = redis://default:xxxxx@us1-yyyyy.upstash.io:6379/1
Click Save (auto-restart)
```

#### celery-file-worker
```
Railway → celery-file-worker → Variables
REDIS_URL = redis://default:xxxxx@us1-yyyyy.upstash.io:6379/0
Click Save
```

#### celery-web-worker
```
Railway → celery-web-worker → Variables
REDIS_URL = redis://default:xxxxx@us1-yyyyy.upstash.io:6379/1
Click Save
```

---

### Step 5: Update railway.toml Files

**Edit and commit these files:**

1. `celery-file-worker/railway.toml` → Add `function = true`
2. `celery-web-worker/railway.toml` → Add `function = true`

```bash
git add celery-file-worker/railway.toml celery-web-worker/railway.toml
git commit -m "Convert to serverless Celery workers"
git push
```

---

### Step 6: Redeploy Workers

```
Railway Dashboard → celery-file-worker
Click "..." → Redeploy

Railway Dashboard → celery-web-worker
Click "..." → Redeploy
```

**Wait 3-5 minutes for deployment**

---

### Step 7: Verify Everything Works

**Check logs:**
```
celery-file-worker → Logs → Should show "celery@hostname ready"
celery-web-worker → Logs → Should show "celery@hostname ready"
```

**Test upload:**
```
1. Upload a file
2. Worker logs should show task picked up
3. Wait 2-5 minutes
4. File should be searchable ✅
```

---

## 💰 Cost Impact

### BEFORE (Current Setup)
```
Redis (Railway):           $5/month
File Worker (always-on):   $10/month
Web Worker (always-on):    $10/month
─────────────────────────────────
TOTAL:                     $25/month
```

### AFTER (Serverless)
```
Redis (Upstash free):       $0/month
File Worker (serverless):   $0/month (under free tier)
Web Worker (serverless):    $0/month (under free tier)
─────────────────────────────────
TOTAL:                      $0/month

SAVINGS: $25/month! 💰
```

---

## ⚠️ What Changes for Users?

### Upload a file

**BEFORE:**
```
Click upload → Returns instantly
Background: Processing happens (2-5 min)
User searches later → File found ✅
```

**AFTER (Serverless):**
```
Click upload → Returns instantly (same)
Background: Processing happens (2-5 min + 15-30s cold start first time)
User searches later → File found ✅

Difference: First task might take 30s extra (cold start)
Subsequent tasks: No difference
```

**Real impact:** Barely noticeable

---

## 🔍 Monitoring Upstash Usage

### Check if You're Under Free Tier

```
Upstash Dashboard → Your database → Stats

Free tier includes:
- 10,000 commands/day
- Unlimited storage
- Unlimited connections

You'd have to work HARD to exceed this!
```

### If You Exceed Free Tier

```
Cost: $0.25 per 10,000 commands

Real example:
- 1000 file uploads/month: ~$1-2 extra
- 100 file uploads/month: ~$0 (under free tier)

Still saving $20+/month!
```

---

## ❓ Troubleshooting

### Workers won't connect to Redis

**Check:**
1. REDIS_URL is correct (copy from Upstash)
2. REDIS_URL is set on all 4 services
3. Services have restarted (wait 2 min after saving)
4. No typos in URL

**Fix:**
```
Copy URL exactly from Upstash dashboard
Paste into Railway Variables
Save and wait 2 minutes
Check logs for connection success
```

### Tasks not executing

**Check:**
1. Both workers show "celery@hostname ready" in logs
2. REDIS_URL on file-worker is `/0`
3. REDIS_URL on web-worker is `/1`
4. Tasks are being queued (check Upstash stats)

**Fix:**
- Restart workers: Click service → "..." → Redeploy
- Check all REDIS_URLs are correct
- Wait 2 minutes for restart

### Cold starts taking too long

**Expected:**
- First task: 15-30 seconds extra (cold start)
- Subsequent: Normal speed

**To keep function warm (optional):**
- Add a "ping" task every 10 minutes
- Cost: ~$0.10/month
- Or just accept occasional cold starts

---

## ✅ Verification Checklist

After all changes:

- [ ] Upstash Redis account created
- [ ] Upstash Redis URL copied
- [ ] Railway Redis service deleted
- [ ] REDIS_URL updated on 4 services
- [ ] railway.toml files updated with `function = true`
- [ ] Changes committed and pushed
- [ ] Workers redeployed
- [ ] Logs show "celery@hostname ready"
- [ ] File upload works
- [ ] File appears searchable after 2-5 min

When all checked → ✅ **DONE!**

---

## 📊 Final Numbers

### What You Achieve

| Metric | Before | After |
|--------|--------|-------|
| **Cost** | $25/month | $0/month |
| **Redis** | Railway | Upstash Free |
| **Workers** | Always-on | Serverless |
| **Cold start** | None | 30s occasional |
| **Functionality** | Same | Same |
| **Savings** | - | $25/month |

---

## 🎉 You Did It!

You now have:
✅ Celery workers (same as before)
✅ Redis (free from Upstash)
✅ Serverless (pay per use)
✅ Savings of $25/month

**Perfect for your budget!** 💪

---

## 📚 Full Details

For complete guide: `SERVERLESS_CELERY_SETUP.md`

Contains:
- Detailed explanations
- Cold start information
- Usage monitoring
- Cost calculations

---

That's it! 3 simple changes, $25/month saved! 🚀
