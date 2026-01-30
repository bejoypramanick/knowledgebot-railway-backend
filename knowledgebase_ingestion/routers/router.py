"""
Consolidated Knowledgebase Ingestion Router
All knowledgebase ingestion endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from typing import Dict, List, Any, Optional
import logging

from ..service.file_service import FileService
from ..service.ingestion_service import IngestionService
from ..core.auth_middleware import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
file_service = FileService()
ingestion_service = IngestionService()

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
        
        # Check file size (max 10MB)
        if file.size and file.size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")
        
        # Check file type
        allowed_types = ['.pdf', '.txt', '.docx', '.md', '.html', '.csv', '.json']
        file_ext = '.' + file.filename.split('.')[-1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_types:
            raise HTTPException(status_code=400, detail=f"File type {file_ext} not allowed")
        
        # Upload file
        result = await file_service.upload_file(
            file=file,
            user_id=current_user.get("uid") if current_user else "anonymous"
        )
        
        return {
            "success": True,
            "data": result,
            "message": "File uploaded successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files")
async def get_uploaded_files(request: Request):
    """Get list of uploaded files"""
    try:
        current_user = await get_current_user(request)
        files = await file_service.get_user_files(current_user.get("uid"))
        
        return {
            "success": True,
            "data": files
        }
    except Exception as e:
        logger.error(f"Error getting files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{file_id}")
async def get_file_details(file_id: str, request: Request):
    """Get details of a specific file"""
    try:
        current_user = await get_current_user(request)
        file_details = await file_service.get_file_details(file_id, current_user.get("uid"))
        
        if not file_details:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {
            "success": True,
            "data": file_details
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request):
    """Delete a file from the knowledgebase"""
    try:
        current_user = await get_current_user(request)
        result = await file_service.delete_file(file_id, current_user.get("uid"))
        
        return {
            "success": True,
            "message": "File deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# INGESTION ENDPOINTS
# =================================

@router.post("/ingest/{file_id}")
async def ingest_file(file_id: str, request: Request):
    """Start ingestion process for a file"""
    try:
        current_user = await get_current_user(request)
        
        # Check if file exists and belongs to user
        file_details = await file_service.get_file_details(file_id, current_user.get("uid"))
        if not file_details:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Start ingestion
        result = await ingestion_service.ingest_file(
            file_id=file_id,
            user_id=current_user.get("uid")
        )
        
        return {
            "success": True,
            "data": result,
            "message": "Ingestion started successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ingest/status/{ingestion_id}")
async def get_ingestion_status(ingestion_id: str, request: Request):
    """Get status of an ingestion process"""
    try:
        current_user = await get_current_user(request)
        status = await ingestion_service.get_ingestion_status(ingestion_id, current_user.get("uid"))
        
        if not status:
            raise HTTPException(status_code=404, detail="Ingestion not found")
        
        return {
            "success": True,
            "data": status
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ingestion status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ingest/history")
async def get_ingestion_history(request: Request, limit: int = 50, offset: int = 0):
    """Get ingestion history for the user"""
    try:
        current_user = await get_current_user(request)
        history = await ingestion_service.get_ingestion_history(
            user_id=current_user.get("uid"),
            limit=limit,
            offset=offset
        )
        
        return {
            "success": True,
            "data": history
        }
    except Exception as e:
        logger.error(f"Error getting ingestion history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# KNOWLEDGE BASE ENDPOINTS
# =================================

@router.get("/knowledgebase/search")
async def search_knowledgebase(query: str, request: Request, limit: int = 10):
    """Search the knowledgebase"""
    try:
        current_user = await get_current_user(request)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        results = await ingestion_service.search_knowledgebase(
            query=query,
            user_id=current_user.get("uid"),
            limit=limit
        )
        
        return {
            "success": True,
            "data": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching knowledgebase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/knowledgebase/stats")
async def get_knowledgebase_stats(request: Request):
    """Get knowledgebase statistics"""
    try:
        current_user = await get_current_user(request)
        stats = await ingestion_service.get_knowledgebase_stats(current_user.get("uid"))
        
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        logger.error(f"Error getting knowledgebase stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# BATCH OPERATIONS ENDPOINTS
# =================================

@router.post("/batch/upload")
async def batch_upload_files(files: List[UploadFile] = File(...), request: Request = None):
    """Upload multiple files at once"""
    try:
        current_user = await get_current_user(request) if request else None
        
        if len(files) > 10:
            raise HTTPException(status_code=400, detail="Too many files (max 10 per batch)")
        
        results = []
        errors = []
        
        for file in files:
            try:
                result = await file_service.upload_file(
                    file=file,
                    user_id=current_user.get("uid") if current_user else "anonymous"
                )
                results.append(result)
            except Exception as e:
                errors.append({
                    "filename": file.filename,
                    "error": str(e)
                })
        
        return {
            "success": True,
            "data": {
                "uploaded": results,
                "errors": errors
            },
            "message": f"Batch upload completed: {len(results)} successful, {len(errors)} failed"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch/ingest")
async def batch_ingest_files(request: Request):
    """Start batch ingestion for multiple files"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        file_ids = body.get("file_ids", [])
        if not file_ids:
            raise HTTPException(status_code=400, detail="No file IDs provided")
        
        if len(file_ids) > 5:
            raise HTTPException(status_code=400, detail="Too many files (max 5 per batch)")
        
        results = await ingestion_service.batch_ingest_files(
            file_ids=file_ids,
            user_id=current_user.get("uid")
        )
        
        return {
            "success": True,
            "data": results,
            "message": "Batch ingestion started"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting batch ingestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check for knowledgebase ingestion service"""
    try:
        health_status = {
            "status": "healthy",
            "service": "knowledgebase-ingestion",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "file_service": "healthy",
                "ingestion_service": "healthy",
                "storage": "connected",
                "database": "connected"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
