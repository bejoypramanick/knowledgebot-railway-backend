# Append to existing content or rewrite?
# I will rewrite to include everything.

import logging
import asyncio
import os
import json
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from google.genai import types
from fastapi import UploadFile, HTTPException, status

from services.knowledgebase_ingestion.core.ai import get_genai_client
from services.knowledgebase_ingestion.core.database import (
    record_metadata, delete_existing_file_record, record_api_usage
)
from services.knowledgebase_ingestion.utils.validation import (
    detect_mime_type_from_extension, sanitize_filename, 
    validate_file_extension, validate_mime_type, validate_file_size
)
from services.knowledgebase_ingestion.utils.files import stream_to_temp_file, calculate_sha256
from services.knowledgebase_ingestion.schemas.models import FileInfo, BatchUploadItem, BatchDeleteItem
from shared.config import settings
from shared import db

logger = logging.getLogger(__name__)

async def process_with_gemini(tmp_path: str, file_display_name: str, original_filename: str, mime_type: str):
    """Upload to Gemini FileSearch and poll for processing completion."""
    genai_client = get_genai_client()
    if not genai_client:
        raise Exception("Gemini client not initialized")

    # Double-check MIME type is not generic (fallback safety)
    final_mime_type = detect_mime_type_from_extension(original_filename, mime_type)
    
    if final_mime_type != mime_type:
        logger.warning(f"⚠️ [GEMINI] MIME type correction: {mime_type} -> {final_mime_type}")
    
    # Format display_name to include original filename as metadata
    if file_display_name != original_filename:
        gemini_display_name = f"{file_display_name} | {original_filename}"
    else:
        gemini_display_name = original_filename
    
    logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")
    
    uploaded_file = genai_client.files.upload(
        file=tmp_path,
        config=types.UploadFileConfig(
            display_name=gemini_display_name,
            mime_type=final_mime_type
        )
    )
    
    logger.info(f"✅ [GEMINI] Upload complete. File ID: {uploaded_file.name}, State: {uploaded_file.state.name}")
    logger.info(f"🔗 [GEMINI] URI: {getattr(uploaded_file, 'uri', 'N/A')}")
    
    final_state = uploaded_file.state.name
    gemini_processed_at = None
    
    try:
        for i in range(15):  # Poll for up to 30 seconds
            current_file = genai_client.files.get(name=uploaded_file.name)
            final_state = current_file.state.name
            logger.info(f"🔄 [GEMINI] Polling state (Attempt {i+1}/15): {final_state}")
            
            if final_state == "ACTIVE":
                gemini_processed_at = datetime.utcnow()
                logger.info("⚡ [GEMINI] Processing complete - File is now ACTIVE")
                break
            elif final_state == "FAILED":
                logger.error(f"❌ [GEMINI] Processing FAILED for {uploaded_file.name}")
                break
                
            await asyncio.sleep(2)
    except Exception as e:
        logger.warning(f"⚠️ [GEMINI] Error during polling: {e}")
        
    return uploaded_file, final_state, gemini_processed_at

