"""
Ingestion Service Layer for Knowledgebase Ingestion
Provides business logic for file ingestion operations
"""
import asyncio
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import UploadFile, HTTPException
from google.genai import types

from knowledgebase_ingestion.core.otel_logger import get_otel_logger
from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.schemas.models import BatchUploadItem, BatchDeleteItem, FileInfo
from knowledgebase_ingestion.utils.validation import (
    validate_file_extension, validate_file_size, validate_mime_type,
    sanitize_filename, detect_mime_type_from_extension
)
from knowledgebase_ingestion.utils.files import stream_to_temp_file, calculate_sha256
from knowledgebase_ingestion.service.file_service import FileService

logger = get_otel_logger("ingestion_service", "knowledgebase-ingestion")

# Singleton file service instance
_file_service = None

def get_file_service() -> FileService:
    """Get singleton FileService instance."""
    global _file_service
    if _file_service is None:
        _file_service = FileService()
    return _file_service


async def process_with_gemini(
    tmp_path: str,
    file_display_name: str,
    original_filename: str,
    mime_type: str,
    user_email: str = None,
    file_search_store_name: str = None
):
    """
    Process file with Gemini - uploads file to Gemini FileSearch.

    Args:
        tmp_path: Path to the temporary file
        file_display_name: Display name for the file
        original_filename: Original filename
        mime_type: MIME type of the file
        user_email: User email for metadata
        file_search_store_name: Optional FileSearch store name

    Returns:
        Tuple of (uploaded_file, final_state, gemini_processed_at)
    """
    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("Gemini client not available - returning placeholder response")
        # Return placeholder for when Gemini is not configured
        class PlaceholderFile:
            def __init__(self, name):
                self.name = name
                self.uri = None
        return PlaceholderFile(f"files/{original_filename}"), "ACTIVE", datetime.utcnow()

    # Detect proper MIME type
    final_mime_type = detect_mime_type_from_extension(original_filename, mime_type)

    # Create display name
    if file_display_name != original_filename:
        gemini_display_name = f"{file_display_name} | {original_filename}"
    else:
        gemini_display_name = original_filename

    logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")

    uploaded_file = None
    final_state = "PENDING"
    gemini_processed_at = None

    try:
        # If no store name provided, resolve it on-demand
        if not file_search_store_name:
            # Resolve FileSearch store on-demand (not relying on module-level variable which may not be shared across workers)
            from shared.file_search import get_file_search_store_by_display_name
            file_search_store_name = get_file_search_store_by_display_name(
                genai_client,
                display_name="knowledgebot-search-store"
            )

        if file_search_store_name:
            logger.info(f"📤 Uploading to FileSearch store: {file_search_store_name}")
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
                # FileSearch upload returns result in response.document_name, not operation.result
                if hasattr(operation, 'response') and hasattr(operation.response, 'document_name'):
                    document_name = operation.response.document_name
                    final_state = "ACTIVE"
                    gemini_processed_at = datetime.utcnow()

                    # Create a placeholder file object with the document name
                    class FileSearchDocument:
                        def __init__(self, name):
                            self.name = name
                            self.uri = None

                    uploaded_file = FileSearchDocument(document_name)
                    logger.info(f"✅ [GEMINI] Upload complete to FileSearch store. Document: {document_name}")
                elif hasattr(operation, 'result') and operation.result:
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
            logger.info("📤 Using general file upload (no FileSearch store configured)")
            uploaded_file = genai_client.files.upload(
                file=tmp_path,
                config=types.UploadFileConfig(
                    display_name=gemini_display_name,
                    mime_type=final_mime_type
                )
            )

            # Poll for processing completion
            final_state = uploaded_file.state.name if hasattr(uploaded_file.state, 'name') else str(uploaded_file.state)

            try:
                for i in range(15):  # Poll for up to 30 seconds
                    current_file = genai_client.files.get(name=uploaded_file.name)
                    final_state = current_file.state.name if hasattr(current_file.state, 'name') else str(current_file.state)
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

    except Exception as e:
        logger.error(f"❌ Error processing file with Gemini: {e}")
        raise


