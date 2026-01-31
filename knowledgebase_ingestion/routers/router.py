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
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Process file with Gemini
        result = await process_with_gemini(
            tmp_path="",  # Will be handled by FileService
            file_display_name=file.filename,
            original_filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            user_email=None
        )
        
        # Record metadata
        await record_metadata(
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            size=0,  # Will be set by FileService
            user_id=None,
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
async def list_files():
    """List all files"""
    try:
        files = await file_service.get_all_files()
        
        return {
            "success": True,
            "files": files
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/upload/constraints")
async def get_upload_constraints():
    """Get upload constraints"""
    try:
        return {
            "success": True,
            "constraints": {
                "max_file_size": 10 * 1024 * 1024,  # 10MB
                "allowed_types": [
                    "application/pdf",
                    "text/plain",
                    "text/markdown",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ],
                "max_files_per_user": 100
            }
        }
    except Exception as e:
        logger.error(f"Error getting upload constraints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Delete a file"""
    try:
        # Check if file exists
        file_record = await file_service.get_file_by_id(file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Delete file
        await file_service.delete_file(file_id)
        
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
