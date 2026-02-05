# Docling Service Implementation Guide

## Overview
The Docling Service is a new standalone microservice (port 8004) that converts documents (PDF, DOCX, PPTX, etc.) to markdown with **image OCR extraction**. It integrates seamlessly with the knowledgebase_ingestion service and is completely **plug-and-play** - can be disabled via environment variable or deployed optionally.

## Architecture

### Service Structure
```
docling_service/                 # New standalone service (port 8004)
├── main.py                      # FastAPI app entry point
├── requirements.txt             # Dependencies (docling, easyocr, etc.)
├── Dockerfile                   # Container config
├── railway.toml                 # Railway deployment
├── core/
│   ├── config.py               # Settings (pydantic BaseSettings)
│   ├── docling_processor.py    # Core docling + OCR logic
│   ├── utils.py                # Exception handlers, logging
│   └── __init__.py
├── routers/
│   ├── router.py               # API endpoints
│   └── __init__.py
├── schemas/
│   ├── models.py               # Pydantic models (request/response)
│   └── __init__.py
├── utils/
│   ├── constants.py            # File type configs
│   ├── validation.py           # Input validation
│   └── __init__.py
└── __init__.py
```

### Integration Flow
```
User uploads file
    ↓
API Gateway routes to Knowledgebase Ingestion (port 8001)
    ↓
Knowledgebase checks: DOCLING_ENABLED + file type supported?
    ↓ YES (PDF/DOCX/PPTX)
Call Docling Service (port 8004) via HTTP POST
    ↓
Docling processes:
  1. Extract document structure to markdown
  2. Extract images from document
  3. Perform OCR on each image
  4. Combine: markdown + image OCR results
    ↓
Return markdown content + metadata
    ↓
Upload markdown to Gemini FileSearch (not raw file)
    ↓
Save metadata to PostgreSQL
    ↓
SUCCESS or FALLBACK if docling fails/times out
```

## Key Features

### 1. Document Processing
- **Input Formats**: PDF, DOCX, DOC, PPTX, PPT, XLSX, HTML
- **Output**: Clean markdown with:
  - Proper heading hierarchy
  - Code blocks preserved
  - Tables extracted and formatted
  - Formula/equation support
  - **Image OCR text extraction**

### 2. Image OCR Extraction (NEW)
- Uses **EasyOCR** for robust text extraction from images
- Automatically detects and extracts text from all images in document
- OCR results appended to markdown as "Extracted Image Text" section
- Metadata tracks:
  - `images_extracted`: Total images found in document
  - `images_with_ocr`: Images with successfully extracted text

### 3. Plug-and-Play Design
- **Enable/Disable**: Set `DOCLING_ENABLED=false` in environment
- **Service Optional**: Docling service can be deployed separately or not at all
- **Graceful Fallback**: If docling fails/times out, automatically uploads raw file
- **No Breaking Changes**: Existing workflow continues unchanged

### 4. Timeout Handling
- Processing timeout: 300 seconds (5 minutes) by default
- Configurable via `DOCLING_TIMEOUT_SECONDS` env var
- Returns error with HTTP 200 (enables fallback in knowledgebase)
- Prevents hanging requests

## Configuration

### Environment Variables

**Docling Service** (`docling_service/`):
```bash
# Port
PORT=8004              # or DOCLING_PORT
DOCLING_PORT=8004

# Docling Configuration
DOCLING_MODEL_NAME=granite-docling-258m
DOCLING_MAX_FILE_SIZE_MB=50
DOCLING_PROCESSING_TIMEOUT_SECONDS=270  # 4.5 minutes

# Processing
DOCLING_MAX_WORKERS=2
```

**Knowledgebase Ingestion Service** (`knowledgebase_ingestion/`):
```bash
# Docling Integration (PLUG-AND-PLAY)
DOCLING_ENABLED=true                    # Set to false to disable
DOCLING_SERVICE_URL=http://docling-service:8004  # Internal Railway URL
DOCLING_TIMEOUT_SECONDS=300             # 5 minutes client timeout
DOCLING_FALLBACK_TO_RAW=true            # Fallback to raw if docling fails
```

### Feature Flags
- `DOCLING_ENABLED=true/false` - Enable/disable docling integration
- `DOCLING_FALLBACK_TO_RAW=true/false` - Whether to fallback to raw upload

## API Endpoints

### Docling Service

