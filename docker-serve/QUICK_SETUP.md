# Quick Setup: Docling-Serve on Railway

## Step 1: Set Environment Variables in Railway Dashboard

**Navigate to**: Railway Dashboard → Services → `docker-serve` → Variables

**Copy & paste these exactly**:

```
REDIS_URL=redis://redis.railway.internal:6379/2
DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
DOCLING_SERVE_LOAD_MODELS_AT_BOOT=false
DOCLING_SERVE_SCRATCH_PATH=/app/scratchpad
DOCLING_SERVE_ENABLE_UI=1
DOCLING_SERVE_LOG_LEVEL=INFO
```

That's it! These are the **only** variables needed for docker-serve itself.

---

## Step 2: Verify Setup

1. **Deploy and wait** for docker-serve to build and start (~10-20 minutes for build, then starts)

2. **Check logs** in Railway:
   - Should see: `✅ Models loaded from /opt/app-root/src/models`
   - Should see: `✅ Listening on RQ queue: docling`
   - Should see: `✅ API running on http://0.0.0.0:5001`

3. **Access web UI** (if enabled):
   - Click on docker-serve service in Railway
   - Click "Networking" tab
   - Find the public URL
   - Append `/ui` (e.g., `https://your-domain.up.railway.app/ui`)

4. **Check Redis connection**:
   - Workers should connect to `DOCLING_REDIS_URL` on DB 2
   - If workers are already running, they should see docling-serve coming online

---

## Step 3: Ensure File/Web Workers Have Correct Config

**For each worker service** (celery-file-worker, celery-web-worker), verify these are set:

```
DOCLING_REDIS_URL=redis://redis.railway.internal:6379/2
DOCLING_RQ_QUEUE_NAME=docling
DOCLING_ENABLED=true
```

(Contact whoever set up the workers to verify)

---

## Troubleshooting

### Docling doesn't start
```
❌ "Models not found at /opt/app-root/src/models/RapidOcr"
```
**Fix**:
- Dockerfile didn't download models properly
- Delete service, rebuild from GitHub
- Check logs during build phase

### Workers can't reach docling
```
❌ "Failed to enqueue job to Redis"
```
**Fix**:
- Verify `DOCLING_REDIS_URL` is set in workers
- Must be: `redis://redis.railway.internal:6379/2` (DB 2, not 0 or 1)
- Restart workers after changing

### Models taking forever to start
```
⏳ "Models still loading after 5 minutes..."
```
**Fix**:
- Increase Railway resource allocation (CPU/memory)
- This shouldn't happen with pre-downloaded models, check logs

### Can't access web UI
```
❌ "Connection refused on :5001"
```
**Fix**:
- Set `DOCLING_SERVE_ENABLE_UI=1`
- Check service is healthy in Railway dashboard
- Web UI runs on port 5001 by default

---

## What Each Variable Does

| Variable | Value | Purpose |
|----------|-------|---------|
| `REDIS_URL` | `redis://redis.railway.internal:6379/2` | **CRITICAL** - Redis connection for RQ queue (must be DB 2) |
| `DOCLING_SERVE_ARTIFACTS_PATH` | `/opt/app-root/src/models` | Where pre-downloaded models are stored in the image |
| `DOCLING_SERVE_LOAD_MODELS_AT_BOOT` | `false` | Skip model download (already in image) |
| `DOCLING_SERVE_SCRATCH_PATH` | `/app/scratchpad` | Temp directory for processing documents |
| `DOCLING_SERVE_ENABLE_UI` | `1` | Enable web UI for monitoring |
| `DOCLING_SERVE_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Next Steps

1. ✅ Set environment variables above in Railway dashboard
2. ✅ Deploy docker-serve service
3. ✅ Verify logs show models loaded successfully
4. ✅ Verify workers can connect to RQ queue
5. ✅ Test by uploading a PDF via the knowledgebase UI
6. ✅ Check logs to see document being processed by docling-serve

---

## Important Notes

- **Models are baked in**: Docker image includes ~5-6GB of models, startup is 2-3 min (not 10+ min)
- **DB 2 only**: Docling uses Redis DB 2, separate from Celery queues (DB 0 and DB 1)
- **Async processing**: Documents are processed asynchronously - workers enqueue and poll for results
- **Optional Railway Storage**: Can configure S3 credentials for persistent result storage (see `ENVIRONMENT_VARIABLES.md`)

---

## Testing

**Quick test without web UI**:

```bash
# SSH into a worker container
# or use Railway shell

# Check if docling queue is listening
redis-cli -u "redis://redis.railway.internal:6379/2" PING
# Should see: PONG

# Check queue status
redis-cli -u "redis://redis.railway.internal:6379/2" KEYS "*"
# Should see RQ queue keys when jobs are being processed
```

---

## Questions?

Refer to:
- `docker-serve/README.md` - Full architecture and deployment details
- `docker-serve/ENVIRONMENT_VARIABLES.md` - All environment variables explained
- Worker logs - Will show detailed errors if something goes wrong
