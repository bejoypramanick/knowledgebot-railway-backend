# Docling-Serve Environment Variables Configuration

This document explains all environment variables needed for docling-serve to work properly on Railway with the file and web workers.

## Architecture Overview

```
File Worker (Celery)  ─┐
                       ├─→ Redis Queue (RQ) - DB 2 ←─ Docling-Serve Worker
Web Worker (Celery)   ─┘
                       ↓
                    Docling Job Results
                       ↓
                 [Redis or Railway Storage]
```

## Environment Variables for docker-serve on Railway

### 0. **CRITICAL - Redis Queue Connection**

```bash
REDIS_URL=redis://redis.railway.internal:6379/2
```
- **Description**: Where docling-serve listens for jobs from the RQ queue
- **Value**: `redis://redis.railway.internal:6379/2`
- **Why**: Docling-serve needs this to:
  - Listen for document conversion jobs from workers
  - Store results and job status
  - Communicate with celery workers
- **Important**: **Must use DB 2** (not DB 0 or DB 1, which are for Celery)
- **Default**: None - must be explicitly set

### 1. **CRITICAL - Docling Model Configuration**

These tell docling-serve where to find the pre-downloaded models:

```bash
DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
```
- **Description**: Points to the parent directory containing the `RapidOcr/` folder
- **Value**: `/opt/app-root/src/models` (where models are baked into the image)
- **Why**: This is where the Dockerfile downloads all models during build
- **Directory structure inside**:
  ```
  /opt/app-root/src/models/
  └── RapidOcr/
      ├── onnx/
      ├── paddle/
      └── fonts/
  ```

```bash
DOCLING_SERVE_LOAD_MODELS_AT_BOOT=false
```
- **Description**: Whether to download models at startup
- **Value**: `false` (models are already in the image, no need to download)
- **Why**: Models are pre-baked, skips 10+ min startup time

### 2. **CRITICAL - Temporary Scratch Directory (still critical)**

```bash
DOCLING_SERVE_SCRATCH_PATH=/app/scratchpad
```
- **Description**: Where docling-serve stores temporary files during processing
- **Value**: `/app/scratchpad` (or any writable directory)
- **Why**: Docling needs space to extract and process documents
- **Note**: You can mount a Railway volume here if you need persistence across restarts

### 3. **RECOMMENDED - UI and Logging (still recommended)**

```bash
DOCLING_SERVE_ENABLE_UI=1
```
- **Description**: Enable the web UI for docling-serve
- **Value**: `1` (enabled) or `0` (disabled)
- **Default**: `1`
- **Why**: Useful for monitoring and debugging

```bash
DOCLING_SERVE_LOG_LEVEL=INFO
```
- **Description**: Logging verbosity
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`
- **Default**: `INFO`
- **Why**: Use `DEBUG` for troubleshooting, `INFO` for production


---

## Summary: All Required Variables for Railway Dashboard

Copy and paste these into Railway Dashboard → docker-serve service → Variables:

```
# Redis Queue Connection (CRITICAL - docling-serve must connect to listen for jobs)
REDIS_URL=redis://redis.railway.internal:6379/2

# Model Configuration (CRITICAL)
DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
DOCLING_SERVE_LOAD_MODELS_AT_BOOT=false
DOCLING_SERVE_SCRATCH_PATH=/app/scratchpad

# UI and Logging (RECOMMENDED)
DOCLING_SERVE_ENABLE_UI=1
DOCLING_SERVE_LOG_LEVEL=INFO
```

---

## How File/Web Workers Connect to Docling-Serve

The file worker and web worker use these environment variables (you set these in THEIR Railway services, not in docker-serve):

### File Worker Environment Variables

```bash
# Redis for Celery file queue (DB 0)
FILE_REDIS_URL=redis://redis.railway.internal:6379/0

# Redis for Docling RQ queue (DB 2) - CRITICAL
DOCLING_REDIS_URL=redis://redis.railway.internal:6379/2

# Docling RQ queue name (must match docker-serve's queue)
DOCLING_RQ_QUEUE_NAME=convert

# Docling configuration
DOCLING_ENABLED=true
DOCLING_TIMEOUT_SECONDS=3600
DOCLING_RQ_JOB_TIMEOUT_MINUTES=60

# Railway Storage (optional - for docling results)
RAILWAY_BUCKET_NAME=your-bucket
RAILWAY_REGION=us-east-1
RAILWAY_STORAGE_URL=https://s3.railway.app
RAILWAY_STORAGE_ACCESS_KEY=your-access-key
RAILWAY_STORAGE_SECRET_KEY=your-secret-key
```

### Web Worker Environment Variables

```bash
# Redis for Celery web queue (DB 1)
WEB_REDIS_URL=redis://redis.railway.internal:6379/1

