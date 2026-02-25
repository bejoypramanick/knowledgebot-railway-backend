# Docling Serve Docker Image

This folder contains a custom Docker image for **Docling Serve with pre-downloaded models**.

## Overview

This Dockerfile builds a complete docling-serve image with all models baked in at build time, eliminating the need to download models at runtime.

## Features

✅ **Pre-downloaded Models** - All RapidOCR, layout, and other models included
✅ **Fast Startup** - No model downloads on container start (~2-3 min vs 10+ min)
✅ **Persistent Models** - Models embedded in image, always available
✅ **CPU Optimized** - Uses official CPU base image
✅ **Security** - Runs as non-root user (UID 1001)

## Models Included

All models are downloaded with the `RapidOcr` parent folder included:

```
/opt/app-root/src/models/
└── RapidOcr/         (Parent folder, auto-created by docling-tools)
    ├── onnx/         (ONNX format models)
    │   ├── PP-OCRv4/
    │   │   ├── det/
    │   │   ├── rec/
    │   │   └── cls/
    │   └── ...other models
    ├── paddle/       (Paddle format models)
    │   └── PP-OCRv4/
    │       └── rec/
    └── fonts/        (Font files)
        └── FZYTK.TTF
```

Includes:
- 🔍 **RapidOCR Models** - Detection, recognition, classification (ONNX + Paddle)
- 📄 **Docling Layout Models** - Page layout understanding
- 🎨 **Supporting Models** - Fonts and dependencies
- 📐 **Performance Optimizations** - Table structure recognition

**Total Image Size:** ~5-6 GB (includes all models)

## Deployment on Railway

### 1. Set Runtime Environment Variables

All paths are **decided at deploy time** - configure them once and change anytime without rebuilding!

**Go to Railway Dashboard → Service Variables and set:**

```
DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
DOCLING_SERVE_LOAD_MODELS_AT_BOOT=false
DOCLING_SERVE_SCRATCH_PATH=/app/scratchpad
DOCLING_SERVE_ENABLE_UI=1
DOCLING_SERVE_LOG_LEVEL=INFO
```

These paths are **not hardcoded** in the image - you configure them at runtime!

### 2. Configure Railway Service

- **Dockerfile path**: `docker-serve/Dockerfile`
- **Build command**: Default (uses Dockerfile)
- **Start command**: Default (uses CMD from base image)
- **Volumes needed**:
  - Mount `/app/scratchpad` for temporary processing
  - Mount `/app/results` for output storage

### 3. Deploy

Push to GitHub:
```bash
git add docker-serve/
git commit -m "Add docling-serve custom Docker image with pre-downloaded models"
git push origin main
```

Railway will automatically detect and build the image.

## What Gets Pre-downloaded

During build, the image runs:

```bash
docling-tools models download --all -o /opt/app-root/src/models
```

This downloads:
- ✅ RapidOCR ONNX models (detection, recognition, classification)
- ✅ Paddle OCR models
- ✅ Docling layout models
- ✅ Font files (FZYTK.TTF, etc.)
- ✅ Supporting dependencies

Models are downloaded directly to the parent directory:
```
/opt/app-root/src/models/
├── onnx/
│   └── PP-OCRv4/
│       ├── det/
│       ├── rec/
│       └── cls/
├── paddle/
│   └── PP-OCRv4/
│       └── ...
└── fonts/
    └── FZYTK.TTF
```

## Advantages vs Manual Installation

| Aspect | Manual Install | Docker Image |
|--------|---|---|
| **Startup Time** | 10-15 minutes | 2-3 minutes |
| **Model Freshness** | Latest at runtime | Built at image time |
| **Disk Space** | Volume only | Image + volume |
| **Reliability** | Depends on network | Always available |
| **Consistency** | May vary | Guaranteed same image |

## Environment Variables (Set at Runtime on Railway)

### Where Models Are Located in Image
```
/opt/app-root/src/models/RapidOcr/  (models baked into image)
```

### Set These on Railway (Decide at Deploy Time)

**Required - Point to image model location:**
```bash
DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
```

**Recommended - Set as needed:**
```bash
DOCLING_SERVE_LOAD_MODELS_AT_BOOT=false  # Models already in image
DOCLING_SERVE_SCRATCH_PATH=/app/scratchpad  # Temp directory
DOCLING_SERVE_ENABLE_UI=1  # Enable web UI
DOCLING_SERVE_LOG_LEVEL=INFO  # Logging level
```

### Key Point
✅ Models are **pre-downloaded and embedded in image** at `/opt/app-root/src/models/RapidOcr/`
✅ Set `DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models` (parent of RapidOcr)
✅ You **decide the paths at deploy time** via Railway env vars
✅ Change paths anytime without rebuilding image
✅ Container uses whatever you set in Railway

## Building Locally

If you want to build and test locally:

```bash
# Build the image
docker build -t docling-serve-custom:latest -f docker-serve/Dockerfile .

# Run locally
docker run -p 5001:5001 \
  -e DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models \
  -e DOCLING_SERVE_SCRATCH_PATH=/tmp/scratchpad \
  -v /tmp/scratchpad:/tmp/scratchpad \
  docling-serve-custom:latest
```

## Troubleshooting

### Image Too Large

The image includes all models (~5-6 GB). If Railway has size limits:
- Use Docker layer caching
- Consider the manual installation approach instead
- Increase storage/memory limits on Railway

### Models Not Found

If you see "not found" errors:

1. Verify `DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models`
2. Check container logs: `docker logs <container-id>`
3. Verify models are in image: `docker exec <container> ls -la /opt/app-root/src/models/RapidOcr/`

### Slow Startup

Startup should be 2-3 minutes. If slower:
- Check Railway resource allocation
- Verify no disk I/O bottlenecks
- Check network connectivity

## Base Image

This uses the official CPU-optimized base image:

```
quay.io/docling-project/docling-serve-cpu:latest
```

For GPU support, change to:
```
quay.io/docling-project/docling-serve-gpu:latest
```

## Security

- ✅ Runs as non-root user (UID 1001)
- ✅ Read-only filesystem where possible
- ✅ Model directories owned by app user
- ✅ No hardcoded credentials

## Support

For issues with docling-serve itself:
- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling Serve GitHub](https://github.com/docling-project/docling-serve)
- [Documentation](https://ds4sd.github.io/docling/)

For Railway deployment issues:
- Check Railway logs
- Verify environment variables
- Ensure volumes are mounted correctly
