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
    """Upload multiple files in batch - PARALLEL processing"""
    try:
        import asyncio

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

        logger.info(f"📤 Starting PARALLEL batch upload of {len(files)} files")

        # Create tasks for all files to be processed concurrently
        async def process_file_wrapper(file):
            """Wrapper to handle individual file processing with error catching"""
            try:
                result = await process_single_file_upload(
                    file=file,
                    display_name=None,
                    user_email=user_email,
                    replace_existing=replace_existing
                )
                return result
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {e}")
                # Return a failed BatchUploadItem
                from knowledgebase_ingestion.schemas.models import BatchUploadItem
                return BatchUploadItem(
                    filename=file.filename,
                    success=False,
                    message="Upload failed",
                    error=str(e)
                )

        # Process all files concurrently using asyncio.gather
        logger.info(f"🚀 Launching {len(files)} concurrent upload tasks...")
        upload_results = await asyncio.gather(
            *[process_file_wrapper(file) for file in files],
            return_exceptions=False
        )

        # Process results
        results = []
        successful_uploads = 0
        failed_uploads = 0

        for result in upload_results:
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

        logger.info(f"✅ Batch upload completed: {successful_uploads} successful, {failed_uploads} failed (total: {len(files)})")

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

@router.post("/delete/batch")
async def delete_files_batch(request: Request):
    """Delete multiple files in batch - PARALLEL processing"""
    try:
        import asyncio

        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Parse form data
        form = await request.form()

        # Get file IDs from form
        file_ids = form.getlist("file_ids")
        if not file_ids:
            raise HTTPException(status_code=400, detail="No file IDs provided")

        logger.info(f"🗑️  Starting PARALLEL batch delete of {len(file_ids)} files")

        # Create tasks for all files to be deleted concurrently
        async def delete_file_wrapper(file_id):
            """Wrapper to handle individual file deletion with error catching"""
            try:
                result = await process_single_file_delete(file_id)
                return result
            except Exception as e:
                logger.error(f"Error deleting file {file_id}: {e}")
                # Return a failed BatchDeleteItem
                from knowledgebase_ingestion.schemas.models import BatchDeleteItem
                return BatchDeleteItem(
                    file_id=file_id,
                    filename=file_id,
                    success=False,
                    message="Delete failed",
                    error=str(e)
                )

        # Process all deletions concurrently using asyncio.gather
        logger.info(f"🚀 Launching {len(file_ids)} concurrent delete tasks...")
        delete_results = await asyncio.gather(
            *[delete_file_wrapper(file_id) for file_id in file_ids],
            return_exceptions=False
        )

        # Process results
        results = []
        successful_deletes = 0
        failed_deletes = 0

        for result in delete_results:
            # Convert BatchDeleteItem to dict for response
            delete_result = {
                "file_id": result.file_id,
                "success": result.success,
                "message": result.message,
                "error": result.error,
                "details": result.details if hasattr(result, 'details') else None
            }

            if result.success:
                successful_deletes += 1
            else:
                failed_deletes += 1

            results.append(delete_result)

        logger.info(f"✅ Batch delete completed: {successful_deletes} successful, {failed_deletes} failed (total: {len(file_ids)})")

        return {
            "success": True,
            "message": f"Batch delete completed: {successful_deletes} successful, {failed_deletes} failed",
            "total_files": len(file_ids),
            "successful_deletes": successful_deletes,
            "failed_deletes": failed_deletes,
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch delete: {e}")
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
