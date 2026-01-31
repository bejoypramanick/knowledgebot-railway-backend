"""
Ingestion Service Layer for Knowledgebase Ingestion
Provides business logic for file ingestion operations
"""
from typing import Dict

import logging

logger = logging.getLogger("ingestion_service")

async def process_with_gemini(tmp_path: str, file_display_name: str, original_filename: str, mime_type: str, user_email: str = None):
    """Process file with Gemini - placeholder implementation"""
    try:
        # This would need to be implemented based on actual Gemini processing logic
        # For now, return success response
        logger.info(f"Processing file with Gemini: {file_display_name}")
        return {
            "success": True,
            "message": f"File {file_display_name} processed successfully",
            "file_name": file_display_name
        }
    except Exception as e:
        logger.error(f"Error processing file with Gemini: {e}")
        raise

async def record_metadata(filename: str, mime_type: str, size: int, user_id: str, **kwargs):
    """Record file metadata - placeholder implementation"""
    try:
        # This would need to be implemented based on actual metadata storage logic
        # For now, return success response
        logger.info(f"Recording metadata for file: {filename}")
        return {
            "success": True,
            "message": f"Metadata recorded for {filename}"
        }
    except Exception as e:
        logger.error(f"Error recording metadata: {e}")
        raise

async def delete_existing_file_record(file_id: str):
    """Delete existing file record - placeholder implementation"""
    try:
        # This would need to be implemented based on actual file deletion logic
        # For now, return success response
        logger.info(f"Deleting file record: {file_id}")
        return {
            "success": True,
            "message": f"File record {file_id} deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting file record: {e}", exc_info=True)
        raise

async def record_api_usage(**kwargs):
    """Record API usage - placeholder implementation"""
    try:
        # This would need to be implemented based on actual usage tracking logic
        # For now, return success response
        logger.info("API usage recorded", **kwargs)
        return {
            "success": True,
            "message": "API usage recorded successfully"
        }
    except Exception as e:
        logger.error(f"Error recording API usage: {e}", exc_info=True)
        raise
    if file_display_name != original_filename:
        gemini_display_name = f"{file_display_name} | {original_filename}"
    else:
        gemini_display_name = original_filename
    
    logger.info(f" [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")
    logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")
    
    if file_search_store_name:
        # Upload directly to the specified FileSearch store
        logger.info(f"📂 Uploading to FileSearch store: {file_search_store_name}")
        operation = genai_client.file_search_stores.upload_to_file_search_store(
            file=tmp_path,
            file_search_store_name=file_search_store_name,
            config={
                'display_name': gemini_display_name,
                'custom_metadata': [
                    {'key': 'original_filename', 'string_value': original_filename},
                    {'key': 'user_email', 'string_value': user_email or 'admin'}
                ]
            }
        )
        
        # Wait for the upload operation to complete
        start_time = time.time()
        max_wait_time = 300  # 5 minutes
        
        while not operation.done:
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                logger.error(f"❌ Timeout waiting for file upload to complete")
                raise Exception("File upload timeout")
            
            await asyncio.sleep(5)
            operation = genai_client.operations.get(operation)
            
        if operation.done:
            if hasattr(operation, 'result') and operation.result:
                uploaded_file = operation.result
                final_state = "ACTIVE"
                gemini_processed_at = datetime.utcnow()
                logger.info(f"✅ [GEMINI] Upload complete to FileSearch store. File: {uploaded_file.name}")
            else:
                logger.error(f"❌ [GEMINI] Upload failed: {operation}")
                raise Exception("File upload failed")
        else:
            raise Exception("File upload incomplete")
    else:
        # Fallback to general file upload (old method)
        logger.warning("⚠️ No File Search store configured - using general file upload")
        uploaded_file = genai_client.files.upload(
            file=tmp_path,
            config=types.UploadFileConfig(
                display_name=gemini_display_name,
                mime_type=final_mime_type
            )
        )
        
        # Poll for processing completion (old method)
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
    email = user_email or "admin"
    
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
            tmp_path, file_display_name, original_filename, detected_mime_type, user_email
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
    
    file_service = FileService()
    gemini_file_name = file_id
    table_name = "gemini_only"
    original_filename = "Gemini-only file"
    
    if not file_id.startswith("files/"):
         # Look up in DB using service
         record = await file_service.find_file_record(file_id)
         
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
    if table_name != "gemini_only":
        try:
            await file_service.delete_file_record(file_id, table_name)
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