async def record_metadata(
    filename: str,
    mime_type: str,
    size: int,
    user_id: str,
    gemini_file_id: str = None,
    **kwargs
):
    """
    Record file metadata to database.

    Args:
        filename: Original filename
        mime_type: MIME type
        size: File size in bytes
        user_id: User ID or email
        gemini_file_id: Gemini file ID
        **kwargs: Additional metadata
    """
    try:
        file_service = get_file_service()

        # Create a placeholder uploaded_file object for compatibility
        class PlaceholderFile:
            def __init__(self, name):
                self.name = name
                self.uri = None

        uploaded_file = PlaceholderFile(gemini_file_id or f"files/{filename}")
        file_ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''

        result = await file_service.record_metadata(
            user_email=user_id,  # Note: user_id parameter actually contains email
            original_filename=filename,
            file_display_name=kwargs.get('display_name', filename),
            file_ext=file_ext,
            uploaded_file=uploaded_file,
            file_size=size,
            sha256_hash=kwargs.get('sha256_hash', ''),
            final_state=kwargs.get('state', 'ACTIVE'),
            gemini_processed_at=kwargs.get('processed_at', datetime.utcnow()),
            mime_type=mime_type,
            version=kwargs.get('version', 1)
        )

        logger.info(f"✅ Metadata recorded for {filename}")
        return {"success": True, "message": f"Metadata recorded for {filename}", "id": result}

    except Exception as e:
        logger.error(f"❌ Error recording metadata: {e}")
        raise


async def delete_existing_file_record(file_id: str):
    """Delete existing file record from database."""
    try:
        file_service = get_file_service()
        await file_service.delete_existing_file_record(file_id)
        logger.info(f"🗑️ Deleted file record: {file_id}")
        return {"success": True, "message": f"File record {file_id} deleted successfully"}
    except Exception as e:
        logger.error(f"❌ Error deleting file record: {e}", exc_info=True)
        raise


async def record_api_usage(**kwargs):
    """Record API usage metrics."""
    try:
        logger.info("📊 API usage recorded", extra=kwargs)
        return {"success": True, "message": "API usage recorded successfully"}
    except Exception as e:
        logger.error(f"❌ Error recording API usage: {e}", exc_info=True)
        raise


async def process_single_file_upload(
    file: UploadFile,
    display_name: Optional[str] = None,
    user_email: Optional[str] = None,
    replace_existing: bool = False
) -> BatchUploadItem:
    """
    Process a single file upload for batch operations.

    Args:
        file: The uploaded file
        display_name: Optional display name
        user_email: User email for tracking
        replace_existing: Whether to replace existing files with same name

    Returns:
        BatchUploadItem with upload result
    """
    file_service = get_file_service()
    start_time = time.perf_counter()
    original_filename = sanitize_filename(file.filename or "unknown_file")
    file_display_name = display_name or original_filename
    email = user_email or "admin"

    log_context = {"upload_file_name": original_filename, "user_email": email}
    tmp_path = None

    try:
        # Validate file extension
        ext_valid, ext_error = validate_file_extension(original_filename)
        if not ext_valid:
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="Validation failed",
                error=ext_error
            )

        # Validate MIME type
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

        # Calculate hash and detect MIME type
        sha256_hash = calculate_sha256(tmp_path)
        detected_mime_type = detect_mime_type_from_extension(original_filename, file.content_type)

        # Check for duplicates
        duplicate_check = await file_service.handle_duplicate_check(sha256_hash, original_filename, replace_existing)
        if not duplicate_check.get("allow", True):
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="Duplicate file",
                error=duplicate_check.get("detail", "File already exists")
            )

        replaced = duplicate_check.get("reason") == "replaced"

        # Process with Gemini
        uploaded_file, final_state, gemini_processed_at = await process_with_gemini(
            tmp_path, file_display_name, original_filename, detected_mime_type, user_email
        )

        if final_state != "ACTIVE":
            # Cleanup on failure
            genai_client = get_genai_client()
            if genai_client and uploaded_file:
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
        file_record_id = await file_service.record_metadata(
            user_email=email,
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
            db_record_id=str(file_record_id) if file_record_id else None,
            original_filename=original_filename
        )

        processing_time = time.perf_counter() - start_time
        logger.info(f"✅ Upload completed for {original_filename} in {processing_time:.2f}s", extra=log_context)

        return BatchUploadItem(
            filename=original_filename,
            success=True,
            file=file_info,
            message="Upload successful",
            replaced_existing=replaced
        )

    except Exception as e:
        logger.error(f"❌ Error in upload for {original_filename}: {e}", extra=log_context)
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
    file_service = get_file_service()

    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")

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
    if genai_client and gemini_file_name:
        try:
            genai_client.files.delete(name=gemini_file_name)
            deletion_results["gemini"]["success"] = True
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                deletion_results["gemini"]["error"] = "File not found (already deleted)"
            else:
                deletion_results["gemini"]["error"] = str(e)
    else:
        deletion_results["gemini"]["error"] = "Gemini client not available"

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
            filename=file_id,
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
