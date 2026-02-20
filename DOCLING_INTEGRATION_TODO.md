# Docling Integration TODO for File Worker

## Current Status
The file worker DOES call Docling service, but it doesn't capture and store all the metadata properly.

## What Needs to Be Fixed

### 1. Capture Docling Metadata
In `celery-file-worker/service/processing_service.py`, around line 450:

**Current code:**
```python
markdown_content, docling_metadata = await process_with_docling(
    tmp_path,
    original_filename,
    detected_mime_type
)
```

**Need to capture these fields from `docling_metadata`:**
- `processing_time_ms` - Time taken by Docling
- `images_extracted` - Number of images found
- `images_with_ocr` - Number of images processed with OCR
- `char_count` - Character count (if provided)

**Add after line 460:**
```python
# Capture Docling metadata
processed_by_docling = True
docling_processing_time_ms = docling_metadata.get('processing_time_ms', 0)
docling_images_extracted = docling_metadata.get('images_extracted', 0)
docling_images_with_ocr = docling_metadata.get('images_with_ocr', 0)
```

### 2. Initialize Docling Variables
At the start of `process_file_content` function (around line 240), add:

```python
# Initialize Docling tracking variables
processed_by_docling = False
docling_processing_time_ms = None
docling_images_extracted = 0
docling_images_with_ocr = 0
original_file_extension = None
original_mime_type = None
```

### 3. Track Original File Info
Before any file conversion (around line 390), capture:

```python
# Store original file info before conversion
original_file_extension = original_filename.rsplit('.', 1)[-1] if '.' in original_filename else ''
original_mime_type = detected_mime_type
```

### 4. Replace record_metadata with DAO Update
Replace the call to `file_service.record_metadata()` (around line 600) with:

```python
# Import the new DAO
from dao.fileupload_dao import FileUploadDAO

# Update file record with all processing data
dao = FileUploadDAO()

# First update status to processing
await dao.update_file_status(file_id, 'processing')

# Calculate char count from markdown if available
char_count = 0
if markdown_tmp_path and os.path.exists(markdown_tmp_path):
    try:
        with open(markdown_tmp_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
            char_count = len(markdown_content)
    except Exception as e:
        logger.warning(f"⚠️ Could not read markdown for char count: {e}")

# Update with all processing data
success = await dao.update_file_with_processing_data(
    file_id=int(file_id),
    gemini_file_name=document_name,
    gemini_file_uri=document_uri if hasattr(uploaded_file, 'uri') else None,
    gemini_state=final_state,
    file_size=file_size,
    char_count=char_count,
    sha256_hash=sha256_hash,
    metadata={
        'type': 'file_search',
        'file_search_store_name': file_search_store_name,
        'document_name': document_name,
        'uploaded_at': gemini_processed_at.isoformat() if gemini_processed_at else None
    },
    processed_by_docling=processed_by_docling,
    docling_processing_time_ms=docling_processing_time_ms,
    docling_images_extracted=docling_images_extracted,
    docling_images_with_ocr=docling_images_with_ocr,
    original_file_extension=original_file_extension,
    original_mime_type=original_mime_type
)

if not success:
    logger.error(f"❌ [DB_ERROR] Failed to update file record for {original_filename}")
    raise Exception("Database update failed")

logger.info(f"✅ [DB_UPDATE] Updated file record with all processing data")
```

### 5. Update Error Handling
In the exception handler (around line 650), update status to 'failed':

```python
except Exception as e:
    logger.error(f"❌ [PROCESSING_ERROR] Error processing file {original_filename}: {e}")
    
    # Update status to failed
    if file_id:
        from dao.fileupload_dao import FileUploadDAO
        dao = FileUploadDAO()
        await dao.update_file_status(int(file_id), 'failed', error_message=str(e))
    
    # Cleanup...
```

## Environment Variables Required

Make sure these are set in the celery-file-worker service on Railway:

```bash
# Docling Service
DOCLING_ENABLED=true
DOCLING_SERVICE_URL=https://docling-service.up.railway.app
DOCLING_TIMEOUT_SECONDS=300

# FileSearch Store
GEMINI_FILE_SEARCH_STORE_NAME=knowledgebot-search-store
GEMINI_API_KEY=...

# S3 Storage
RAILWAY_BUCKET_NAME=...
RAILWAY_STORAGE_URL=...
RAILWAY_STORAGE_ACCESS_KEY=...
RAILWAY_STORAGE_SECRET_KEY=...
```

## Testing Checklist

After making these changes:

- [ ] Upload a PDF file - verify Docling is called
- [ ] Check database - verify `processed_by_docling=true`
- [ ] Check database - verify `docling_processing_time_ms` is populated
- [ ] Check database - verify `docling_images_extracted` is populated
- [ ] Check database - verify `char_count` is populated
- [ ] Check database - verify `original_file_extension` and `original_mime_type` are captured
- [ ] Check database - verify `gemini_file_name` and `gemini_file_uri` are populated
- [ ] Check database - verify `metadata` JSON contains file_search info
- [ ] Verify file is uploaded to FileSearch store (not raw Gemini Files API)
- [ ] Verify status transitions: pending → processing → completed
- [ ] Test error case - verify status goes to 'failed' with error_message

## Reference

See `celery-web-worker/service/processing_service.py` for the complete pattern of how web scraping captures all metadata.
