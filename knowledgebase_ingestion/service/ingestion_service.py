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

from shared.otel_logger import get_otel_logger
from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.core.config import settings
from knowledgebase_ingestion.schemas.models import BatchUploadItem, BatchDeleteItem, FileInfo
from knowledgebase_ingestion.utils.validation import (
    validate_file_extension, validate_file_size, validate_mime_type,
    sanitize_filename, detect_mime_type_from_extension
)
from knowledgebase_ingestion.utils.files import stream_to_temp_file, calculate_sha256
from knowledgebase_ingestion.service.file_service import FileService
from knowledgebase_ingestion.service.docling_integration import (
    process_with_docling,
    should_use_docling_for_file,
    create_markdown_temp_file
)

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
        Tuple of (uploaded_file, final_state, gemini_processed_at, file_search_metadata)
    """
    genai_client = get_genai_client()
    file_search_metadata = {}  # Track FileSearch store and document info

    if not genai_client:
        logger.warning("Gemini client not available - returning placeholder response")
        # Return placeholder for when Gemini is not configured
        class PlaceholderFile:
            def __init__(self, name):
                self.name = name
                self.uri = None
        return PlaceholderFile(f"files/{original_filename}"), "ACTIVE", datetime.utcnow(), file_search_metadata

    # Detect proper MIME type - use magic bytes from file path
    final_mime_type = detect_mime_type_from_extension(original_filename, mime_type, tmp_path)

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

            if not operation:
                logger.error("❌ [GEMINI] Failed to create upload operation")
                raise Exception("Gemini operation creation failed")

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

                    # Store FileSearch metadata for deletion later
                    file_search_metadata = {
                        'type': 'file_search',
                        'file_search_store_name': file_search_store_name,
                        'document_name': document_name,
                        'uploaded_at': gemini_processed_at.isoformat()
                    }

                    # Create a placeholder file object with the document name
                    class FileSearchDocument:
                        def __init__(self, name):
                            self.name = name
                            self.uri = None

                    uploaded_file = FileSearchDocument(document_name)
                    logger.info(f"✅ [GEMINI] Upload complete to FileSearch store. Document: {document_name}")
                    logger.info(f"📝 [METADATA] Stored FileSearch info: store={file_search_store_name}, document={document_name}")
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

            # Guard: ensure file was actually uploaded
            if not uploaded_file:
                logger.error("❌ [GEMINI] uploaded_file is None after upload call")
                raise Exception("Gemini upload failed - no file object returned")

            # Poll for processing completion
            final_state = "PENDING"
            if hasattr(uploaded_file, 'state'):
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

        return uploaded_file, final_state, gemini_processed_at, file_search_metadata

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

        # Calculate hash and detect MIME type robustly using magic bytes
        sha256_hash = calculate_sha256(tmp_path)
        detected_mime_type = detect_mime_type_from_extension(original_filename, file.content_type, tmp_path)
        
        logger.info(f"🔍 [ROUTING] Detected MIME: {detected_mime_type} for {original_filename}")

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

        # ---------------------------------------------------------
        # STRICT INGESTION ROUTING
        # ---------------------------------------------------------
        markdown_tmp_path = None
        docling_metadata = {}
        processed_successfully = False

        # 1. Route HTML files to HTML-specific pipeline
        if detected_mime_type == 'text/html' or original_filename.lower().endswith(('.html', '.htm')):
            logger.info(f"🌐 [ROUTING] Routing {original_filename} to HTML-specific pipeline")
            try:
                from shared.html_processor import extract_content_from_html
                markdown_content, html_metadata = extract_content_from_html(tmp_path)
                
                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    # Switch to markdown artifact
                    original_tmp_path = tmp_path
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    processed_successfully = True
                    logger.info(f"✅ [HTML] Extracted {len(markdown_content)} characters from HTML")
                else:
                    error_msg = html_metadata.get("error", "HTML extraction failed")
                    logger.error(f"❌ [HTML] Extraction failed for {original_filename}: {error_msg}")
                    # HARD FAILURE: Do not return 200, stop processing
                    if tmp_path and os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    return BatchUploadItem(
                        filename=original_filename,
                        success=False,
                        message="HTML extraction failed",
                        error=error_msg
                    )
            except Exception as e:
                logger.error(f"❌ [HTML] Unexpected error processing HTML: {e}")
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return BatchUploadItem(
                    filename=original_filename,
                    success=False,
                    message="HTML processing error",
                    error=str(e)
                )

        # 2. Route PDFs and other Docling-supported files
        elif await should_use_docling_for_file(original_filename, detected_mime_type, file_size):
            logger.info(f"📄 [ROUTING] Routing {original_filename} to Docling (PDF/DOCX) pipeline")
            # Strict check: Never send HTML to Docling
            if detected_mime_type == 'text/html' or original_filename.lower().endswith(('.html', '.htm')):
                logger.error(f"🚫 [ROUTING] Refusing to send HTML to Docling for {original_filename}")
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return BatchUploadItem(
                    filename=original_filename,
                    success=False,
                    message="Routing error",
                    error="HTML files must use HTML pipeline, not Docling"
                )

            try:
                markdown_content, docling_metadata = await process_with_docling(
                    tmp_path,
                    original_filename,
                    detected_mime_type
                )

                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    # Switch to markdown artifact
                    original_tmp_path = tmp_path
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    processed_successfully = True
                    logger.info(f"✅ [DOCLING] Converted {original_filename} to markdown")
                else:
                    error_msg = docling_metadata.get("error", "Docling processing failed")
                    logger.error(f"❌ [DOCLING] Processing failed for {original_filename}: {error_msg}")
                    
                    # HARD FAILURE (no fallback to raw if it's a PDF/DOCX that failed)
                    if tmp_path and os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    return BatchUploadItem(
                        filename=original_filename,
                        success=False,
                        message="Document conversion failed",
                        error=error_msg
                    )
            except Exception as e:
                logger.error(f"❌ [DOCLING] Unexpected error in Docling pipeline: {e}")
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return BatchUploadItem(
                    filename=original_filename,
                    success=False,
                    message="Docling processing error",
                    error=str(e)
                )
        else:
            # For types that skip docling (txt, md, etc.), we mark as processed successfully
            logger.info(f"📝 [ROUTING] Skipping special processing for {detected_mime_type}")
            processed_successfully = True

        # ---------------------------------------------------------
        # GEMINI UPLOAD GUARD
        # ---------------------------------------------------------
        # We only reach here if processed_successfully is True or it was a skip-docling type
        logger.info(f"🚀 [GEMINI] Initiating upload for {original_filename}")
        uploaded_file, final_state, gemini_processed_at, file_search_metadata = await process_with_gemini(
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
            if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                os.unlink(markdown_tmp_path)

            return BatchUploadItem(
                filename=original_filename,
                success=False,
                message="File processing failed",
                error=f"Final state: {final_state}"
            )

        # Store metadata in database (including FileSearch metadata for deletion)
        try:
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
                mime_type=detected_mime_type,
                file_search_metadata=file_search_metadata
            )
        except Exception as db_error:
            logger.error(f"❌ [DB ERROR] Failed to record metadata in database for {original_filename}: {db_error}")
            logger.error(f"⚠️ File is in Gemini (ID: {uploaded_file.name}) but NOT in database!")
            raise  # Re-raise to prevent marking upload as successful

        if not file_record_id:
            logger.error(f"❌ [DB ERROR] Database returned no ID for {original_filename}")
            logger.error(f"⚠️ File is in Gemini (ID: {uploaded_file.name}) but NOT properly recorded in database!")
            raise Exception("Database metadata recording failed - file orphaned in Gemini")

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
        logger.info(f"✅ [SUCCESS] Upload completed for {original_filename}")
        logger.info(f"   📁 Gemini File ID: {uploaded_file.name}")
        logger.info(f"   🗄️  Database ID: {file_record_id}")
        logger.info(f"   ⏱️  Time: {processing_time:.2f}s")
        logger.info(f"   📊 Size: {file_size} bytes")
        logger.info(f"   🔐 Hash: {sha256_hash}")

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
        # Cleanup temporary files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
        if markdown_tmp_path and os.path.exists(markdown_tmp_path):
            try:
                os.unlink(markdown_tmp_path)
            except:
                pass


async def query_gemini_file_existence(
    gemini_file_name: str,
    file_search_metadata: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Query if file exists in Gemini stores before deletion.

    Returns:
        {
            "raw_file_exists": bool,
            "file_search_exists": bool,
            "store_name": str or None,
            "document_name": str or None
        }
    """
    import json
    genai_client = get_genai_client()
    result = {
        "raw_file_exists": False,
        "file_search_exists": False,
        "store_name": None,
        "document_name": None
    }

    # Check raw file existence
    if gemini_file_name and not gemini_file_name.startswith("documents/"):
        try:
            genai_client.files.get(name=gemini_file_name)
            result["raw_file_exists"] = True
            logger.info(f"🔍 [PRE-DELETE QUERY] Raw file exists: {gemini_file_name}")
        except Exception:
            logger.info(f"🔍 [PRE-DELETE QUERY] Raw file not found: {gemini_file_name}")

    # Check FileSearch document existence
    if file_search_metadata:
        try:
            metadata = json.loads(file_search_metadata) if isinstance(file_search_metadata, str) else file_search_metadata
            if metadata.get('type') == 'file_search':
                store_name = metadata.get('file_search_store_name')
                document_name = metadata.get('document_name')
                result["store_name"] = store_name
                result["document_name"] = document_name

                if store_name and document_name:
                    try:
                        # Attempt to get document info (verifies existence)
                        genai_client.file_search_stores.get_document(
                            file_search_store_name=store_name,
                            document_name=document_name
                        )
                        result["file_search_exists"] = True
                        logger.info(f"🔍 [PRE-DELETE QUERY] FileSearch document exists: {document_name} in {store_name}")
                    except Exception:
                        logger.info(f"🔍 [PRE-DELETE QUERY] FileSearch document not found: {document_name}")
        except Exception as e:
            logger.warning(f"⚠️ [PRE-DELETE QUERY] Error parsing metadata: {e}")

    return result


