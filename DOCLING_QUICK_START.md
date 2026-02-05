# Docling Service - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Option 1: Local Development

```bash
# 1. Install docling service dependencies
cd docling_service
pip install -r requirements.txt

# 2. Run docling service (separate terminal)
export DOCLING_PORT=8004
python -m uvicorn main:app --host 0.0.0.0 --port 8004 --reload

# 3. In another terminal, enable docling in knowledgebase
export DOCLING_ENABLED=true
export DOCLING_SERVICE_URL=http://localhost:8004

# Run knowledgebase service
cd knowledgebase_ingestion
python -m uvicorn main:app --host 0.0.0.0 --port 8001
```

### Option 2: Docker Compose

```bash
# 1. Add to docker-compose.yml (at end of services section):
docling-service:
  build:
    context: .
    dockerfile: docling_service/Dockerfile
  ports:
    - "8004:8004"
  environment:
    - DOCLING_PORT=8004
    - DOCLING_MODEL_NAME=granite-docling-258m
    - DOCLING_PROCESSING_TIMEOUT_SECONDS=270
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8004/health"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 120s

# 2. Run with compose
docker-compose up

# 3. Enable in knowledgebase (in docker-compose.yml):
knowledgebase-ingestion:
  environment:
    - DOCLING_ENABLED=true
    - DOCLING_SERVICE_URL=http://docling-service:8004
    - DOCLING_TIMEOUT_SECONDS=300
```

### Option 3: Railway Deployment

```bash
# 1. Create new Railway service via dashboard
railway service create

# 2. Set service name to: docling-service

# 3. Link Dockerfile: docling_service/Dockerfile

# 4. Set environment variables in Railway:
PORT=8004
DOCLING_MODEL_NAME=granite-docling-258m
DOCLING_PROCESSING_TIMEOUT_SECONDS=270

# 5. Deploy

# 6. Update knowledgebase-ingestion service with:
DOCLING_ENABLED=true
DOCLING_SERVICE_URL=http://docling-service:8004  # Internal Railway URL
DOCLING_TIMEOUT_SECONDS=300
```

## ✅ Verify Installation

```bash
# 1. Check docling service is running
curl http://localhost:8004/health

# Expected response:
{
  "status": "healthy",
  "docling_initialized": true,
  "ocr_initialized": true,
  "service": "docling-service"
}

# 2. Test docling conversion
curl -X POST http://localhost:8004/api/v1/docling/process \
  -F "file=@sample.pdf"

# Expected response:
{
  "success": true,
  "content": "# Document Title\n\nContent here...",
  "metadata": {
    "filename": "sample.pdf",
    "processing_time_ms": 1500,
    "images_extracted": 2,
    "images_with_ocr": 2
  }
}

# 3. Test file upload (with docling)
curl -X POST http://localhost:8001/api/v1/knowledgebase/upload \
  -F "file=@sample.pdf" \
  -H "X-User-Email: test@example.com"

# Should upload markdown instead of raw PDF
```

## 🔧 Disable Docling (If Needed)

If you want to use the system without docling:

```bash
# Set environment variable
export DOCLING_ENABLED=false

# Restart knowledgebase service
# Now all files upload as raw (no markdown conversion)
```

## 📊 Check Docling Performance

```bash
# Test with a real PDF
time curl -X POST http://localhost:8004/api/v1/docling/process \
  -F "file=@large-document.pdf"

# Look at:
# - total time
# - processing_time_ms in response
# - images_extracted and images_with_ocr counts
```

## 🐛 Troubleshooting

### Docling service not starting?
```bash
# Check if port 8004 is available
lsof -i :8004

# Check Docker logs
docker logs docling-service

# Check Python version (needs 3.12+)
python --version
```

### "Module not found" errors?
```bash
# Make sure you're in the right directory
pwd  # Should be in knowledgebot-railway-backend

# Reinstall dependencies
cd docling_service
pip install --upgrade -r requirements.txt

# Check PYTHONPATH
export PYTHONPATH=/path/to/knowledgebot-railway-backend
```

### Docling service timing out?
```bash
# Increase timeout in knowledgebase config
export DOCLING_TIMEOUT_SECONDS=600  # 10 minutes

# Check if file is very large
du -h sample.pdf

# Try smaller file first
```

### Getting "Docling service unreachable"?
```bash
# Check if service is running
curl http://localhost:8004/health

# Check Docker network
docker network ls
docker inspect <network-name>

# Check service URL in knowledgebase config
echo $DOCLING_SERVICE_URL  # Should be http://docling-service:8004 (Docker)
                          # or http://localhost:8004 (local)
```

## 📝 Example Usage

### Upload PDF with automatic docling processing
```bash
curl -X POST http://localhost:8001/api/v1/knowledgebase/upload \
  -F "file=@research-paper.pdf" \
  -H "X-User-Email: user@example.com"

# Result:
# - PDF converted to markdown
# - Images extracted and OCR'd
# - Markdown uploaded to Gemini (not PDF)
# - Better RAG search results
```

### Upload non-document file (skips docling)
```bash
curl -X POST http://localhost:8001/api/v1/knowledgebase/upload \
  -F "file=@data.csv" \
  -H "X-User-Email: user@example.com"

# Result:
# - CSV uploaded as-is (skips docling)
# - No markdown conversion needed
```

### Check what files are supported
```bash
# Docling processes these:
# PDF, DOCX, DOC, PPTX, PPT, XLSX, HTML

# Skips docling (uploads raw):
# TXT, MD, CSV, JSON, XML, YAML

# Unsupported:
# EXE, ZIP, RAR, etc. (will fail validation)
```

## 🎯 Performance Tips

1. **First Run**: First request may take 30-60 seconds (models download)
   - Subsequent requests are faster (2-10 seconds)
   - Monitor `processing_time_ms` in response

2. **Large Files**: Very large PDFs (100+ pages) may timeout
   - Increase `DOCLING_TIMEOUT_SECONDS` if needed
   - Or disable docling with `DOCLING_ENABLED=false`

3. **Image-Heavy Documents**: Documents with many images take longer
   - Each image requires OCR processing
   - Processing time ~ 1-2 seconds per image

4. **Memory**: Docling + OCR require ~4GB RAM
   - Allocate 4GB to docker container/Railway service
   - Monitor `docker stats` for memory usage

## 📚 Full Documentation

For complete details, see:
- `DOCLING_IMPLEMENTATION.md` - Full implementation guide
- `DOCLING_IMPLEMENTATION_SUMMARY.md` - Summary of changes
- Code comments in `docling_service/core/docling_processor.py` - Implementation details

## 🆘 Getting Help

1. Check logs: `docker logs docling-service`
2. Test health: `curl http://localhost:8004/health`
3. Verify config: `echo $DOCLING_*` (show all docling env vars)
4. Test directly: `curl -X POST http://localhost:8004/api/v1/docling/process -F "file=@test.pdf"`
5. Check Railway logs: Dashboard → Service → Logs

---

**Everything is ready to go!** 🎉
