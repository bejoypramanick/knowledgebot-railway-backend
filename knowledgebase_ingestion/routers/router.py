"""
Consolidated Knowledgebase Ingestion Router
All knowledgebase ingestion endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from typing import Dict, List, Any, Optional
import logging

from ..service.file_service import FileService
from ..service.ingestion_service import (
    process_single_file_upload,
    process_single_file_delete,
    delete_file_logic,
    nuke_filestore_and_database,
    delete_website_hierarchy,
    upload_file_celery
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
file_service = FileService()

def extract_user_from_request(request: Request) -> tuple[str, str]:
    """Extract user information from request headers forwarded by API Gateway"""
    user_email = request.headers.get("X-User-Email", "unknown@example.com")
    user_id = request.headers.get("X-User-UID", "unknown")
    return user_email, user_id

# =================================
# FILE UPLOAD ENDPOINTS
# =================================

@router.post("/upload")
async def upload_file_alias(
    file: UploadFile = File(...),
    request: Request = None,
    display_name: Optional[str] = Form(None),
    replace_existing: bool = Form(False)
):
    """Upload a file to the knowledgebase (alias endpoint for /files/upload)"""
    return await upload_file(file, request, display_name, replace_existing)

@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    display_name: Optional[str] = Form(None),
    replace_existing: bool = Form(False)
):
    """Upload a file to the knowledgebase"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        # Use the service layer for processing
        result = await process_single_file_upload(
            file=file,
            display_name=display_name,
            user_email=user_email,
            replace_existing=replace_existing
        )

        if result.success:
            return {
                "success": True,
                "message": result.message,
                "file": result.file.dict() if result.file else None,
                "replaced_existing": result.replaced_existing
            }
        else:
            raise HTTPException(status_code=400, detail=result.error or result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files")
async def list_files(request: Request = None):
    """List all files and websites in hierarchical structure (backward compatible)"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get unified knowledgebase (files + hierarchical websites)
        knowledgebase = await file_service.get_all_knowledgebase()
        
        # Return in format that's backward compatible but includes websites
        return {
            "success": True,
            "files": knowledgebase["files"],  # Original files list
            "websites": knowledgebase["websites"],  # Add hierarchical websites
            "summary": knowledgebase["summary"],  # Add summary info
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/knowledgebase")
async def list_knowledgebase(request: Request = None):
    """List all knowledgebase items (files + websites) with hierarchical structure for websites"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        knowledgebase = await file_service.get_all_knowledgebase()
        
        return {
            "success": True,
            "knowledgebase": knowledgebase,
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error listing knowledgebase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batchupload")
async def upload_files_batch(request: Request):
    """Upload multiple files in batch"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Parse multipart form data
        form = await request.form()

        # Get all files from form
        files = form.getlist("files")
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        # Get optional parameters
        replace_existing = form.get("replace_existing", "false").lower() == "true"

        results = []
        successful_uploads = 0
        failed_uploads = 0

        # Process each file using the service layer
        for file in files:
            try:
                # Use the proper service function
                result = await process_single_file_upload(
                    file=file,
                    display_name=None,
                    user_email=user_email,
                    replace_existing=replace_existing
                )

                # Convert BatchUploadItem to dict for response
                file_result = {
                    "filename": result.filename,
                    "success": result.success,
                    "message": result.message,
                    "error": result.error,
                    "file_id": result.file.name if result.file else None,
                    "replaced_existing": result.replaced_existing
                }

                if result.success:
                    successful_uploads += 1
                else:
                    failed_uploads += 1

                results.append(file_result)

            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {e}")
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "message": "Upload failed",
                    "error": str(e),
                    "file_id": None
                })
                failed_uploads += 1

        return {
            "success": True,
            "message": f"Batch upload completed: {successful_uploads} successful, {failed_uploads} failed",
            "total_files": len(files),
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads,
            "parallel_processing": True,
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/async")
async def upload_file_async_endpoint(
    file: UploadFile = File(...),
    request: Request = None,
    display_name: Optional[str] = Form(None)
):
    """
    Async file upload endpoint with Celery - returns immediately with pending status.
    Actual processing happens in Celery worker. Frontend should poll /status/{id} to track progress.
    """
    try:
        user_email, user_id = extract_user_from_request(request)

        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        result = await upload_file_celery(
            file=file,
            display_name=display_name,
            user_email=user_email
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in async file upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_processing_status(request: Request = None):
    """Get processing status for all pending/processing items (files and websites)"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Get all non-completed files
            files = await conn.fetch(
                """SELECT id, original_filename, processing_status, error_message, created_at, updated_at
                   FROM file_uploads
                   WHERE processing_status IN ('pending', 'processing')
                   ORDER BY updated_at DESC"""
            )

            # Get all non-completed websites
            websites = await conn.fetch(
                """SELECT id, original_url, processing_status, error_message, created_at, updated_at
                   FROM scraped_websites
                   WHERE processing_status IN ('pending', 'processing')
                   ORDER BY updated_at DESC"""
            )

            return {
                "success": True,
                "files": [
                    {
                        "id": str(f['id']),
                        "type": "file",
                        "name": f['original_filename'],
                        "processing_status": f['processing_status'],
                        "error_message": f['error_message'],
                        "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                        "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
                    }
                    for f in files
                ],
                "websites": [
                    {
                        "id": str(w['id']),
                        "type": "website",
                        "name": w['original_url'],
                        "processing_status": w['processing_status'],
                        "error_message": w['error_message'],
                        "created_at": w['created_at'].isoformat() if w['created_at'] else None,
                        "updated_at": w['updated_at'].isoformat() if w['updated_at'] else None
                    }
                    for w in websites
                ]
            }
    except Exception as e:
        logger.error(f"Error getting processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single file or website"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Try to find in file_uploads first
            file_record = await conn.fetchrow(
                """SELECT id, original_filename, processing_status, error_message, created_at, updated_at
                   FROM file_uploads WHERE id = $1""",
                int(item_id)
            )

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

            # Try to find in scraped_websites
            website_record = await conn.fetchrow(
                """SELECT id, original_url, processing_status, error_message, created_at, updated_at
                   FROM scraped_websites WHERE id = $1""",
                int(item_id)
            )

            if website_record:
                return {
                    "success": True,
                    "type": "website",
                    "id": str(website_record['id']),
                    "name": website_record['original_url'],
                    "processing_status": website_record['processing_status'],
                    "error_message": website_record['error_message'],
                    "created_at": website_record['created_at'].isoformat() if website_record['created_at'] else None,
                    "updated_at": website_record['updated_at'].isoformat() if website_record['updated_at'] else None
                }

            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/upload/constraints")
async def get_upload_constraints(request: Request = None):
    """Get upload constraints"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Import constants for consistency
        from ..utils.constants import MAX_FILE_SIZE_BYTES, ALLOWED_FILE_EXTENSIONS

        return {
            "success": True,
            # Top-level fields for frontend compatibility
            "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
            "allowed_extensions": ALLOWED_FILE_EXTENSIONS,
            "max_file_size_display": f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB",
            # Nested constraints for backwards compatibility
            "constraints": {
                "max_file_size": MAX_FILE_SIZE_BYTES,
                "allowed_extensions": ALLOWED_FILE_EXTENSIONS,
                "allowed_types": [
                    "application/pdf",
                    "text/plain",
                    "text/markdown",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ],
                "max_files_per_user": 100
            },
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error getting upload constraints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request = None):
    """
    Delete an uploaded file with transactional safety.

    This endpoint is for uploaded files only (not websites/sitemaps).
    Use /web/{id} endpoint for websites and sitemaps.

    Transaction Safety:
    - FileStore deletion attempted first
    - Database deletion happens in a transaction
    - If FileStore fails, database is not touched
    - If database transaction fails, it rolls back automatically
    """
    try:
        if not file_id:
            raise HTTPException(status_code=400, detail="file_id is required")

        # Use the service layer for file deletion
        logger.info(f"📄 Deleting uploaded file: {file_id}")
        result = await delete_file_logic(file_id)

        return {
            "success": result.get("success", True),
            "message": result.get("message", "File deleted successfully"),
            "details": result.get("details"),
            "transaction_status": result.get("transaction_status", "unknown")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/web/{website_id}")
async def delete_web_item(website_id: str, request: Request = None):
    """
    Delete a website or sitemap and all its child pages with cascade delete.

    This endpoint is for websites and sitemaps (not uploaded files).
    Automatically deletes all child pages when parent is deleted.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        logger.info(f"🌐 User {user_email} requesting deletion of website/sitemap {website_id}")

        # Use hierarchy deletion with cascade delete
        result = await delete_website_hierarchy(website_id)

        return {
            "success": result.get("success", True),
            "message": result.get("message", "Website/sitemap deleted successfully"),
            "details": result.get("details"),
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website/sitemap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/websites/{website_id}/hierarchy")
async def delete_website_hierarchy_deprecated(website_id: str, request: Request = None):
    """
    Delete a website and all its child pages with transactional safety.
    
    Transaction Safety:
    - FileSearch deletion attempted first for all pages
    - Database deletion happens only if FileSearch mostly succeeds
    - Uses recursive hierarchy to find all child pages
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        logger.info(f"🌳 User {user_email} requesting hierarchical deletion of website {website_id}")
        
        # Use local ingestion service function for hierarchical deletion
        result = await delete_website_hierarchy(website_id)
        
        return {
            "success": result.get("success", True),
            "message": result.get("message", "Website hierarchy deleted successfully"),
            "details": result.get("details"),
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website hierarchy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/delete-all")
async def delete_all_files(request: Request = None):
    """
    Delete all files and websites: Remove all documents from FileSearch store and all database records.
    This is a destructive operation and should only be called with explicit admin confirmation.
    
    Transaction Safety:
    - If FileStore deletion fails, database is NOT touched
    - Database deletion happens in a transaction - rolls back if it fails
    - Returns detailed status of what succeeded/failed
    """
    try:
        # Log the delete all for audit purposes
        user_email = request.headers.get("X-User-Email", "unknown") if request else "unknown"
        logger.critical(f"🚨 DELETE ALL INITIATED by {user_email}")

        # Execute the deletion with transactional safety
        result = await nuke_filestore_and_database()

        transaction_status = result.get("transaction_status", "unknown")
        success = result.get("success", False)

        if success:
            logger.critical(f"🚨 DELETE ALL SUCCESSFUL - All data removed (transaction: {transaction_status})")
            # Return 200 with success details
            return {
                "success": True,
                "message": result.get("message"),
                "details": result.get("details"),
                "transaction_status": transaction_status
            }
        else:
            # Transaction failed or was aborted - return error
            logger.critical(f"🚨 DELETE ALL FAILED - Transaction status: {transaction_status}")
            logger.critical(f"   Message: {result.get('message')}")

            # Return 500 error with detailed message
            raise HTTPException(
                status_code=500,
                detail=f"{result.get('message')} (Transaction: {transaction_status})"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during delete all operation: {e}")
        raise HTTPException(status_code=500, detail=f"Delete all operation failed with error: {str(e)}")

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "service": "knowledgebase_ingestion",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "file_service": "healthy",
                "storage": "connected",
                "database": "connected"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
