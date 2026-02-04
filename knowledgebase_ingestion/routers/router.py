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
    delete_file_logic
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

@router.delete("/files/{file_id}")
async def delete_file_by_id(file_id: str, request: Request = None):
    """Delete a specific file by ID"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        result = await file_service.delete_file(file_id)
        
        return {
            "success": True,
            "message": "File deleted successfully",
            "result": result,
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{file_id}")
async def get_file_by_id(file_id: str, request: Request = None):
    """Get a specific file by ID"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        file_record = await file_service.get_file_by_id(file_id)
        
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {
            "success": True,
            "file": file_record,
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file {file_id}: {e}")
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
    """Delete a file"""
    try:
        # Use the service layer for deletion (handles both Gemini and DB)
        result = await delete_file_logic(file_id)

        return {
            "success": result.get("success", True),
            "message": result.get("message", "File deleted successfully"),
            "details": result.get("details")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