**POST `/api/v1/docling/process`** - Convert document to markdown
```bash
# Request
curl -X POST http://localhost:8004/api/v1/docling/process \
  -F "file=@document.pdf"

# Response (200 OK)
{
  "success": true,
  "content": "# Document Title\n\nContent here...",
  "metadata": {
    "filename": "document.pdf",
    "processing_time_ms": 1500,
    "model": "granite-docling-258m",
    "markdown_length": 5000,
    "document_pages": 10,
    "images_extracted": 3,
    "images_with_ocr": 3
  },
  "error": null
}

# Response on error (200 OK - enables fallback)
{
  "success": false,
  "content": null,
  "metadata": {"error": "Processing timeout"},
  "error": "Processing timeout"
}
```

**GET `/health`** - Health check
```bash
curl http://localhost:8004/health

# Response
{
  "status": "healthy",
  "docling_initialized": true,
  "ocr_initialized": true,
  "service": "docling-service",
  "model": "granite-docling-258m"
}
```

### Knowledgebase Ingestion Service (Unchanged)
```bash
# Single file upload (with transparent docling processing)
POST /api/v1/knowledgebase/upload
POST /api/v1/knowledgebase/files/upload

# File deletion, listing, etc. - unchanged
DELETE /api/v1/knowledgebase/files/{id}
GET /api/v1/knowledgebase/files
```

## Implementation Details

### 1. Docling Processor (`core/docling_processor.py`)
- Lazy initialization of DocumentConverter and OCR Reader
- Async processing with timeout handling
- Image extraction and OCR on every document
- Returns markdown + metadata

**Key Methods**:
- `initialize()` - Async initialization (called on app startup)
- `process_document()` - Convert document to markdown with OCR
- `_extract_and_ocr_images()` - Extract and OCR images

### 2. Knowledgebase Integration (`service/docling_integration.py`)
- `should_use_docling_for_file()` - Check if file should be processed
- `process_with_docling()` - Call docling service via HTTP
- `create_markdown_temp_file()` - Create temp markdown file

**Decision Logic**:
1. Check `DOCLING_ENABLED` environment variable
2. Check if docling service URL is configured
3. Check if file type is supported
4. File size < 50MB

**Skip Docling For**:
- Already text: `.txt`, `.md`, `.csv`, `.json`, `.xml`
- Not supported: unknown extensions
- Too large: > 50MB

### 3. Modified Ingestion Flow (`service/ingestion_service.py`)
```python
# After duplicate check
if should_use_docling_for_file(...):
    try:
        markdown_content, metadata = await process_with_docling(...)
        if markdown_content:
            # Create temp markdown file
            tmp_path = markdown file
            original_filename = "name.md"
            mime_type = "text/markdown"
    except Exception:
        # Fallback to raw file
        continue with original tmp_path

# Upload to Gemini (either markdown or raw)
await process_with_gemini(tmp_path, ...)
```

## Database Changes (Optional)

**Migration Script**: `sql/add_docling_columns.sql`

**New Columns** (optional, for analytics):
```sql
ALTER TABLE file_uploads ADD COLUMN
  processed_by_docling boolean DEFAULT false,
  docling_processing_time_ms int4,
  original_file_extension varchar(50),
  original_mime_type varchar(100),
  docling_images_extracted int4,
  docling_images_with_ocr int4;
```

**Not Required**: Current schema works fine without these columns. They're useful for:
- Analytics: Track docling usage
- Debugging: See processing times
- Optimization: Identify slow conversions

## Deployment

### Local Development
```bash
# 1. Install docling service dependencies
cd docling_service
pip install -r requirements.txt

# 2. Set environment
export DOCLING_PORT=8004
export DOCLING_MODEL_NAME=granite-docling-258m

# 3. Run service
python -m uvicorn main:app --host 0.0.0.0 --port 8004

# 4. Test
curl -X POST http://localhost:8004/api/v1/docling/process \
  -F "file=@test.pdf"
```

### Docker
```bash
# Build
docker build -f docling_service/Dockerfile -t docling-service:latest .

# Run
docker run -p 8004:8004 docling-service:latest
```

### Railway Deployment
1. Create new Railway service: "docling-service"
2. Set environment variables in Railway dashboard:
   ```
   DOCLING_PORT=8004
   DOCLING_MODEL_NAME=granite-docling-258m
   DOCLING_PROCESSING_TIMEOUT_SECONDS=270
   ```
3. Deploy container
4. Update knowledgebase_ingestion service:
   ```
   DOCLING_SERVICE_URL=http://docling-service:8004  (internal URL)
   DOCLING_ENABLED=true
   ```

**Resource Requirements**:
- Memory: 4GB (docling + OCR models are large)
- CPU: 2 cores
- Storage: 2GB for model downloads

## Testing

### Unit Tests
```bash
# Test docling conversion
python -m pytest tests/test_docling_processor.py

# Test knowledgebase integration
python -m pytest tests/test_docling_integration.py
```

