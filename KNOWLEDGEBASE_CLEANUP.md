# Knowledgebase Ingestion Service Cleanup

## Overview
Now that file processing has been migrated to celery-file-worker, the knowledgebase_ingestion service has unused code and configuration that can be safely removed.

## Code to Remove

### 1. Remove Unused Functions from `knowledgebase_ingestion/service/file_service.py`

#### Function: `record_metadata` (Lines ~188-260)
**Status:** UNUSED - Never called anywhere in knowledgebase_ingestion
**Reason:** File metadata recording now happens in celery-file-worker using the new DAO

```python
# DELETE THIS ENTIRE FUNCTION:
async def record_metadata(self, user_email: str, original_filename: str, file_display_name: str,
                         file_ext: str, uploaded_file: Any,
                         file_size: int, sha256_hash: str,
                         final_state: str, gemini_processed_at: Any, mime_type: str, version: int = 1,
                         file_search_metadata: Dict[str, Any] = None):
    # ... entire function body ...
```

#### Function: `process_file_upload` (Lines ~331-342)
**Status:** UNUSED - Never called anywhere
**Reason:** File processing now happens in celery-file-worker

```python
# DELETE THIS ENTIRE FUNCTION:
async def process_file_upload(self, file_data: dict, user_email: str) -> dict:
    """Process single file upload with business logic"""
    # ... entire function body ...
```

### 2. Remove Docling Configuration from `knowledgebase_ingestion/core/config.py`

**Lines to remove (~29-32):**
```python
# DELETE THESE LINES:
# Docling Service Configuration (plug-and-play)
docling_enabled: bool = True  # Set to False to disable docling and use raw uploads
docling_timeout_seconds: int = 300  # Processing timeout (5 minutes)
docling_fallback_to_raw: bool = True  # Fallback to raw upload if docling fails/times out
```

**Also remove from line ~17:**
```python
# DELETE THIS LINE:
docling_service_url: str = "http://localhost:8004"
```

**Reason:** knowledgebase_ingestion never calls Docling - only celery-file-worker and celery-web-worker do

## Environment Variables to Remove from Railway

Remove these from the **knowledgebase-ingestion** service in Railway:
- `DOCLING_ENABLED`
- `DOCLING_FALLBACK_TO_RAW`
- `DOCLING_SERVICE_URL`
- `DOCLING_TIMEOUT_SECONDS`

**Keep these variables in:**
- celery-file-worker ✅
- celery-web-worker ✅

## Functions to KEEP in file_service.py

These are still used by knowledgebase_ingestion:

### ✅ `check_duplicate_file` 
Used by: File upload validation before queuing to Celery

### ✅ `delete_existing_file_record`
Used by: File deletion endpoints

### ✅ `get_admin_user_role_id`
Used by: User role validation (though this might be replaced by the new auth.py helper)

### ✅ `get_file_by_id`
Used by: File status queries

### ✅ `get_all_files`
Used by: File listing endpoints

### ✅ `handle_duplicate_check`
Used by: Duplicate detection logic

## What knowledgebase_ingestion DOES Now

The service is now a lightweight API gateway that:
1. ✅ Receives file uploads via HTTP
2. ✅ Validates files (extension, size, MIME type)
3. ✅ Checks for duplicates
4. ✅ Uploads files to S3
5. ✅ Creates database records with status='pending'
6. ✅ Dispatches tasks to Celery workers
7. ✅ Provides status query endpoints
8. ✅ Handles file deletion

## What knowledgebase_ingestion DOES NOT Do

The service no longer:
- ❌ Processes files
- ❌ Calls Docling
- ❌ Uploads to Gemini/FileSearch
- ❌ Updates file metadata after processing
- ❌ Calculates file metrics

All of the above now happens in **celery-file-worker**.

## Benefits of Cleanup

1. **Clearer separation of concerns** - API layer vs processing layer
2. **Reduced dependencies** - No need for Gemini SDK in knowledgebase_ingestion
3. **Simpler configuration** - Fewer environment variables
4. **Less confusion** - No duplicate/unused code
5. **Easier maintenance** - Single source of truth for file processing

## Testing After Cleanup

After removing the code:
1. ✅ File upload should still work (creates record, queues to Celery)
2. ✅ File status queries should still work
3. ✅ File deletion should still work
4. ✅ Duplicate detection should still work
5. ✅ File processing happens in celery-file-worker
6. ✅ No errors about missing Docling config

## Migration Summary

| Functionality | Before | After |
|--------------|--------|-------|
| File validation | knowledgebase_ingestion | knowledgebase_ingestion ✅ |
| S3 upload | knowledgebase_ingestion | knowledgebase_ingestion ✅ |
| DB record creation | knowledgebase_ingestion | knowledgebase_ingestion ✅ |
| Celery dispatch | knowledgebase_ingestion | knowledgebase_ingestion ✅ |
| File processing | ❌ knowledgebase_ingestion | celery-file-worker ✅ |
| Docling call | ❌ knowledgebase_ingestion | celery-file-worker ✅ |
| Gemini upload | ❌ knowledgebase_ingestion | celery-file-worker ✅ |
| DB metadata update | ❌ knowledgebase_ingestion | celery-file-worker ✅ |
