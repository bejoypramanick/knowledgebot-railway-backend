import logging
import asyncio
import time
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Query, Request, status

from ..schemas.models import (
    UploadResponse, FileInfo, BatchUploadResponse, BatchDeleteResponse, BatchUploadItem, BatchDeleteItem
)
from ..servcie.ingestion import (
    process_single_file_upload, delete_file_logic, process_single_file_delete
)
from ..servcie.service_factory import ServiceFactory
from ..utils.files import stream_to_temp_file, calculate_sha256
from ..utils.validation import (
    sanitize_filename, validate_file_extension, validate_mime_type, validate_file_size, detect_mime_type_from_extension
)
from ..utils.constants import (
    MAX_FILE_SIZE_BYTES, ALLOWED_FILE_EXTENSIONS, ALLOWED_MIME_TYPES
)
from ..core.ai import get_genai_client, genai_client
from shared.config import settings
from shared import db
from shared.utils import log_endpoint_request
import os

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/files/status")
async def get_service_status():
    """Get service status."""
    return {
        "service": "knowledgebase_ingestion",
        "status": "healthy",
        "gemini_configured": get_genai_client() is not None,
        "database_configured": db.railway_db is not None,
        "version": "1.0.0"
    }

@router.get("/upload/constraints")
async def get_upload_constraints():
    """Get file upload constraints."""
    return {
        "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
        "max_file_size_mb": 5,
        "allowed_extensions": sorted(ALLOWED_FILE_EXTENSIONS),
        "allowed_mime_types": sorted(ALLOWED_MIME_TYPES)
    }

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
    user_email: Optional[str] = Header(None, alias="X-User-Email"),
    replace_existing: bool = Form(False)
):
    """Modularized Document Ingestion Pipeline."""
    start_time = time.perf_counter()
    replaced_existing = False
    
    if not get_genai_client():
        raise HTTPException(status_code=503, detail="Gemini client not configured")
        
    original_filename = sanitize_filename(file.filename or "unknown_file")
    email = user_email or "admin"
    
    # 1. Validation
    valid, msg = validate_file_extension(original_filename)
    if not valid: raise HTTPException(400, msg)
    
    valid, msg = validate_mime_type(file.content_type, original_filename)
    if not valid: raise HTTPException(400, msg)
    
    # 2. Check duplicates (requires streaming first to get hash? No, original main.py streamed first)
    # Stream to temp
    tmp_path, file_size = await stream_to_temp_file(file, original_filename)
    
    try:
        valid, msg = validate_file_size(file_size)
        if not valid: raise HTTPException(400, msg)
        
        sha256_hash = calculate_sha256(tmp_path)
        
        # Check duplicates using service
        file_service = FileService()
        duplicate_result = await file_service.handle_duplicate_check(sha256_hash, original_filename, replace_existing)
        
        if not duplicate_result["allow"]:
            if duplicate_result["reason"] == "file_exists":
                raise HTTPException(409, detail=duplicate_result["detail"])
            elif duplicate_result["reason"] == "error":
                raise HTTPException(500, detail="Error checking duplicate file")
        
        if duplicate_result["reason"] == "replaced":
            replaced_existing = True
        
        # We need to re-open the file OR re-use process_with_gemini logic.
        # But process_single_file_upload handles streaming internally.
        # We already streamed it here.
        # Let's import process_with_gemini from services.ingestion_service
        from ..servcie.ingestion_service import process_with_gemini, record_metadata
        
        detected_mime = detect_mime_type_from_extension(original_filename, file.content_type)
        uploaded_file, final_state, gemini_processed_at = await process_with_gemini(
            tmp_path, display_name or original_filename, original_filename, detected_mime, email
        )
        
        # Record metadata
        user_id = await file_service.get_or_create_user(email)
        db_id = await file_service.record_metadata(
            user_id, original_filename, display_name or original_filename,
            os.path.splitext(original_filename)[1], uploaded_file, file_size, sha256_hash,
            final_state, gemini_processed_at, detected_mime
        )
        
        # Cleanup
        if os.path.exists(tmp_path): os.unlink(tmp_path)
        
        return UploadResponse(
            success=True,
            file=FileInfo(
                name=uploaded_file.name,
                display_name=uploaded_file.display_name,
                mime_type=uploaded_file.mime_type,
                size_bytes=str(file_size),
                sha256_hash=sha256_hash,
                state=final_state,
                db_record_id=str(db_id),
                source='upload',
                original_filename=original_filename
            ),
            message="File uploaded successfully",
            replaced_existing=replaced_existing
        )
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        if os.path.exists(tmp_path): os.unlink(tmp_path)
        raise HTTPException(500, detail=str(e))

