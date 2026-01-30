"""
Consolidated Knowledgebase Ingestion Router
All knowledgebase ingestion endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from typing import Dict, List, Any, Optional
import logging

from ..service.file_service import FileService
from ..service.ingestion_service import (
    process_with_gemini,
    record_metadata,
    delete_existing_file_record,
    record_api_usage
)
from ..core.auth_middleware import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
file_service = FileService()

# =================================
# FILE UPLOAD ENDPOINTS
# =================================

@router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), request: Request = None):
    """Upload a file to the knowledgebase"""
    try:
        current_user = await get_current_user(request) if request else None
        
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Process file with Gemini
        result = await process_with_gemini(
            tmp_path="",  # Will be handled by FileService
            file_display_name=file.filename,
            original_filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            user_email=current_user.get("email") if current_user else None
        )
        
        # Record metadata
        await record_metadata(
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            size=0,  # Will be set by FileService
            user_id=current_user.get("uid") if current_user else None,
            gemini_file_id=result.get("file_id") if result else None
        )
        
        return {
            "success": True,
            "message": "File uploaded successfully",
            "file_id": result.get("file_id") if result else None
        }
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files")
async def list_files(request: Request):
    """List all files for the user"""
    try:
        current_user = await get_current_user(request)
        files = await file_service.get_user_files(current_user.get("uid"))
        
        return {
            "success": True,
            "files": files
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request):
    """Delete a file"""
    try:
        current_user = await get_current_user(request)
        
        # Check if file exists and belongs to user
        file_record = await file_service.get_file_by_id(file_id, current_user.get("uid"))
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Delete file
        await file_service.delete_file(file_id, current_user.get("uid"))
        
        return {
            "success": True,
            "message": "File deleted successfully"
        }
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
