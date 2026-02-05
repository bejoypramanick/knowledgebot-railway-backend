# Docling Models Volume Setup on Railway

## Overview

By setting up a persistent volume, docling models are downloaded once and cached for all future restarts. This:
- ✅ Eliminates model re-downloads on restart (~5-10 minutes saved)
- ✅ Reduces bandwidth costs
- ✅ Speeds up service startup significantly
- ✅ Improves reliability (offline model availability)

## Model Sizes

```
Total cache size needed: ~2-3GB
├── Docling (granite-docling-258m): ~700MB
├── EasyOCR (English): ~300MB
└── Additional cache/indexes: ~1GB
```

## Setup Steps on Railway

### 1. Create Volume in Railway Dashboard

1. **Go to Railway Dashboard**: https://railway.app/dashboard
2. **Select your project**: `knowledgebot-railway-backend`
3. **Select docling-service**: Click on `docling-service`
4. **Click "Storage" tab** (or "Volumes")
5. **Click "Add Storage"** or **"Create Volume"**

### 2. Configure Volume

Set these values:

| Field | Value | Notes |
|-------|-------|-------|
| **Mount Path** | `/models` | Where models cache inside container |
| **Size** | `3GB` | Enough for docling + easyocr + cache |
| **Name** | `docling-models` | Optional, for identification |

### 3. Deploy

1. Click **"Save"** or **"Create"**
2. Railway will automatically restart the service with the volume attached
3. Service will show "Deploying" status

## Verification

### Check Volume is Mounted

1. Go to docling-service → **Deployments** tab
2. Find latest deployment
3. Look for volume info showing:
   ```
   /models (3GB) mounted
   ```

### Check Model Download Progress

1. Go to **Logs** tab
2. Look for messages like:
   ```
   📁 Model Cache Directories:
      Hugging Face: /models/huggingface
      EasyOCR: /models/easyocr
   ⏳ Initializing Docling processor and OCR reader...
   ```

### Verify Models Cached

First request will show:
```
✅ Docling processor initialized successfully
   (Models downloading... this takes 5-10 minutes first time)
```

Subsequent restarts will show:
```
✅ Docling processor initialized successfully
   (Models loaded from cache in <5 seconds)
```

## How It Works

### First Deployment (With Volume)

```
Container starts
  ↓
Mounts /models volume
  ↓
Sets HF_HOME=/models/huggingface
Sets EASYOCR_USER_AGENT_ORIGIN=/models/easyocr
  ↓
Initialize docling
  ↓
Docling checks HF_HOME for model cache
  ↓
Model not found locally
  ↓
Download model → /models/huggingface/... (~5 mins)
  ↓
Initialize easyocr
  ↓
Download easyocr models → /models/easyocr/... (~5 mins)
  ↓
✅ Ready to process documents
  ↓
Models cached on persistent volume (/models)
```

### Subsequent Restarts (Models Cached)

```
Container restarts
  ↓
Mounts /models volume
  ↓
Docling checks HF_HOME for cache
  ↓
✅ Models found locally
  ↓
Load from cache (~2-3 seconds)
  ↓
✅ Ready to process documents instantly
```

## Environment Variables Set Automatically

The Dockerfile now sets these environment variables:

```dockerfile
ENV HF_HOME=/models/huggingface           # Hugging Face model cache
ENV EASYOCR_USER_AGENT_ORIGIN=/models/easyocr  # EasyOCR cache
ENV HOME=/root                             # User home directory
```

When volume is mounted at `/models`, all models download there automatically.

## Monitoring Model Cache

### Check Cache Size

In Railway logs, you'll see:
```
📁 Model Cache Directories:
   Hugging Face: /models/huggingface
   EasyOCR: /models/easyocr
```

### Expected Storage Usage After Setup

```
/models/
├── huggingface/
│   └── hub/
│       └── models--...
│           └── snapshots/
│               └── [model files ~700MB]
└── easyocr/
    ├── model_zh.pth (~200MB)
    ├── model_en.pth (~100MB)
    └── craft_mlt_25k.pth (~100MB)

Total: ~1.2GB (grows slightly with additional languages)
```

## Troubleshooting

### Volume Not Mounting

**Symptom**: Models re-download every restart

**Check**:
1. Go to docling-service → Storage tab
2. Verify volume shows "Mounted" status
3. Verify mount path is `/models`

### Volume Full

**Symptom**: Logs show "No space left on device"

**Fix**:
1. Go to docling-service → Storage tab
2. Click volume → Edit
3. Increase size (from 3GB to 5GB or more)
4. Restart service

### Models Not Caching

**Symptom**: New models downloaded on every startup

**Check logs for**:
```
HF_HOME=/models/huggingface
EASYOCR_USER_AGENT_ORIGIN=/models/easyocr
```

If not set correctly:
1. Verify Dockerfile has environment variables
2. Verify volume is mounted at `/models`
3. Restart service

### Slow First Startup

**Expected behavior**:
- First startup: 10-15 minutes (downloading models)
- Subsequent restarts: 5-10 seconds

If taking longer:
1. Check Railway logs for download progress
2. Monitor available storage
3. Check network connectivity in logs

## Cost Savings

### Without Volume
```
Every restart:
- Download docling model: 5 mins
- Download easyocr models: 5 mins
- Bandwidth used: ~1GB per restart
- Cost: Bandwidth charges per deployment
```

### With Volume (3GB/month cost)
```
First startup: 10 mins + 3GB storage
Subsequent restarts: 5 seconds
Bandwidth: Downloaded once, reused
Cost: Only storage cost (~$0.50-1.00/month for 3GB)
```

**Savings**: Significant bandwidth reduction, faster deployments.

## Adding More Languages to OCR (Future)

If you want to add multi-language OCR support:

1. Modify `docling_processor.py`:
```python
# Current
easyocr.Reader(['en'], verbose=False, gpu=False)

# Add Spanish, French, German
easyocr.Reader(['en', 'es', 'fr', 'de'], verbose=False, gpu=False)
```

2. Increase volume size if needed:
   - English only: 2GB
   - English + 3 languages: 3-4GB
   - All languages: 5-6GB

The volume will automatically cache additional models when you deploy.

## Summary

1. ✅ Create 3GB volume on Railway
2. ✅ Mount at `/models`
3. ✅ Dockerfile already configured to use it
4. ✅ Models auto-download on first startup
5. ✅ Models cached for all future restarts
6. ✅ Startup time improves from 10+ mins to <10 seconds

**That's it!** The models will download once and persist across all service restarts.