# Redis for Docling RQ queue (DB 2) - CRITICAL
DOCLING_REDIS_URL=redis://redis.railway.internal:6379/2

# Docling RQ queue name (must match docker-serve's queue)
DOCLING_RQ_QUEUE_NAME=convert

# Docling configuration
DOCLING_ENABLED=true
DOCLING_TIMEOUT_SECONDS=1800
DOCLING_RQ_JOB_TIMEOUT_MINUTES=60
```

---

## Redis Database Layout (Important!)

Your Redis instance has **3 separate databases**:

- **DB 0** (`FILE_REDIS_URL`): File processing queue (Celery)
- **DB 1** (`WEB_REDIS_URL`): Web scraping queue (Celery)
- **DB 2** (`DOCLING_REDIS_URL`): Docling document conversion (RQ)

This separation prevents queue conflicts:
- File worker puts jobs on DB 0
- Web worker puts jobs on DB 1
- Both workers enqueue docling jobs to DB 2
- Docling-serve worker listens on DB 2
- Results stored in DB 2 Redis (or uploaded to Railway Storage)

---

## Railway Storage (Optional but Recommended)

If you configure Railway Storage credentials, docling-serve will:
1. Accept S3 upload targets from workers
2. Process documents
3. Upload results directly to Railway Storage S3
4. Return S3 key in Redis instead of binary data

This is better for large documents because:
- Avoids large Redis values
- Results persist in S3 for download
- Workers can fetch results later

**Without Railway Storage**: Results stored in Redis (4-hour TTL), good for small docs

**With Railway Storage**: Results in S3, workers upload markdown to S3 too, optimal for production

---

## Volumes Needed on Railway

Mount these volumes in docker-serve service:

1. **Scratch Directory** (required):
   ```
   Mount path: /app/scratchpad
   ```
   - Temporary files during processing
   - Can be ephemeral (doesn't need to persist)

2. **Results Directory** (optional):
   ```
   Mount path: /app/results
   ```
   - Output storage if not using Railway Storage S3
   - Only needed if you want to keep results on disk

---

## Test Checklist

After configuring, verify:

1. **Check docling-serve logs**:
   ```
   DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models ✓
   Models loaded successfully ✓
   Listening on RQ queue: docling ✓
   ```

2. **Check file worker logs**:
   ```
   Connected to DOCLING_REDIS_URL ✓
   Enqueued job to RQ queue ✓
   Polling for docling result ✓
   ```

3. **Check web worker logs**:
   ```
   Connected to DOCLING_REDIS_URL ✓
   HTML uploaded to S3 ✓
   Docling job enqueued ✓
   Result received ✓
   ```

---

## Common Issues & Fixes

### Issue: "Models not found at /opt/app-root/src/models/RapidOcr"

**Solution**:
- Verify `DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models` is set
- Check docker-serve logs: `ls /opt/app-root/src/models/` should show `RapidOcr/`
- If not present, Dockerfile didn't download models - rebuild and redeploy

### Issue: "Connection refused" from file worker to docling queue

**Solution**:
- Verify file worker has `DOCLING_REDIS_URL=redis://redis.railway.internal:6379/2`
- Verify docling-serve is running and listening on DB 2
- Check Redis is accessible from both services (should be on same Railway project)

### Issue: "Docling job timeout after 3600 seconds"

**Solution**:
- Increase `DOCLING_TIMEOUT_SECONDS` in file/web workers
- Increase `DOCLING_RQ_JOB_TIMEOUT_MINUTES` in file/web workers
- Increase `DOCLING_SERVE_LOG_LEVEL=DEBUG` to see what's taking so long
- Check if docling-serve has enough CPU/memory allocated

### Issue: "Scratch path not writable"

**Solution**:
- Make sure volume is mounted at `/app/scratchpad`
- Check volume has write permissions
- Try changing to `/tmp/scratchpad` if mount fails

### Issue: "Redis results TTL expired before worker could fetch"

**Solution**:
- If using Railway Storage: configure all S3 credentials in file/web workers
- Increase polling intervals if document processing is very slow
- Default 4-hour Redis TTL should be enough for most documents

---

## Production Recommendations

1. **Set all CRITICAL variables** - model path, scratch path, load models flag
2. **Enable Railway Storage** - safer for large documents, better for persistence
3. **Set DOCLING_SERVE_LOG_LEVEL=INFO** - balance debugging and performance
4. **Mount volumes** - ensure scratchpad is writable
5. **Monitor logs** - watch for timeout errors and adjust timeouts accordingly
6. **Scale docling-serve** - may need multiple instances for high volume
   - Each instance needs separate queue worker
   - Distribute jobs across instances via RQ queue
