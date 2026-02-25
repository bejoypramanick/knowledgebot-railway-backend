# RapidOCR Models Installation Guide

This guide explains how to install RapidOCR models for docling-serve when using offline mode (with `DOCLING_SERVE_ARTIFACTS_PATH=/data`).

## Problem

When `DOCLING_SERVE_ARTIFACTS_PATH` is set to `/data`, docling-serve runs in **offline mode** and does NOT auto-download models. If models are missing, you'll see errors like:

```
FileNotFoundError: /data/RapidOcr/onnx/PP-OCRv4/det/ch_PP-OCRv4_det_infer.onnx does not exists.
```

## Solution

Use one of the installation scripts to download and set up all required RapidOCR models.

## Installation Methods

### Method 1: Bash Script (Recommended for Linux/Mac)

**Quick Installation:**
```bash
bash scripts/install_rapidocr_models.sh /data
```

**Features:**
- ✅ Fast and lightweight
- ✅ No dependencies (uses curl/wget)
- ✅ Shows progress for each download
- ✅ Verifies installation
- ✅ Retries on failure

**Requirements:**
- `curl` or `wget` installed
- Bash shell
- Write permission to `/data`

### Method 2: Python Script (Cross-platform)

**Quick Installation:**
```bash
python scripts/install_rapidocr_models.py --data-path /data
```

**Features:**
- ✅ Works on Windows, Mac, Linux
- ✅ Built-in progress bar
- ✅ Error handling
- ✅ Verifies file sizes
- ✅ Skip existing files

**Requirements:**
- Python 3.6+
- Write permission to `/data`

**With custom path:**
```bash
python scripts/install_rapidocr_models.py --data-path /custom/path
```

## What Gets Installed

The scripts download these models:

| Model | Size | Purpose |
|-------|------|---------|
| PP-OCRv4 Detection | ~63 MB | Text detection in images |
| PP-OCRv4 Recognition | ~68 MB | Text recognition/reading |
| PP-OCRv4 Classification | ~2 MB | Text orientation classification |
| PPOCR Keys | ~28 KB | Character dictionary |
| FZYTK Font | ~10 MB | Font for text rendering |

**Total:** ~143 MB

## Directory Structure

After installation, you'll have:

```
/data/RapidOcr/
├── onnx/
│   └── PP-OCRv4/
│       ├── det/
│       │   └── ch_PP-OCRv4_det_infer.onnx
│       ├── rec/
│       │   └── ch_PP-OCRv4_rec_infer.onnx
│       └── cls/
│           └── ch_ppocr_mobile_v2.0_cls_infer.onnx
├── paddle/
│   └── PP-OCRv4/
│       └── rec/
│           └── ch_PP-OCRv4_rec_infer/
│               └── ppocr_keys_v1.txt
└── fonts/
    └── FZYTK.TTF
```

## Usage on Railway

### Step 1: SSH into Railway Volume

```bash
# SSH into docling-serve service
# Then navigate to volume mount point
cd /data
```

### Step 2: Run Installation Script

From the `/data` directory:

```bash
# Download the script first
curl -O https://raw.githubusercontent.com/ecommbalaji/knowledgebot-railway-backend/main/scripts/install_rapidocr_models.sh

# Or use the Python version
curl -O https://raw.githubusercontent.com/ecommbalaji/knowledgebot-railway-backend/main/scripts/install_rapidocr_models.py
python install_rapidocr_models.py --data-path /data
```

Or upload the script to Railway and run it in a deployment.

### Step 3: Verify Installation

Check that files exist:

```bash
ls -la /data/RapidOcr/onnx/PP-OCRv4/det/
ls -la /data/RapidOcr/onnx/PP-OCRv4/rec/
ls -la /data/RapidOcr/onnx/PP-OCRv4/cls/
ls -la /data/RapidOcr/paddle/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer/
```

### Step 4: Restart docling-serve

After installation, restart the docling-serve container:

1. Go to Railway Dashboard
2. Find docling-serve service
3. Click "Deploy" or restart the service
4. Check logs for successful model loading

## Troubleshooting

### "curl: command not found"
- Use Python script instead: `python install_rapidocr_models.py`
- Or install curl: `apt-get install curl` (on Linux)

### "Permission denied"
- Ensure you have write permission to `/data`
- On Railway, check that the volume is properly mounted
- May need to run with sudo (if local testing)

### "Connection timeout"
- Check your internet connection
- GitHub servers may be temporarily unavailable
- Try again in a few minutes
- Use a different network if behind a proxy

### "File not found after download"
- Check available disk space: `df -h /data`
- Verify internet connection
- Try the other script (Bash vs Python)

### Models Still Not Loading

1. Verify `DOCLING_SERVE_ARTIFACTS_PATH=/data` is set:
   ```bash
   echo $DOCLING_SERVE_ARTIFACTS_PATH
   ```

2. Check file permissions:
   ```bash
   ls -la /data/RapidOcr/onnx/PP-OCRv4/det/
   ```

3. View docling-serve logs for detailed errors

## Alternative: Disable Offline Mode

If you want to avoid pre-downloading models, you can:

**Unset the artifacts path** to enable auto-download:

1. Go to Railway Dashboard → docling-serve → Variables
2. **Delete** `DOCLING_SERVE_ARTIFACTS_PATH`
3. Keep `DOCLING_SERVE_DOWNLOAD_MODELS_ON_START=True`
4. Redeploy

Docling will then auto-download models on first startup (takes 5-10 minutes).

## Support

If you encounter issues:

1. Check the installation logs
2. Verify directory structure matches above
3. Ensure all files are fully downloaded (check file sizes)
4. Try the alternative script (Bash vs Python)
5. Check Railway logs for detailed error messages

## References

- [RapidOCR GitHub](https://github.com/RapidAI/RapidOCR)
- [Docling Documentation](https://ds4sd.github.io/docling/)
- [PP-OCRv4 Models](https://github.com/PaddleOCR/PaddleOCR)