async def process_single_file_upload(
    file: UploadFile,
    display_name: Optional[str] = None,
    user_email: Optional[str] = None
) -> BatchUploadItem:
    """Process a single file upload for batch operations."""
    genai_client = get_genai_client()
    start_time = time.perf_counter()
    original_filename = sanitize_filename(file.filename or "unknown_file")
    file_display_name = display_name or original_filename
    email = user_email or settings.default_user_email
    
    log_context = {"upload_file_name": original_filename, "user_email": email}
    tmp_path = None
    
    try:
        # Validate file
        ext_valid, ext_error = validate_file_extension(original_filename)
        if not ext_valid:
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="Validation failed",
                error=ext_error
            )
        
        mime_valid, mime_error = validate_mime_type(file.content_type, original_filename)
        if not mime_valid:
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="Validation failed",
                error=mime_error
            )
        
        # Stream to temp file
        tmp_path, file_size = await stream_to_temp_file(file, original_filename)
        
        # Validate file size
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="Validation failed",
                error=size_error
            )
        
        sha256_hash = calculate_sha256(tmp_path)
        detected_mime_type = detect_mime_type_from_extension(original_filename, file.content_type)
        
        # Process with Gemini
        uploaded_file, final_state, gemini_processed_at = await process_with_gemini(
            tmp_path, file_display_name, original_filename, detected_mime_type
        )
        
        if final_state != "ACTIVE":
            # Cleanup on failure
            try:
                genai_client.files.delete(name=uploaded_file.name)
            except:
                pass
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="File processing failed",
                error=f"Final state: {final_state}"
            )
        
        # Store metadata
        file_record_id = await record_metadata(
            user_id=email,
            original_filename=original_filename,
            file_display_name=file_display_name,
            file_ext=original_filename.rsplit('.', 1)[-1] if '.' in original_filename else '',
            uploaded_file=uploaded_file,
            file_size=file_size,
            sha256_hash=sha256_hash,
            final_state=final_state,
            gemini_processed_at=gemini_processed_at,
            mime_type=detected_mime_type
        )
        
        file_info = FileInfo(
            name=uploaded_file.name,
            display_name=file_display_name,
            size_bytes=str(file_size),
            mime_type=detected_mime_type,
            create_time=gemini_processed_at.isoformat() if gemini_processed_at else datetime.utcnow().isoformat(),
            source="upload",
            state=final_state,
            sha256_hash=sha256_hash,
            db_record_id=str(file_record_id) if file_record_id else None
        )
        
        processing_time = time.perf_counter() - start_time
        logger.info(f"✅ Batch upload completed for {original_filename} in {processing_time:.2f}s", extra=log_context)
        
        return BatchUploadItem(
            filename=original_filename,
            success=True,
            file=file_info,
            message="Upload successful",
            replaced_existing=False
        )
        
    except Exception as e:
        logger.error(f"❌ Error in batch upload for {original_filename}: {e}", extra=log_context)
        return BatchUploadItem(
            filename=original_filename,
            success=False,
            message="Upload failed",
            error=str(e)
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass

async def delete_file_logic(file_id: str) -> Dict[str, Any]:
    """Delete a file from Gemini FileSearch and database."""
    genai_client = get_genai_client()
    if not genai_client:
        raise Exception("Gemini client not initialized")
        
    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")
    
    gemini_file_name = file_id
    table_name = "gemini_only"
    original_filename = "Gemini-only file"
    
    if not file_id.startswith("files/") and db.railway_db:
         # Look up in DB
         record = await db.railway_db.fetchrow(
             "SELECT gemini_file_name, original_filename, 'file_uploads' as table_name FROM file_uploads WHERE id = $1",
             file_id
         )
         if not record:
             record = await db.railway_db.fetchrow(
                 "SELECT gemini_file_name, original_url as original_filename, 'scraped_websites' as table_name FROM scraped_websites WHERE id = $1",
                 file_id
             )
         
         if record:
             gemini_file_name = record['gemini_file_name']
             original_filename = record.get('original_filename', 'Unknown')
             table_name = record['table_name']
         else:
             raise HTTPException(status_code=404, detail="File not found")

    deletion_results = {
        "gemini": {"success": False, "error": None},
        "postgres": {"success": False, "error": None}
    }
    
    # Delete from Gemini
    try:
        try:
             genai_client.files.delete(name=gemini_file_name)
             deletion_results["gemini"]["success"] = True
        except Exception as e:
             if "404" in str(e) or "not found" in str(e).lower():
                 deletion_results["gemini"]["error"] = "File not found (already deleted)"
             else:
                 deletion_results["gemini"]["error"] = str(e)
    except Exception:
        deletion_results["gemini"]["error"] = "Unknown error"

    # Delete from DB
    if db.railway_db and table_name != "gemini_only":
        try:
            query = f"DELETE FROM {table_name} WHERE id = $1"
            await db.railway_db.execute(query, file_id)
            deletion_results["postgres"]["success"] = True
        except Exception as e:
            deletion_results["postgres"]["error"] = str(e)
            
    # Determine success
    db_success = deletion_results["postgres"].get("success", False)
    gemini_success = deletion_results["gemini"].get("success", False)
    
    if db_success or gemini_success:
        return {
            "success": True, 
            "message": "File deletion processed",
            "details": deletion_results
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to delete file from both Gemini and DB")

async def process_single_file_delete(file_id: str) -> BatchDeleteItem:
    """Process a single file delete for batch operations."""
    try:
        result = await delete_file_logic(file_id)
        return BatchDeleteItem(
            file_id=file_id,
            filename=file_id, # Simplified
            success=result["success"],
            message=result["message"],
            details=result.get("details")
        )
    except Exception as e:
        return BatchDeleteItem(
            file_id=file_id,
            filename=file_id,
            success=False,
            message=str(e),
            error=str(e)
        )