### Integration Tests
```bash
# Test end-to-end: PDF → markdown → Gemini
python -m pytest tests/test_e2e_docling.py

# Test fallback: docling service unavailable
python -m pytest tests/test_docling_fallback.py
```

### Manual Testing
```bash
# 1. Test docling service directly
curl -X POST http://localhost:8004/api/v1/docling/process \
  -F "file=@sample.pdf"

# 2. Test knowledgebase with docling
curl -X POST http://localhost:8001/api/v1/knowledgebase/upload \
  -F "file=@sample.pdf" \
  -H "X-User-Email: test@example.com"

# 3. Test with docling disabled
export DOCLING_ENABLED=false
# ...repeat step 2, should upload raw PDF

# 4. Test timeout handling
# Use a very large PDF (> 5 minutes processing)
# Should fallback to raw upload
```

## Troubleshooting

### Docling Service Not Responding
```bash
# Check health
curl http://localhost:8004/health

# Check logs for initialization errors
docker logs docling-service

# Verify port
netstat -an | grep 8004
```

### Markdown Content Missing
1. Check if `DOCLING_ENABLED=true`
2. Verify file type is supported (PDF, DOCX, etc.)
3. Check file size < 50MB
4. Review service logs for processing errors

### Image OCR Not Working
1. Verify OCR reader initialized (health check)
2. Check if document contains images
3. Review logs for OCR errors
4. Note: OCR requires significant memory (~1GB per concurrent request)

### Service Timeout
1. Increase `DOCLING_PROCESSING_TIMEOUT_SECONDS`
2. Check if file is very large (> 100 pages)
3. Verify service has adequate memory
4. Consider splitting large documents

### Memory Issues
- Docling + OCR models require 4GB
- Processing large files can use additional memory
- Consider limiting concurrent requests
- Monitor with `docker stats`

## Performance Considerations

### Processing Times
- Small PDF (< 10 pages): 2-5 seconds
- Medium PDF (10-50 pages): 5-30 seconds
- Large PDF (> 50 pages): 30-120 seconds
- Heavy images: +10-20 seconds per image for OCR

### Memory Usage
- Base models: 2-3GB
- Per concurrent request: 500MB-1GB
- Peak with OCR: Up to 4GB

### Optimization Tips
1. Use `DOCLING_MAX_FILE_SIZE_MB=50` to reject huge files
2. Set timeout appropriately (5 minutes default)
3. Deploy on Railway with 4GB memory
4. Consider request limiting if many concurrent uploads

## Security Considerations

### File Validation
- Extension whitelist (PDF, DOCX, etc.)
- MIME type validation
- File size limits (50MB default)
- Path traversal protection

### API Security
- No authentication required (internal service only)
- Multipart file upload validation
- Timeout protection (prevents DoS)
- Error messages don't expose system details

### Data Privacy
- Temporary files deleted after processing
- No file persistence
- Markdown sent directly to Gemini
- No caching of processed documents

## Monitoring & Logging

### OpenTelemetry Integration
- Automatic FastAPI instrumentation
- Request/response logging
- Performance metrics
- Error tracking

### Key Metrics
- Request latency
- Success/failure rate
- Processing time per file
- OCR performance
- Memory usage

### Logging
- INFO: File processing started/completed
- WARNING: Docling errors, fallback to raw
- ERROR: Service errors, crashes
- DEBUG: Detailed processing steps

## Future Enhancements

1. **Async Processing**: Queue for very large files
2. **Image Caching**: Cache OCR results by file hash
3. **Multi-Language OCR**: Add support for non-English text
4. **Audio Transcription**: Extract audio from videos/presentations
5. **A/B Testing**: Compare RAG quality (docling vs raw)
6. **Custom Models**: Support user-provided Docling models
7. **Streaming**: Stream markdown for real-time processing

## FAQ

**Q: Can I disable docling?**
A: Yes, set `DOCLING_ENABLED=false`

**Q: What if docling service is down?**
A: Automatically fallbacks to raw file upload (if `DOCLING_FALLBACK_TO_RAW=true`)

**Q: Does it support my file type?**
A: PDF, DOCX, PPTX, XLSX, HTML are supported. See constants.py for full list.

**Q: How do I optimize processing speed?**
A: Increase memory allocation, deploy dedicated service instance, limit file size.

**Q: Can I use different Docling model?**
A: Yes, set `DOCLING_MODEL_NAME` to any Docling-supported model.

**Q: Does OCR work for all images?**
A: EasyOCR supports 80+ languages. English is default. Adjust in docling_processor.py.

## Support & Debugging

1. Check logs: `docker logs docling-service`
2. Health check: `GET /health`
3. Test endpoint: `POST /api/v1/docling/process` with sample file
4. Check environment: `env | grep DOCLING`
5. Verify connectivity: `curl docling-service:8004/health`
