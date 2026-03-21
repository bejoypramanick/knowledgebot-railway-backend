"""
File Upload Router
Handles all file upload related endpoints
"""
from fastapi import APIRouter, HTTPException, Request, UploadFile, Form
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
import mimetypes

from knowledgebase_ingestion.utils.auth import extract_user_from_request
from knowledgebase_ingestion.utils.logging import get_otel_logger
from knowledgebase_ingestion.service.fileupload_service import (
    get_fileupload_dao, get_pending_files, get_file_by_id,
    cancel_files, update_file_status, delete_file,
    validate_file_upload, delete_all_knowledge
)
from knowledgebase_ingestion.service.file_service import get_file_service
from knowledgebase_ingestion.service.upload_constraints_service import get_upload_constraints_service
from knowledgebase_ingestion.dao.webcrawl_dao import WebCrawlDAO
from shared.redis_message_queue import RedisMessageQueue
from shared.celery_dispatcher import file_celery

logger = get_otel_logger("fileupload_router", "knowledgebase-ingestion")


def get_mime_type_fallback(filename: str, db_mime_type: Optional[str] = None) -> str:
    """Get MIME type from database or derive from filename as fallback."""
    if db_mime_type:
        return db_mime_type
    # Fallback: derive from filename
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"

# NOTE: Prefix is provided by include_router() in main.py
# Do NOT include full path here to avoid double prefix (prefix=/api/v1/knowledgebase in include_router)
router = APIRouter(tags=["file-upload"])

# =================================
# FILE UPLOAD CONSTRAINTS ENDPOINT
# =================================

@router.get("/upload/constraints")
async def get_upload_constraints(request: Request = None):
    """
    Get file upload constraints (max file size, allowed extensions, MIME types).

    Returns:
        Upload constraints including:
        - max_file_size: Maximum file size in bytes
        - max_file_size_display: Human-readable file size (e.g., "100 MB")
        - allowed_extensions: List of allowed file extensions
        - allowed_mime_types: List of allowed MIME types
        - supported_file_types: Detailed metadata for each file type
        - file_categories: Grouped by category (document, spreadsheet, etc.)
    """
    try:
        logger.info("=" * 80)
        logger.info("📋 [CONSTRAINTS_REQUEST] Upload constraints requested")
        logger.info("=" * 80)

        # Extract authenticated user information (optional, just for logging)
        try:
            user_email, user_id = extract_user_from_request(request)
            logger.info(f"👤 [USER] Requested by: {user_email}")
        except Exception:
            logger.info(f"👤 [USER] Requested by: unauthenticated client")

        # Get constraints from service
        logger.info("🔧 [LOAD] Loading upload constraints from service...")
        constraints_service = get_upload_constraints_service()
        constraints = constraints_service.get_constraints()

        logger.info("=" * 80)
        logger.info("✅ [CONSTRAINTS_SUCCESS] Upload constraints retrieved successfully")
        logger.info("=" * 80)
        logger.info(f"📊 [DETAILS] Max file size: {constraints['constraints']['max_file_size_display']}")
        logger.info(f"📊 [DETAILS] Allowed extensions: {len(constraints['constraints']['allowed_extensions'])}")
        logger.info(f"📊 [DETAILS] Allowed MIME types: {len(constraints['constraints']['allowed_mime_types'])}")
        logger.info(f"📊 [DETAILS] File categories: {', '.join(constraints['constraints']['file_categories'].keys())}")

        return constraints

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [CONSTRAINTS_ERROR] Error getting upload constraints: {e}")
        logger.error("=" * 80)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# FILE LISTING ENDPOINTS
# =================================

