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
    delete_website_hierarchy
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
    """List all files"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        files = await file_service.get_all_files()
        
        return {
            "success": True,
            "files": files,
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
    Delete a file with transactional safety.

    Transaction Safety:
    - FileStore deletion attempted first
    - Database deletion happens in a transaction
    - If FileStore fails, database is not touched
    - If database transaction fails, it rolls back automatically
    """
    try:
        # Use the service layer for deletion (handles both Gemini and DB with transactions)
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
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/websites/{website_id}/hierarchy")
async def delete_website_hierarchy(website_id: str, request: Request = None):
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
