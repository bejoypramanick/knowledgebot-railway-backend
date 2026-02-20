# File Upload Implementation Guide

## Overview
This guide ensures file uploads follow the same pattern as web scraping, with proper Docling integration and complete database field population.

## Database Migration

Run this migration first:
```bash
psql $DATABASE_URL < sql/migrations/add_missing_columns_to_file_uploads.sql
```

This ensures all columns exist with proper constraints.

## Key Implementation Requirements

### 1. Use Docling for File Processing
The file worker MUST call Docling service for document extraction and conversion to Markdown before uploading to FileSearch.

**Pattern from web worker:**
```python
# Check if file should use Docling
if should_use_docling_for_file(original_filename, mime_type):
    # Process with Docling
    docling_result = await process_with_docling(
        file_path=tmp_path,
        original_filename=original_filename
    )
    
    # Use the markdown output
    markdown_content = docling_result['markdown']
    processed_by_docling = True
    docling_processing_time_ms = docling_result['processing_time_ms']
    docling_images_extracted = docling_result.get('images_extracted', 0)
    docling_images_with_ocr = docling_result.get('images_with_ocr', 0)
```

### 2. Get FileSearch Store by Display Name
NEVER hardcode store IDs. Always look up by display name:

```python
from shared.file_search import get_file_search_store_by_display_name
from core.config import settings

store_display_name = settings.gemini_file_search_store_name
file_search_store_name = get_file_search_store_by_display_name(
    genai_client,
    display_name=store_display_name
)
```

### 3. Update Database with ALL Fields
After successful processing, update the file_uploads record with ALL details:

```python
from dao.fileupload_dao import FileUploadDAO

dao = FileUploadDAO()
await dao.update_file_with_processing_data(
    file_id=file_id,
    gemini_file_name=document_name,
    gemini_file_uri=document_uri,
    gemini_state="ACTIVE",
    file_size=file_size,
    char_count=char_count,
    sha256_hash=sha256_hash,
    metadata={
        'type': 'file_search',
        'file_search_store_name': file_search_store_name,
        'document_name': document_name,
        'uploaded_at': datetime.utcnow().isoformat()
    },
    processed_by_docling=processed_by_docling,
    docling_processing_time_ms=docling_processing_time_ms,
    docling_images_extracted=docling_images_extracted,
    docling_images_with_ocr=docling_images_with_ocr,
    original_file_extension=file_extension,
    original_mime_type=original_mime_type
)
```

### 4. Status Updates During Processing

**Set status to 'processing' at start:**
```python
await dao.update_file_status(file_id, 'processing')
```

**Set status to 'failed' on error:**
```python
await dao.update_file_status(file_id, 'failed', error_message=str(e))
```

**Status is set to 'completed' by update_file_with_processing_data()**

### 5. Complete Field Mapping

| Database Column | Source | Notes |
|----------------|--------|-------|
| id | Auto-generated | Primary key |
| user_role_id | Looked up from email | JOIN users table |
| original_filename | From upload | Original file name |
| display_name | From upload | User-provided display name |
| file_extension | Extracted | From filename |
| gemini_file_name | From Gemini | Document name in FileSearch |
| gemini_file_uri | From Gemini | Document URI |
| gemini_state | From Gemini | "ACTIVE" after upload |
| sha256_hash | Calculated | File hash for deduplication |
| file_size | From file | Actual file size in bytes |
| mime_type | Detected | MIME type |
| metadata | Constructed | JSON with file_search info |
| version | Default 1 | Version tracking |
| processed_by_docling | Boolean | True if Docling was used |
| docling_processing_time_ms | From Docling | Processing time |
| original_file_extension | Extracted | Original extension |
| original_mime_type | Detected | Original MIME type |
| docling_images_extracted | From Docling | Number of images |
| docling_images_with_ocr | From Docling | Images with OCR |
| created_at | Auto | Timestamp |
| updated_at | Auto | Timestamp |
| processing_status | Tracked | pending → processing → completed/failed |
| error_message | On failure | Error details |
| celery_task_id | From Celery | Task ID for tracking |
| task_revoked_at | On cancel | Cancellation timestamp |
| char_count | Calculated | Character count in markdown |

## Processing Flow

1. **Initial Record Creation** (in knowledgebase_ingestion router)
   - Create record with status='pending'
   - Store: user_role_id, original_filename, display_name, file_size, mime_type, sha256_hash, s3_url, celery_task_id

2. **Celery Task Starts** (in celery-file-worker)
   - Update status to 'processing'
   - Download file from S3
   - Validate file

3. **Docling Processing** (if applicable)
   - Call Docling service
   - Get markdown output
   - Track processing metrics

4. **FileSearch Upload**
   - Look up store by display name
   - Upload markdown to FileSearch
   - Get document_name and URI

5. **Final Database Update**
   - Update ALL fields with processing results
   - Set status to 'completed'
   - Delete file from S3

6. **Error Handling**
   - On any error: update status to 'failed'
   - Store error_message
   - Clean up temp files

## Reference Implementation

See `celery-web-worker/service/processing_service.py` for the complete pattern:
- How to call Docling
- How to upload to FileSearch
- How to update database with all fields

## Environment Variables Required

```bash
# File Worker
GEMINI_API_KEY=...
GEMINI_FILE_SEARCH_STORE_NAME=knowledgebot-search-store
DOCLING_ENABLED=true
DOCLING_SERVICE_URL=http://docling-service:8000
RAILWAY_BUCKET_NAME=...
RAILWAY_STORAGE_URL=...
RAILWAY_STORAGE_ACCESS_KEY=...
RAILWAY_STORAGE_SECRET_KEY=...
```

## Testing Checklist

- [ ] File upload creates record with status='pending'
- [ ] Celery task updates status to 'processing'
- [ ] Docling is called for supported file types
- [ ] FileSearch store is looked up by display name (not hardcoded)
- [ ] All database fields are populated after processing
- [ ] Status is set to 'completed' on success
- [ ] Status is set to 'failed' with error_message on failure
- [ ] File is deleted from S3 after processing
- [ ] user_role_id is properly looked up from email