@router.get("/files")
async def get_all_files(request: Request = None, status: Optional[str] = None):
    """
    Get all files and websites with their current status and hierarchical structure
    
    Query Parameters:
        status: Optional filter for item status
            - 'inactive': Returns items that are NOT pending, processing, queued, and NOT completed (cancelled, deleted, failed)
            - None (default): Returns pending, processing, queued, and completed items
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Get files based on status parameter
        from knowledgebase_ingestion.dao.fileupload_dao import FileUploadDAO
        fileupload_dao = FileUploadDAO()
        
        if status == 'inactive':
            # Get items that are NOT pending and NOT completed
            files = await fileupload_dao.get_inactive_files()
        else:
            # Get items that are pending or completed
            files = await fileupload_dao.get_active_files()

        # Get hierarchical websites based on status parameter
        webcrawl_dao = WebCrawlDAO()
        if status == 'inactive':
            websites = await webcrawl_dao.get_hierarchical_websites(include_inactive=True)
        else:
            websites = await webcrawl_dao.get_hierarchical_websites(include_inactive=False)

        # Format files for response
        files_list = [
            {
                "id": str(f['id']),
                "type": "file",
                "source": "upload",  # Add source field for UI filtering
                "name": f['original_filename'],
                "file_extension": f.get('file_extension'),  # Include file extension
                "mime_type": get_mime_type_fallback(f['original_filename'], f.get('mime_type')),  # Include MIME type with fallback
                "processing_status": f['processing_status'],
                "error_message": f['error_message'],
                "size_bytes": f.get('file_size', 0),  # Map file_size to size_bytes for UI
                "char_count": f.get('char_count', 0),
                "processed_content_s3_key": f.get('processed_content_s3_key'),
                "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
            }
            for f in files
        ]

        return {
            "success": True,
            "files": files_list,
            "websites": websites,  # hierarchical website tree (filtered)
            "count": len(files_list),
            "sources": {
                "upload": len(files_list),
                "scrape": len(websites)  # Count of root-level websites
            }
        }
    except Exception as e:
        logger.error(f"Error getting files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_file_processing_status(request: Request = None):
    """Get processing status for all pending/processing files"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get all files with their current status
        files = await get_pending_files()

        return {
            "success": True,
            "files": [
                {
                    "id": str(f['id']),
                    "type": "file",
                    "name": f['original_filename'],
                    "file_extension": f.get('file_extension'),  # Include file extension
                    "mime_type": get_mime_type_fallback(f['original_filename'], f.get('mime_type')),  # Include MIME type with fallback
                    "processing_status": f['processing_status'],
                    "error_message": f['error_message'],
                    "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                    "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
                }
                for f in files
            ]
        }
    except Exception as e:
        logger.error(f"Error getting file processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_file_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single file"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get file record
        file_record = await get_file_by_id(item_id)
        if file_record:
            return {
                "success": True,
                "type": "file",
                "id": str(file_record['id']),
                "name": file_record['original_filename'],
                "processing_status": file_record['processing_status'],
                "error_message": file_record['error_message'],
                "created_at": file_record['created_at'].isoformat() if file_record['created_at'] else None,
                "updated_at": file_record['updated_at'].isoformat() if file_record['updated_at'] else None
            }

        raise HTTPException(status_code=404, detail=f"File {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_file_task(item_id: str, request: Request = None):
    """
    Cancel a pending or processing file task.
    Sets Redis cancellation flag and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Revoke queued Celery task (stops it before it starts)
        file_celery.control.revoke(item_id, terminate=False)
        logger.info(f"✅ Revoked Celery task {item_id} from queue")

        # Set Redis cancellation flag for in-progress tasks
        redis_queue = RedisMessageQueue()
        success = redis_queue.set_task_cancelled(item_id)

        if success:
            logger.info(f"✅ Set cancellation flag for file task {item_id}")

            # Update database status to cancelled
            files_cancelled = await cancel_files()

            if files_cancelled > 0:
                logger.info(f"✅ Marked {files_cancelled} file tasks as cancelled in database")
            else:
                logger.warning(f"⚠️ File task {item_id} not found or already completed")
        else:
            logger.error(f"❌ Failed to set cancellation flag for file task {item_id}")

        return {
            "success": success,
            "message": "File task cancellation requested" if success else "Failed to cancel file task",
            "item_id": item_id
        }
        
    except Exception as e:
        logger.error(f"Error cancelling file task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_file_tasks(request: Request = None):
    """
    Cancel all pending and processing file tasks.
    Sets Redis cancellation flags and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Purge all queued Celery tasks (prevents pending tasks from being picked up)
        file_celery.control.purge()
        logger.info("✅ Purged Celery file_processing queue")

        # Also clear any legacy Redis queue keys
        redis_queue = RedisMessageQueue()
        redis_queue.clear_file_task_queue()
        logger.info("✅ Cleared file task queue in Redis")

        # Mark all pending/processing tasks as cancelled in database
        files_cancelled = await cancel_files()

        if files_cancelled > 0:
            logger.info(f"✅ Marked {files_cancelled} file tasks as cancelled in database")

        return {
            "success": True,
            "message": f"Cancelled {files_cancelled} file tasks",
            "cancelled_count": files_cancelled
        }

    except Exception as e:
        logger.error(f"Error cancelling all file tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# DELETE ENDPOINTS
# =================================

@router.delete("/files/{file_id}")
async def delete_file_endpoint(file_id: str, request: Request = None, hard_delete: bool = False):
    """
    Delete an uploaded file with COMPLETE cleanup of all data points.

    This operation performs comprehensive deletion:
    1. Terminates Celery task (file_processing queue)
    2. Cleans Redis task state and cancellation flags
    3. Deletes from Gemini (raw file + FileSearch document)
    4. Deletes from S3 (raw upload + processed markdown)
    5. Updates database (soft delete by default, hard delete optional)

    Query Parameters:
        hard_delete: If true, hard delete from database (default: false, soft delete)

    Returns:
        Complete deletion report with cleanup summary
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        logger.info(f"🗑️  [FILE_DELETE_REQUEST] Deleting file {file_id} (hard_delete={hard_delete})")
        logger.info(f"   Requested by: {user_email}")

        from knowledgebase_ingestion.service.comprehensive_deletion_service import (
            comprehensive_deletion_service,
            ItemType
        )

        # Delete file with complete cleanup
        result = await comprehensive_deletion_service.delete_item(
            item_id=file_id,
            item_type=ItemType.FILE,
            hard_delete=hard_delete
        )

        if result.get('success'):
            logger.info(f"✅ [FILE_DELETE_SUCCESS] File {file_id} deleted completely")
            logger.info(f"   Celery tasks revoked: {result['cleanup_summary']['celery_tasks_revoked']}")
            logger.info(f"   Redis keys deleted: {result['cleanup_summary']['redis_keys_deleted']}")
            logger.info(f"   Gemini files deleted: {result['cleanup_summary']['gemini_files_deleted']}")
            logger.info(f"   Gemini FileSearch docs deleted: {result['cleanup_summary']['gemini_filesearch_docs_deleted']}")
            logger.info(f"   S3 raw files deleted: {result['cleanup_summary']['s3_raw_files_deleted']}")
            logger.info(f"   S3 processed files deleted: {result['cleanup_summary']['s3_processed_files_deleted']}")
            return result
        else:
            error_msg = result.get('errors')[0].get('error') if result.get('errors') else 'Deletion failed'
            logger.error(f"❌ [FILE_DELETE_FAILED] {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        error_traceback = traceback.format_exc()
        logger.error(f"❌ [FILE_DELETE_ERROR] Error deleting file {file_id}: {error_msg}")
        logger.error(f"   Traceback: {error_traceback}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/delete-all")
async def delete_all_knowledge_endpoint(request: Request = None):
    """
    Delete all files and websites from knowledge base.
    This operation performs a SOFT DELETE (marks as deleted, doesn't remove records):
    1. Removes all files from Gemini FileSearch store
    2. Clears all Redis task queues (file_processing, web_crawling)
    3. Marks all file records with status='deleted' (soft delete for audit trail)
    4. Marks all website records with status='deleted' (soft delete for audit trail)

    Records are retained in database with status='deleted' for audit and recovery purposes.

    REQUIRES: X-Confirm-Delete-All: true header (safety check to prevent accidental deletion)
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Safety check: require confirmation header
        confirm_header = request.headers.get("X-Confirm-Delete-All")
        if confirm_header != "true":
            logger.warning(f"❌ [DELETE_ALL_DENIED] Delete all requested without confirmation header by {user_email}")
            raise HTTPException(
                status_code=400,
                detail="Delete all operation requires X-Confirm-Delete-All: true header"
            )

        logger.info("=" * 80)
        logger.info(f"🔴 [DELETE_ALL_REQUEST] Delete all knowledge base requested by {user_email}")
        logger.info("=" * 80)

        # Call delete all service function
        result = await delete_all_knowledge()

        if result.get("success"):
            logger.info("=" * 80)
            logger.info(f"✅ [DELETE_ALL_SUCCESS] Knowledge base cleared and FileSearch store recreated")
            logger.info("=" * 80)
            logger.info(f"   FileSearch stores deleted: {result.get('filesearch_stores_deleted')}")
            logger.info(f"   New FileSearch store: {result.get('new_store_name')}")
            logger.info(f"   S3 files deleted: {result.get('s3_files_deleted')}")
            logger.info(f"   Websites marked as deleted: {result.get('websites_marked_deleted')}")
            logger.info(f"   Redis queues cleared: {result.get('redis_queues_cleared')}")
            logger.info(f"   Database records retained with status='deleted' for audit trail")
            logger.info(f"   Cleared by: {user_email}")

            return {
                "success": True,
                "message": result.get("message"),
                "filesearch_stores_deleted": result.get("filesearch_stores_deleted"),
                "new_store_name": result.get("new_store_name"),
                "s3_files_deleted": result.get("s3_files_deleted"),
                "websites_marked_deleted": result.get("websites_marked_deleted"),
                "redis_queues_cleared": result.get("redis_queues_cleared"),
                "note": "Database records retained with status='deleted' for audit trail and recovery. FileSearch store is now empty and ready for new content."
            }
        else:
            logger.error("=" * 80)
            logger.error(f"❌ [DELETE_ALL_FAILED] Knowledge base delete failed")
            logger.error("=" * 80)
            logger.error(f"   Message: {result.get('message')}")
            if result.get("errors"):
                for error in result.get("errors", []):
                    logger.error(f"   Error: {error}")

            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Failed to delete knowledge base")
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [DELETE_ALL_ERROR] Error deleting all knowledge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# DOWNLOAD ENDPOINT
# =================================

@router.get("/download/{file_id}")
async def download_processed_content(file_id: str, request: Request = None):
    """
    Get a presigned download URL for the processed markdown content of a file or website.
    Returns a presigned S3 URL that the UI can use to download the converted .md file.
    Supports both file_uploads and scraped_websites tables.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text
        from shared.s3_file_storage import s3_file_storage

        async with get_db_session() as session:
            # Try file_uploads table first
            file_query = """
                SELECT original_filename as name, processed_content_s3_key
                FROM file_uploads WHERE id = :id
            """
            result = await session.execute(text(file_query), {"id": file_id})
            record = result.mappings().first()

            # If not found, try scraped_websites table
            if not record:
                website_query = """
                    SELECT original_url as name, processed_content_s3_key
                    FROM scraped_websites WHERE id = :id
                """
                result = await session.execute(text(website_query), {"id": file_id})
                record = result.mappings().first()

            if not record:
                raise HTTPException(status_code=404, detail="File or website not found")

            s3_key = record['processed_content_s3_key']
            if not s3_key:
                raise HTTPException(status_code=404, detail="No processed content available for this item")

            # Generate presigned download URL
            success, url = s3_file_storage.generate_presigned_url(s3_key, expiration=3600)
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {url}")

            # Derive the .md filename
            # For files: strip extension and add .md
            # For websites: use URL slug and add .md
            original = record['name']
            if '.' in original and not original.startswith('http'):
                # Likely a filename
                md_filename = original.rsplit('.', 1)[0] + '.md'
            elif original.startswith('http'):
                # Likely a URL - extract domain/path
                from urllib.parse import urlparse
                parsed = urlparse(original)
                path = parsed.path.strip('/').replace('/', '_')
                domain = parsed.netloc.replace('www.', '')
                md_filename = f"{domain}_{path}.md" if path else f"{domain}.md"
            else:
                # Fallback
                md_filename = original + '.md'

            return {
                "success": True,
                "download_url": url,
                "filename": md_filename
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating download URL for item {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# FILE UPLOAD ENDPOINTS
# =================================

@router.post("/upload/async")
async def upload_file_async(
    file: UploadFile = Form(...),
    file_display_name: Optional[str] = Form(None),
    replace_existing: bool = Form(False),
    sha256_hash: Optional[str] = Form(None),
    request: Request = None
):
    """
    Async file upload endpoint with Celery task queue - returns immediately with pending status.
    
    Args:
        file: The file to upload
        file_display_name: Optional display name for the file
        replace_existing: If True, replace existing file with same name (marks old as deleted)
        request: HTTP request object
    """
    logger.info("=" * 80)
    logger.info("📥 [UPLOAD_START] New file upload request received")
    logger.info("=" * 80)
    logger.info(f"   Replace existing: {replace_existing}")
    logger.info(f"   Frontend hash provided: {sha256_hash}")

    try:
        # Extract authenticated user information
        logger.info("🔐 [AUTH] Extracting user information from request")
        user_email, user_id = extract_user_from_request(request)
        logger.info(f"   User Email: {user_email}")
        logger.info(f"   User ID (from header): {user_id}")
        
        # Look up user_role_id from database using email
        from knowledgebase_ingestion.utils.auth import get_user_role_id_from_email
        user_role_id = await get_user_role_id_from_email(user_email)
        logger.info(f"   User Role ID (from DB): {user_role_id}")

        # Validate file
        logger.info(f"✔️  [VALIDATION] Validating file: {file.filename}")
        file_size_initial = await get_file_size(file)
        logger.info(f"   File Size: {file_size_initial} bytes")

        validation_result = await validate_file_upload(file, file_size_initial, replace_existing)
        if not validation_result['valid']:
            # Check if it's a duplicate (409) or other validation error (400)
            if validation_result.get('is_duplicate'):
                logger.warning(f"⚠️  [DUPLICATE_DETECTED] {validation_result.get('error')}")
                error_response = {
                    "success": False,
                    "error": validation_result.get('error'),
                    "reason": validation_result.get('reason'),
                    "match_type": validation_result.get('match_type', 'filename'),
                    "detail": f"File '{validation_result.get('existing_file_name')}' already exists (Status: {validation_result.get('existing_file_status')})",
                    "existing_file_id": validation_result.get('existing_file_id'),
                    "existing_file_name": validation_result.get('existing_file_name'),
                }
                logger.error(f"❌ [UPLOAD_REJECTED] {error_response}")
                raise HTTPException(status_code=409, detail=error_response)
            else:
                logger.error(f"❌ [VALIDATION_FAILED] {validation_result['error']}")
                raise HTTPException(status_code=400, detail=validation_result['error'])

        logger.info(f"✅ [VALIDATION_SUCCESS] File validation passed")
        logger.info(f"   Original Name: {validation_result['original_filename']}")
        logger.info(f"   Display Name: {file_display_name}")
        logger.info(f"   MIME Type: {validation_result['mime_type']}")
        logger.info(f"   File Extension: {validation_result.get('file_extension', 'unknown')}")

        # Read file into bytes and upload to S3, then dispatch to worker
        try:
            logger.info("📖 [FILE_READ] Reading file into memory")
            file_bytes = await file.read()
            file_size = len(file_bytes)
            logger.info(f"✅ [FILE_READ_SUCCESS] File read: {file_size} bytes")

            # Calculate file hash FIRST
            logger.info("🔐 [HASH_CALCULATION] Calculating file hash")
            file_sha256 = None
            try:
                from knowledgebase_ingestion.utils.hash import calculate_file_hash
                file_sha256 = await calculate_file_hash(file_bytes)
                logger.info(f"✅ [HASH_CALCULATED] SHA256: {file_sha256}")
                if not file_sha256:
                    logger.warning(f"⚠️ [HASH_CALCULATION] Hash calculation returned empty/None value")
            except Exception as hash_err:
                logger.error(f"❌ [HASH_CALCULATION] Failed to calculate hash: {hash_err}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

            # Check for duplicates (by filename and hash)
            logger.info("🔍 [DUPLICATE_CHECK] Checking for duplicate files...")
            from knowledgebase_ingestion.service.file_service import get_file_service
            file_service = get_file_service()
            duplicate_check = await file_service.handle_duplicate_check(
                validation_result['original_filename'],
                replace_existing=replace_existing,
                sha256_hash=file_sha256
            )

            if not duplicate_check['allow']:
                logger.warning(f"⚠️  [DUPLICATE_DETECTED] {duplicate_check.get('detail', 'File duplicate detected')}")
                error_response = {
                    "success": False,
                    "error": "Duplicate file detected",
                    "reason": duplicate_check.get('reason'),
                    "match_type": duplicate_check.get('match_type', 'unknown'),
                    "detail": duplicate_check.get('detail'),
                    "existing_file_id": duplicate_check.get('existing_file_id'),
                    "existing_file_name": duplicate_check.get('existing_file_name'),
                    "existing_file_hash": duplicate_check.get('existing_file_hash'),
                }
                logger.error(f"❌ [UPLOAD_REJECTED] {error_response}")
                raise HTTPException(status_code=409, detail=error_response)

            logger.info(f"✅ [DUPLICATE_CHECK_PASSED] No duplicates found, proceeding with upload")

            # Upload to S3
            logger.info(f"☁️  [S3_UPLOAD_START] Uploading to S3 storage")
            logger.info(f"   Filename: {validation_result['filename']}")
            logger.info(f"   Size: {file_size} bytes")
            logger.info(f"   Type: upload")

            from shared.s3_file_storage import s3_file_storage

            success, s3_result = await s3_file_storage.upload_file(
                file_data=file_bytes,
                original_filename=validation_result['filename'],
                file_type="upload"
            )

            if not success:
                logger.error(f"❌ [S3_UPLOAD_FAILED] {s3_result}")
                raise HTTPException(status_code=500, detail=f"File upload to S3 failed: {s3_result}")

            s3_key = s3_result
            logger.info(f"✅ [S3_UPLOAD_SUCCESS] File uploaded to S3")
            logger.info(f"   S3 Key: {s3_key}")

            # Create file record in database FIRST with placeholder task_id
            logger.info(f"💾 [DB_INSERT_START] Creating file record in database")
            
            import uuid
            placeholder_task_id = str(uuid.uuid4())
            logger.info(f"   Placeholder Task ID: {placeholder_task_id}")

            # Extract file extension from filename
            import os
            file_extension = os.path.splitext(validation_result['original_filename'])[1].lower()
            if file_extension.startswith('.'):
                file_extension = file_extension[1:]  # Remove leading dot

            record_data = {
                'user_role_id': user_role_id,  # Use user_role_id from database
                'original_filename': validation_result['original_filename'],
                'file_display_name': file_display_name or validation_result['filename'],
                'size_bytes': file_size,
                'mime_type': validation_result['mime_type'],
                'file_extension': file_extension,
                'processing_status': 'pending',
                'sha256_hash': file_sha256,
                's3_key': s3_key,
                'celery_task_id': placeholder_task_id
            }

            logger.info(f"📝 [DB_INSERT_DATA] Record data:")
            logger.info(f"   user_role_id: {record_data['user_role_id']}")
            logger.info(f"   original_filename: {record_data['original_filename']}")
            logger.info(f"   file_display_name: {record_data['file_display_name']}")
            logger.info(f"   size_bytes: {record_data['size_bytes']}")
            logger.info(f"   mime_type: {record_data['mime_type']}")
            logger.info(f"   file_extension: {record_data['file_extension']}")
            logger.info(f"   processing_status: {record_data['processing_status']}")
            logger.info(f"   sha256_hash: {record_data['sha256_hash']}")
            logger.info(f"   s3_key: {record_data['s3_key']}")
            logger.info(f"   celery_task_id: {record_data['celery_task_id']}")

            from knowledgebase_ingestion.service.fileupload_service import create_file_record
            file_id = await create_file_record(record_data)

            if not file_id:
                logger.error(f"❌ [DB_INSERT_FAILED] Failed to create file record in database")
                raise HTTPException(status_code=500, detail="Failed to create file record")

            logger.info(f"✅ [DB_INSERT_SUCCESS] File record created in database")
            logger.info(f"   File ID: {file_id}")

            # Dispatch to Celery worker — Celery assigns the task ID
            logger.info(f"📤 [CELERY_DISPATCH_START] Dispatching file task to Celery worker")
            logger.info(f"   Queue: file_processing")
            logger.info(f"   Task: tasks.process_file_upload_task")
            logger.info(f"   File ID: {file_id}")

            result = file_celery.send_task(
                'tasks.process_file_upload_task',
                args=[
                    file_id,  # Pass file_id instead of individual parameters
                    user_email  # Keep user_email for logging context
                ],
                queue='file_processing'
            )
            celery_task_id = result.id

            logger.info(f"✅ [CELERY_DISPATCH_SUCCESS] Task dispatched to Celery")
            logger.info(f"   Celery Task ID: {celery_task_id}")
            logger.info(f"   Args:")
            logger.info(f"     - file_id: {file_id}")
            logger.info(f"     - user_email: {user_email}")

            # Update DB record with the real Celery task ID
            logger.info(f"💾 [DB_UPDATE] Updating DB with real Celery task ID: {celery_task_id}")
            dao = get_fileupload_dao()
            try:
                await dao.update_celery_task_id(file_id, celery_task_id)
                logger.info(f"✅ [DB_UPDATE_SUCCESS] DB updated with Celery task ID")
                logger.info(f"⏱️  [DB_COMMIT_WAIT] Waited for DB commit")
            except Exception as db_err:
                import traceback
                logger.error(f"❌ [DB_UPDATE_ERROR] Failed to update DB with task ID: {db_err}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise

            logger.info("=" * 80)
            logger.info("✨ [UPLOAD_COMPLETE] File upload process completed successfully")
            logger.info("=" * 80)

            # Fetch the complete file record for UI population (like webcrawl does)
            try:
                from knowledgebase_ingestion.dao.fileupload_dao import FileUploadDAO
                dao = FileUploadDAO()
                full_file = await dao.get_file_by_id(file_id)
                
                if full_file:
                    logger.info(f"✅ [FILE_FETCH] Fetched full file record for UI")
                    return {
                        "success": True,
                        "message": "File processing task queued successfully",
                        "task_id": celery_task_id,
                        "file_id": str(file_id),
                        "id": str(file_id),
                        "type": "file",
                        "source": "upload",
                        "name": full_file.get('original_filename'),
                        "processing_status": full_file.get('processing_status', 'pending'),
                        "error_message": full_file.get('error_message'),
                        "size_bytes": full_file.get('file_size', 0),  # Map file_size to size_bytes for UI
                        "char_count": full_file.get('char_count', 0),
                        "created_at": full_file.get('created_at').isoformat() if full_file.get('created_at') else None,
                        "updated_at": full_file.get('updated_at').isoformat() if full_file.get('updated_at') else None,
                        "status": "Queued"
                    }
            except Exception as fetch_err:
                logger.warning(f"⚠️ Could not fetch full file record: {fetch_err}")

            # Fallback response if fetch fails
            return {
                "success": True,
                "message": "File processing task queued successfully",
                "task_id": celery_task_id,
                "file_id": str(file_id),
                "id": str(file_id),
                "type": "file",
                "source": "upload",
                "name": validation_result['original_filename'],
                "processing_status": "pending",
                "error_message": None,
                "size_bytes": file_size,
                "char_count": 0,
                "created_at": None,
                "updated_at": None,
                "status": "Queued"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error queuing file task: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in async file upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "file-upload",
        "timestamp": "2025-01-19T00:00:00Z"
    }


# Helper functions
async def get_file_size(file: UploadFile) -> int:
    """Get file size from UploadFile object."""
    try:
        # Reset file position and read size
        await file.seek(0)
        content = await file.read()
        await file.seek(0)
        return len(content)
    except Exception as e:
        logger.error(f"Error getting file size: {e}")
        return 0


async def calculate_file_hash(file_bytes: bytes) -> str:
    """Calculate SHA256 hash of file bytes."""
    import hashlib
    return hashlib.sha256(file_bytes).hexdigest()