async def delete_file_logic(file_id: str) -> Dict[str, Any]:
    """Delete a file from Gemini FileSearch and database with proper metadata handling."""
    genai_client = get_genai_client()
    file_service = get_file_service()

    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")

    gemini_file_name = file_id
    table_name = "gemini_only"
    original_filename = "Gemini-only file"
    file_search_metadata = None

    if not file_id.startswith("files/"):
        # Look up in DB using service - need to get full record with metadata
        try:
            from shared.db import get_db_connection

            # Convert file_id to integer if it's a numeric string
            try:
                numeric_id = int(file_id)
            except ValueError:
                numeric_id = file_id

            async with get_db_connection() as conn:
                # Try file_uploads table first
                record = await conn.fetchrow(
                    "SELECT gemini_file_name, original_filename, metadata FROM file_uploads WHERE id = $1",
                    numeric_id
                )
                if record:
                    gemini_file_name = record['gemini_file_name']
                    original_filename = record.get('original_filename', 'Unknown')
                    table_name = 'file_uploads'
                    file_search_metadata = record.get('metadata')
                else:
                    # Try scraped_websites table
                    record = await conn.fetchrow(
                        "SELECT gemini_file_name, original_url, metadata FROM scraped_websites WHERE id = $1",
                        numeric_id
                    )
                    if record:
                        gemini_file_name = record['gemini_file_name']
                        original_filename = record.get('original_url', 'Unknown')
                        table_name = 'scraped_websites'
                        file_search_metadata = record.get('metadata')
                    else:
                        logger.error(f"❌ [DELETE] File not found in database: {file_id}")
                        raise HTTPException(status_code=404, detail="File not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ [DELETE] Error looking up file record: {e}")
            raise HTTPException(status_code=500, detail=f"Error looking up file: {e}")

    deletion_results = {
        "gemini": {"success": False, "error": None},
        "file_search": {"success": False, "error": None},
        "postgres": {"success": False, "error": None}
    }

    logger.info(f"📋 File Details:")
    logger.info(f"   ID: {file_id}")
    logger.info(f"   Name: {original_filename}")
    logger.info(f"   Gemini File ID: {gemini_file_name}")
    logger.info(f"   Table: {table_name}")
    if file_search_metadata:
        logger.info(f"   FileSearch Metadata: {file_search_metadata}")

    # PRE-DELETION: Query if file exists in Gemini stores
    logger.info(f"📋 [PRE-DELETE] Querying file existence in Gemini stores...")
    existence_check = await query_gemini_file_existence(gemini_file_name, file_search_metadata)

    logger.info(f"📊 [PRE-DELETE QUERY RESULTS]:")
    logger.info(f"   Raw File Exists: {existence_check['raw_file_exists']}")
    logger.info(f"   FileSearch Document Exists: {existence_check['file_search_exists']}")
    if existence_check['store_name']:
        logger.info(f"   FileSearch Store: {existence_check['store_name']}")
        logger.info(f"   Document Name: {existence_check['document_name']}")

    # Delete from FileSearch store first (if file was uploaded to FileSearch)
    if genai_client and file_search_metadata:
        try:
            import json
            if isinstance(file_search_metadata, str):
                metadata = json.loads(file_search_metadata)
            else:
                metadata = file_search_metadata

            if metadata.get('type') == 'file_search' and metadata.get('file_search_store_name') and metadata.get('document_name'):
                store_name = metadata['file_search_store_name']
                document_name = metadata['document_name']

                logger.info(f"📤 Attempting to delete from FileSearch store: {store_name}")
                logger.info(f"   Document: {document_name}")

                try:
                    # Delete the document from the FileSearch store
                    # This removes the file from the store AND cleans up embeddings
                    genai_client.file_search_stores.delete_document(
                        file_search_store_name=store_name,
                        document_name=document_name
                    )
                    deletion_results["file_search"]["success"] = True
                    logger.info(f"✅ [FILESEARCH] Deleted document: {document_name} from store: {store_name}")
                    logger.info(f"   All embeddings and index entries removed")

                    # POST-DELETION: Verify document was deleted
                    logger.info(f"🔍 [POST-DELETE VERIFICATION] Checking if document was deleted...")
                    try:
                        genai_client.file_search_stores.get_document(
                            file_search_store_name=store_name,
                            document_name=document_name
                        )
                        # If we get here, document still exists - log warning
                        logger.warning(f"⚠️ [POST-DELETE VERIFICATION] Document still exists after deletion attempt!")
                    except Exception:
                        # Document not found - this is expected/success
                        logger.info(f"✅ [POST-DELETE VERIFICATION] Document successfully removed from FileSearch store")

                except Exception as fs_error:
                    if "404" in str(fs_error) or "not found" in str(fs_error).lower():
                        deletion_results["file_search"]["error"] = "Document not found (already deleted)"
                        logger.warning(f"⚠️ [FILESEARCH] Document already deleted or not found: {document_name}")
                    else:
                        deletion_results["file_search"]["error"] = str(fs_error)
                        logger.error(f"❌ [FILESEARCH] Error deleting document: {fs_error}")
        except Exception as e:
            logger.warning(f"⚠️ [FILESEARCH] Could not parse metadata for FileSearch deletion: {e}")

    # Delete the raw file from Gemini (if it exists separately)
    if genai_client and gemini_file_name and not gemini_file_name.startswith("documents/"):
        try:
            logger.info(f"📤 Attempting to delete raw file from Gemini: {gemini_file_name}")
            genai_client.files.delete(name=gemini_file_name)
            deletion_results["gemini"]["success"] = True
            logger.info(f"✅ [GEMINI] Deleted raw file: {gemini_file_name}")
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                deletion_results["gemini"]["error"] = "File not found (already deleted)"
                logger.warning(f"⚠️ [GEMINI] File already deleted or not found: {gemini_file_name}")
            else:
                deletion_results["gemini"]["error"] = str(e)
                logger.error(f"❌ [GEMINI] Error deleting raw file: {e}")
    else:
        if gemini_file_name.startswith("documents/"):
            logger.info(f"ℹ️ [GEMINI] File is a FileSearch document, not a standalone file - skipping raw file deletion")
            deletion_results["gemini"]["success"] = True
        else:
            logger.warning(f"⚠️ [GEMINI] No gemini_file_name provided, skipping raw file deletion")

    # Delete from DB
    if table_name != "gemini_only":
        try:
            await file_service.delete_file_record(file_id, table_name)
            deletion_results["postgres"]["success"] = True
            logger.info(f"✅ [DATABASE] Deleted from {table_name}: ID={file_id}")
        except Exception as e:
            deletion_results["postgres"]["error"] = str(e)
            logger.error(f"❌ [DATABASE] Error deleting from {table_name}: {e}")

    # Determine success
    db_success = deletion_results["postgres"].get("success", False)
    file_search_success = deletion_results["file_search"].get("success", False)
    gemini_success = deletion_results["gemini"].get("success", False)

    logger.info(f"📊 Deletion Summary for {original_filename}:")
    logger.info(f"   FileSearch Store: {file_search_success}")
    logger.info(f"   Gemini Raw File: {gemini_success}")
    logger.info(f"   Database: {db_success}")

    # Check for complete success
    if db_success and (file_search_success or gemini_success or deletion_results["gemini"].get("error") == "Gemini client not available"):
        logger.info(f"✅ [SUCCESS] File {original_filename} completely removed from all locations")
        return {
            "success": True,
            "message": "File deleted successfully from FileSearch, Gemini, and database (all embeddings removed)",
            "details": deletion_results
        }
    elif db_success or file_search_success or gemini_success:
        logger.warning(f"⚠️ [PARTIAL] File {original_filename} removed from some locations:")
        logger.warning(f"   FileSearch: {deletion_results['file_search'].get('success', False)}")
        logger.warning(f"   Gemini: {deletion_results['gemini'].get('success', False)}")
        logger.warning(f"   Database: {deletion_results['postgres'].get('success', False)}")
        return {
            "success": True,
            "message": "File deletion processed (removed from some locations)",
            "details": deletion_results
        }
    else:
        logger.error(f"❌ [FAILURE] Could not delete {original_filename} from any location!")
        logger.error(f"   FileSearch error: {deletion_results['file_search'].get('error')}")
        logger.error(f"   Gemini error: {deletion_results['gemini'].get('error')}")
        logger.error(f"   Database error: {deletion_results['postgres'].get('error')}")
        raise HTTPException(status_code=500, detail="Failed to delete file from FileSearch, Gemini, and database")


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