@router.post("/upload/batch", response_model=BatchUploadResponse)
async def upload_files_batch(
    files: List[UploadFile] = File(...)
):
    """Batch upload files."""
    results = []
    successful = 0
    failed = 0
    
    for file in files:
        res = await process_single_file_upload(file)
        results.append(res)
        if res.success: successful += 1
        else: failed += 1
        
    return BatchUploadResponse(
        success=successful > 0,
        total_files=len(files),
        successful_uploads=successful,
        failed_uploads=failed,
        results=results,
        message=f"Batch upload: {successful} success, {failed} failed"
    )

@router.delete("/files/{file_id}")
async def delete_file_endpoint(file_id: str):
    """Delete a file."""
    try:
        result = await delete_file_logic(file_id)
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@router.post("/delete/batch", response_model=BatchDeleteResponse)
async def delete_batch_endpoint(
    file_ids: List[str] = Form(...)
):
    """Batch delete files."""
    tasks = [process_single_file_delete(fid) for fid in file_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    processed = []
    success = 0
    failed = 0
    for r in results:
        if isinstance(r, BatchDeleteItem):
            processed.append(r)
            if r.success: success += 1
            else: failed += 1
        else:
            failed += 1
            
    return BatchDeleteResponse(
        success=success > 0,
        total_files=len(file_ids),
        successful_deletes=success,
        failed_deletes=failed,
        results=processed,
        message=f"Batch delete: {success} success, {failed} failed"
    )

@router.get("/files")
async def list_files_endpoint(
    source: Optional[str] = Query(None)
):
    """List files."""
    if not db.railway_db:
        return {"files": [], "count": 0}
        
    query = """
    SELECT id, original_filename, display_name, file_extension, mime_type, size_bytes, sha256_hash, gemini_file_name, gemini_state, created_at, 'upload' as source, COALESCE(version, 1) as version
    FROM file_uploads
    """
    if source == 'scrape':
        query = """
        SELECT id, original_url as original_filename, title as display_name, 'url' as file_extension, mime_type, size_bytes, '0' as sha256_hash, gemini_file_name, gemini_state, created_at, 'scrape' as source, COALESCE(version, 1) as version
        FROM scraped_websites
        """
    elif source is None:
        query = """
        SELECT id, original_filename, display_name, file_extension, mime_type, size_bytes, sha256_hash, gemini_file_name, gemini_state, created_at, 'upload' as source, COALESCE(version, 1) as version FROM file_uploads
        UNION ALL
        SELECT id, original_url as original_filename, title as display_name, 'url' as file_extension, mime_type, size_bytes, '0' as sha256_hash, gemini_file_name, gemini_state, created_at, 'scrape' as source, COALESCE(version, 1) as version FROM scraped_websites
        """
        
    rows = await db.railway_db.fetch(query + " ORDER BY created_at DESC")
    files = []
    for r in rows:
        files.append(FileInfo(
            name=r['gemini_file_name'],
            display_name=r['display_name'],
            mime_type=r['mime_type'] or '',
            size_bytes=str(r['size_bytes'] or 0),
            sha256_hash=r['sha256_hash'],
            state=r['gemini_state'],
            db_record_id=str(r['id']),
            source=r['source'],
            original_filename=r['original_filename'],
            create_time=r['created_at'].isoformat() if r['created_at'] else None
        ))
        
    return {"files": files, "count": len(files)}
