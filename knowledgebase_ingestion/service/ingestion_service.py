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
    Process file with Gemini - uploads file directly to FileSearch store (no fallback).

    Args:
        tmp_path: Path to the temporary file
        file_display_name: Display name for the file
        original_filename: Original filename
        mime_type: MIME type of the file
        user_email: User email for metadata
        file_search_store_name: Optional override for store name

    Returns:
        Tuple of (uploaded_file, final_state, gemini_processed_at, file_search_metadata)
    """
    from shared.file_search import get_file_search_store_by_display_name

    genai_client = get_genai_client()
    if not genai_client:
        logger.error("❌ Gemini client not available")
        raise Exception("Gemini client not configured")

    # Detect proper MIME type - use magic bytes from file path
    final_mime_type = detect_mime_type_from_extension(original_filename, mime_type, tmp_path)

    # Create display name
    if file_display_name != original_filename:
        gemini_display_name = f"{file_display_name} | {original_filename}"
    else:
        gemini_display_name = original_filename

    logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")

    try:
        # Use provided store name or get from config
        if not file_search_store_name:
            store_display_name = settings.gemini_file_search_store_name
            if not store_display_name:
                logger.error("❌ GEMINI_FILE_SEARCH_STORE_NAME not configured")
                raise Exception("GEMINI_FILE_SEARCH_STORE_NAME environment variable is required")

            logger.info(f"📦 Looking up FileSearch store: {store_display_name}")

            # Look up store by display name
            file_search_store_name = get_file_search_store_by_display_name(
                genai_client,
                display_name=store_display_name
            )

            if not file_search_store_name:
                logger.error(f"❌ FileSearch store '{store_display_name}' not found")
                raise Exception(f"FileSearch store '{store_display_name}' not found")

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
        document_name = None
        final_state = "PENDING"
        gemini_processed_at = None

        while not operation.done:
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                logger.error(f"❌ Timeout waiting for file upload to complete")
                raise Exception("File upload timeout")

            await asyncio.sleep(5)
            operation = genai_client.operations.get(operation)

        # FileSearch upload returns result in response.document_name
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
            file_search_metadata = {
                'type': 'file_search',
                'file_search_store_name': file_search_store_name,
                'document_name': document_name,
                'uploaded_at': gemini_processed_at.isoformat()
            }

            logger.info(f"✅ [GEMINI] Upload complete to FileSearch store. Document: {document_name}")
            logger.info(f"📝 [METADATA] Stored FileSearch info: store={file_search_store_name}, document={document_name}")
            return uploaded_file, final_state, gemini_processed_at, file_search_metadata
        else:
            logger.error(f"❌ [GEMINI] Upload failed - no document_name in response: {operation}")
            raise Exception("FileSearch upload failed - no document returned")

    except Exception as e:
        logger.error(f"❌ Error uploading to FileSearch: {e}")
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
    # Validate file_id
    if not file_id:
        return {"success": False, "error": "file_id is required"}
    
    # Check if this looks like a URL instead of a file ID
    if file_id.startswith(('http://', 'https://')):
        logger.error(f"❌ [INVALID INPUT] {file_id} appears to be a URL, not a file ID")
        logger.error(f"   Use /web/{id} endpoint for websites, not /files/{id}")
        return {"success": False, "error": f"Invalid input: {file_id} appears to be a URL. Use /web/{id} endpoint for websites."}

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
                    # Use force deletion to avoid FAILED_PRECONDITION errors
                    logger.info(f"🗑️ [FILESEARCH] Force deleting document: {document_name}")
                    genai_client.file_search_stores.documents.delete(
                        name=document_name,
                        config={'force': True}
                    )
                    deletion_results["file_search"]["success"] = True
                    logger.info(f"✅ [FILESEARCH] Force deleted document: {document_name} from store: {store_name}")
                except Exception as e:
                    # If force deletion fails, try the manual chunk deletion approach
                    logger.warning(f"⚠️ [FILESEARCH] Force deletion failed, trying manual chunk deletion: {e}")
                    
                    # First, delete all chunks from the document
                    logger.info(f"🗑️ [FILESEARCH] Deleting all chunks from document: {document_name}")
                    try:
                        # List chunks using the correct API method
                        chunks_response = genai_client.file_search_stores.documents.chunks.list(parent=document_name)
                        chunk_count = 0
                        
                        # Handle different response formats
                        chunks = []
                        if hasattr(chunks_response, 'chunks'):
                            chunks = chunks_response.chunks
                        elif hasattr(chunks_response, '__iter__'):
                            chunks = chunks_response
                        
                        for chunk in chunks:
                            try:
                                chunk_name = chunk.name if hasattr(chunk, 'name') else chunk
                                genai_client.file_search_stores.documents.chunks.delete(name=chunk_name)
                                chunk_count += 1
                                logger.debug(f"   Deleted chunk: {chunk_name}")
                            except Exception as chunk_error:
                                logger.warning(f"⚠️ Could not delete chunk {chunk_name}: {chunk_error}")
                        
                        logger.info(f"✅ [FILESEARCH] Deleted {chunk_count} chunks from document")
                        
                        # Wait a moment for chunks to be fully deleted
                        import time
                        time.sleep(0.5)
                        
                    except Exception as chunks_error:
                        logger.warning(f"⚠️ [FILESEARCH] Could not list/delete chunks for {document_name}: {chunks_error}")
                        # Continue with document deletion anyway

                    # Now delete the document itself
                    logger.info(f"🗑️ [FILESEARCH] Deleting document: {document_name}")
                    try:
                        genai_client.file_search_stores.documents.delete(name=document_name)
                        deletion_results["file_search"]["success"] = True
                        logger.info(f"✅ [FILESEARCH] Deleted document: {document_name} from store: {store_name}")
                    except Exception as doc_delete_error:
                        if "FAILED_PRECONDITION" in str(doc_delete_error) and chunk_count > 0:
                            logger.warning(f"⚠️ Document still has chunks, retrying after delay...")
                            time.sleep(1)
                            # Retry document deletion
                            genai_client.file_search_stores.documents.delete(name=document_name)
                            deletion_results["file_search"]["success"] = True
                            logger.info(f"✅ [FILESEARCH] Deleted document on retry: {document_name}")
                        else:
                            raise doc_delete_error
                    logger.info(f"   All embeddings and index entries removed")

                    # POST-DELETION: Verify document was deleted
                    logger.info(f"🔍 [POST-DELETE VERIFICATION] Checking if document was deleted...")
                    try:
                        genai_client.file_search_stores.documents.get(name=document_name)
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
        if gemini_file_name and gemini_file_name.startswith("documents/"):
            logger.info(f"ℹ️ [GEMINI] File is a FileSearch document, not a standalone file - skipping raw file deletion")
            deletion_results["gemini"]["success"] = True
        else:
            logger.warning(f"⚠️ [GEMINI] No gemini_file_name provided, skipping raw file deletion")

    # Delete from DB within a transaction - only if FileStore deletion succeeded or was skipped
    if table_name != "gemini_only":
        # Check if FileStore deletion was critical and failed
        file_search_was_attempted = genai_client and file_search_metadata
        file_search_failed = file_search_was_attempted and deletion_results["file_search"]["success"] == False

        if file_search_failed:
            # FileStore deletion was attempted but failed - abort database deletion
            deletion_results["postgres"]["error"] = "Aborting database deletion: FileStore deletion failed. Database unchanged."
            logger.error(f"❌ [TRANSACTION] Aborting database deletion due to FileStore failure. Database remains unchanged.")
        else:
            # FileStore deletion succeeded or was not applicable - proceed with database deletion in a transaction
            try:
                from shared.db import get_db_connection

                async with get_db_connection() as conn:
                    # Start explicit transaction
                    async with conn.transaction():
                        await file_service.delete_file_record(file_id, table_name)
                        deletion_results["postgres"]["success"] = True
                        logger.info(f"✅ [DATABASE] Deleted from {table_name}: ID={file_id} (transaction committed)")
            except Exception as e:
                # Transaction automatically rolled back on exception
                deletion_results["postgres"]["error"] = f"Database deletion failed and rolled back: {str(e)}"
                logger.error(f"❌ [DATABASE] Transaction rolled back - Error deleting from {table_name}: {e}")

    # Determine success
    db_success = deletion_results["postgres"].get("success", False)
    db_error = deletion_results["postgres"].get("error")
    file_search_success = deletion_results["file_search"].get("success", False)
    file_search_error = deletion_results["file_search"].get("error")
    gemini_success = deletion_results["gemini"].get("success", False)
    gemini_error = deletion_results["gemini"].get("error")

    logger.info(f"📊 Deletion Summary for {original_filename}:")
    logger.info(f"   FileSearch Store: {file_search_success}")
    logger.info(f"   Gemini Raw File: {gemini_success}")
    logger.info(f"   Database: {db_success}")

    # Check for transactional success - all critical operations must succeed
    all_operations_succeeded = db_success and (file_search_success or gemini_success or table_name == "gemini_only")

    if all_operations_succeeded:
        # Complete success - file removed from all locations, database transaction committed
        logger.info(f"✅ [TRANSACTION SUCCESS] File {original_filename} completely removed from all locations")
        return {
            "success": True,
            "message": f"File deleted successfully (all embeddings removed, database transaction committed)",
            "details": deletion_results,
            "transaction_status": "committed"
        }
    elif db_error and "Aborting" in db_error:
        # FileStore deletion failed, database was NOT touched
        logger.error(f"❌ [TRANSACTION ABORTED] {db_error}")
        raise HTTPException(
            status_code=500,
            detail=f"Deletion failed: FileStore deletion failed - database unchanged. Error: {file_search_error or gemini_error}"
        )
    elif db_error and "rolled back" in db_error.lower():
        # Database deletion failed, transaction was rolled back
        logger.error(f"❌ [TRANSACTION ROLLED BACK] {db_error}")
        raise HTTPException(
            status_code=500,
            detail=f"Deletion failed: Database deletion failed and rolled back - FileStore changes remain. Please contact support. Error: {db_error}"
        )
    elif db_success and (file_search_success or gemini_success):
        # Partial success but database was committed
        logger.warning(f"⚠️ [PARTIAL SUCCESS] File {original_filename} partially removed")
        logger.warning(f"   Database: ✅ Committed")
        logger.warning(f"   FileSearch: {file_search_success}")
        logger.warning(f"   Gemini: {gemini_success}")
        return {
            "success": True,
            "message": f"File deleted from database. FileSearch/Gemini status: FileSearch={file_search_success}, Gemini={gemini_success}",
            "details": deletion_results,
            "transaction_status": "committed"
        }
    else:
        # Complete failure
        logger.error(f"❌ [FAILURE] Could not delete {original_filename} from any location!")
        logger.error(f"   FileSearch error: {file_search_error}")
        logger.error(f"   Gemini error: {gemini_error}")
        logger.error(f"   Database error: {db_error}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file. FileSearch: {file_search_error or 'N/A'}, Gemini: {gemini_error or 'N/A'}, Database: {db_error or 'N/A'}"
        )


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


async def delete_website_hierarchy(website_id: str) -> Dict[str, Any]:
    """Delete a website and all its child pages from FileSearch first, then database."""
    try:
        from shared.db import get_db_connection
        from knowledgebase_ingestion.core.ai import get_genai_client

        # Validate website_id
        if not website_id:
            return {"success": False, "error": "website_id is required"}

        # First get all records in hierarchy (parent + all children)
        async with get_db_connection() as conn:
            # Get parent and all recursive children
            hierarchy_query = """
                WITH RECURSIVE website_hierarchy AS (
                    -- Base case: parent page
                    SELECT id, original_url, metadata, parent_id, depth, celery_task_id, 0 as level
                    FROM scraped_websites
                    WHERE id = $1

                    UNION ALL

                    -- Recursive case: all children
                    SELECT w.id, w.original_url, w.metadata, w.parent_id, w.depth, w.celery_task_id, wh.level + 1
                    FROM scraped_websites w
                    INNER JOIN website_hierarchy wh ON w.parent_id = wh.id
                )
                SELECT id, original_url, metadata, celery_task_id, level
                FROM website_hierarchy
                ORDER BY level, id;
            """
            # Convert website_id to int if it's numeric, otherwise keep as string
            website_id_param = int(website_id) if website_id and website_id.isdigit() else website_id
            hierarchy_records = await conn.fetch(hierarchy_query, website_id_param)

            if not hierarchy_records:
                return {"success": False, "error": "Website not found"}

            # Step 0: Revoke any running Celery tasks for these websites
            logger.info(f"🔴 Checking for running Celery tasks to revoke...")
            celery_tasks_revoked = 0
            celery_revoke_errors = []

            for record in hierarchy_records:
                celery_task_id = record.get("celery_task_id")
                if celery_task_id:
                    try:
                        # Revoke task using knowledgebase_ingestion's celery_app
                        # Both services share the same Redis broker, so this works for all task types
                        from knowledgebase_ingestion.celery_app import celery_app
                        celery_app.control.revoke(celery_task_id, terminate=True)
                        celery_tasks_revoked += 1
                        logger.info(f"🔴 Revoked Celery task {celery_task_id} for page {record['id']}")
                    except Exception as e:
                        error_msg = f"Failed to revoke Celery task {celery_task_id}: {e}"
                        logger.warning(f"⚠️ {error_msg}")
                        celery_revoke_errors.append(error_msg)

            if celery_tasks_revoked > 0:
                logger.info(f"✅ Revoked {celery_tasks_revoked} Celery tasks before deletion")
            
            logger.info(f"🌳 Found {len(hierarchy_records)} pages in website hierarchy to delete")
            
            # Step 1: Delete all from FileSearch first
            genai_client = get_genai_client()
            filesearch_deleted = 0
            filesearch_errors = []
            
            for record in hierarchy_records:
                metadata = record.get("metadata")
                if metadata and genai_client:
                    try:
                        import json
                        if isinstance(metadata, str):
                            metadata_dict = json.loads(metadata)
                        else:
                            metadata_dict = metadata

                        if metadata_dict.get('type') == 'file_search' and metadata_dict.get('document_name'):
                            document_name = metadata_dict['document_name']
                            logger.info(f"🗑️ Deleting page {record['id']} (level {record['level']}) from FileSearch: {document_name}")

                            # Try force deletion first
                            try:
                                genai_client.file_search_stores.documents.delete(
                                    name=document_name,
                                    config={'force': True}
                                )
                                filesearch_deleted += 1
                                logger.info(f"✅ Force deleted from FileSearch: {document_name}")
                            except Exception as force_error:
                                logger.warning(f"⚠️ Force deletion failed for {document_name}, trying manual chunk deletion: {force_error}")
                                
                                # Fall back to manual chunk deletion
                                try:
                                    # List chunks using the correct API method
                                    chunks_response = genai_client.file_search_stores.documents.chunks.list(parent=document_name)
                                    chunk_count = 0
                                    
                                    # Handle different response formats
                                    chunks = []
                                    if hasattr(chunks_response, 'chunks'):
                                        chunks = chunks_response.chunks
                                    elif hasattr(chunks_response, '__iter__'):
                                        chunks = chunks_response
                                    
                                    for chunk in chunks:
                                        try:
                                            chunk_name = chunk.name if hasattr(chunk, 'name') else chunk
                                            genai_client.file_search_stores.documents.chunks.delete(name=chunk_name)
                                            chunk_count += 1
                                        except Exception as chunk_error:
                                            logger.debug(f"   Could not delete chunk {chunk_name}: {chunk_error}")
                                            pass  # Continue even if individual chunks fail
                                    logger.info(f"   Deleted {chunk_count} chunks from document")
                                    
                                    # Wait a moment for chunks to be fully deleted
                                    import time
                                    time.sleep(0.5)
                                    
                                except Exception as chunks_error:
                                    logger.debug(f"   Could not delete chunks: {chunks_error}")
                                    pass  # Continue with document deletion anyway

                                # Now delete the document itself
                                try:
                                    genai_client.file_search_stores.documents.delete(
                                        name=document_name
                                    )
                                    filesearch_deleted += 1
                                    logger.info(f"✅ Deleted from FileSearch: {document_name}")
                                except Exception as doc_delete_error:
                                    if "FAILED_PRECONDITION" in str(doc_delete_error):
                                        logger.warning(f"⚠️ Document still has chunks, retrying after delay...")
                                        import time
                                        time.sleep(1)
                                        # Retry document deletion
                                        genai_client.file_search_stores.documents.delete(name=document_name)
                                        filesearch_deleted += 1
                                        logger.info(f"✅ Deleted from FileSearch on retry: {document_name}")
                                    else:
                                        logger.error(f"❌ Failed to delete from FileSearch: {doc_delete_error}")
                                        filesearch_errors.append(str(doc_delete_error))
                    except Exception as e:
                        if "404" in str(e) or "not found" in str(e).lower():
                            logger.warning(f"⚠️ FileSearch document already deleted for page {record['id']}: {e}")
                        else:
                            error_msg = f"Could not delete from FileSearch for page {record['id']}: {e}"
                            logger.error(f"❌ {error_msg}")
                            filesearch_errors.append(error_msg)
            
            # Step 2: Delete all from database (only if FileSearch deletion succeeded for most)
            successful_deletions = len(hierarchy_records) - len(filesearch_errors)
            success_rate = successful_deletions / len(hierarchy_records) if len(hierarchy_records) > 0 else 0
            
            logger.info(f"📊 FileSearch Deletion Results: {successful_deletions}/{len(hierarchy_records)} successful ({success_rate:.1%})")
            
            # Only proceed with database deletion if at least 50% succeeded AND no critical errors
            if success_rate < 0.5:
                return {
                    "success": False, 
                    "error": f"Too many FileSearch deletion failures ({len(filesearch_errors)}/{len(hierarchy_records)}). Success rate: {success_rate:.1%}. Aborted database deletion."
                }
            
            if len(filesearch_errors) > 0:
                logger.warning(f"⚠️ Proceeding with database deletion despite {len(filesearch_errors)} FileSearch errors (success rate: {success_rate:.1%})")

            # Begin ATOMIC database transaction for deletion
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Delete all records in hierarchy - ATOMIC OPERATION
                    delete_query = """
                        WITH RECURSIVE website_hierarchy AS (
                            SELECT id FROM scraped_websites WHERE id = $1
                            UNION ALL
                            SELECT w.id FROM scraped_websites w
                            INNER JOIN website_hierarchy wh ON w.parent_id = wh.id
                        )
                        DELETE FROM scraped_websites WHERE id IN (SELECT id FROM website_hierarchy)
                    """
                    result = await conn.execute(delete_query, website_id_param)
                    deleted_count = int(result.split()[-1]) if result else 0
                    logger.info(f"✅ [ATOMIC_TX] Deleted {deleted_count} website records from database")
            
            return {
                "success": True, 
                "message": f"Website hierarchy deleted successfully: {deleted_count} pages total",
                "details": {
                    "total_pages": len(hierarchy_records),
                    "filesearch_deleted": filesearch_deleted,
                    "database_deleted": deleted_count,
                    "filesearch_errors": filesearch_errors
                }
            }

    except Exception as e:
        logger.error(f"Error deleting website hierarchy {website_id}: {e}")
        return {"success": False, "error": str(e)}


async def nuke_filestore_and_database() -> Dict[str, Any]:
    """
    NUCLEAR DELETE: Completely remove all documents from FileSearch store and all records from database.
    This is destructive and should only be used when explicitly requested by admin.
    """
    logger.warning("⚠️⚠️⚠️ NUCLEAR DELETE INITIATED - REMOVING ALL DATA FROM FILESTORE AND DATABASE ⚠️⚠️⚠️")

    genai_client = get_genai_client()
    file_service = get_file_service()

    nuke_results = {
        "filestore_documents_deleted": 0,
        "filestore_errors": [],
        "database_files_deleted": 0,
        "database_scrapes_deleted": 0,
        "database_errors": [],
        "timestamp": datetime.utcnow().isoformat()
    }

    # Phase 1: Delete all documents from FileSearch store
    if genai_client:
        try:
            # Get store display name from settings (same pattern as other services)
            store_display_name = settings.gemini_file_search_store_name
            if not store_display_name:
                logger.warning("⚠️ GEMINI_FILE_SEARCH_STORE_NAME not configured - skipping FileSearch deletion")
            else:
                # Look up store by display name
                from shared.file_search import get_file_search_store_by_display_name

                file_search_store_name = get_file_search_store_by_display_name(
                    genai_client,
                    display_name=store_display_name
                )

                try:
                    if not file_search_store_name:
                        # Store doesn't exist, create it fresh
                        logger.warning(f"⚠️ FileSearch store '{store_display_name}' not found - creating new one")
                        logger.info(f"🔨 Creating new FileSearch store with display_name: {store_display_name}")
                        new_store = genai_client.file_search_stores.create(
                            config={'display_name': store_display_name}
                        )
                        logger.info(f"✅ FileSearch store created: {new_store.name}")
                        logger.info(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")
                        nuke_results["filestore_documents_deleted"] = "NONE"
                        nuke_results["filestore_recreated"] = True
                    else:
                        # Store exists, delete and recreate it
                        logger.warning(f"📤 Attempting to delete FileSearch store: {file_search_store_name}")
                        logger.warning(f"🗑️ Deleting entire FileSearch store with force=True: {file_search_store_name}")
                        genai_client.file_search_stores.delete(
                            name=file_search_store_name,
                            config={'force': True}
                        )
                        logger.warning(f"✅ FileSearch store deleted successfully")
                        nuke_results["filestore_documents_deleted"] = "ALL"

                        # Recreate the store with proper display_name for future use
                        logger.info(f"🔄 Recreating FileSearch store with display_name: {store_display_name}")
                        recreated_store = genai_client.file_search_stores.create(
                            config={'display_name': store_display_name}
                        )
                        logger.info(f"✅ FileSearch store recreated: {recreated_store.name}")
                        logger.info(f"   Display name: {getattr(recreated_store, 'display_name', 'N/A')}")
                        nuke_results["filestore_recreated"] = True

                except Exception as e:
                    error_msg = f"Error deleting/recreating FileSearch store: {str(e)}"
                    logger.error(f"❌ {error_msg}")
                    nuke_results["filestore_errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Error accessing FileSearch: {str(e)}"
            logger.error(f"❌ {error_msg}")
            nuke_results["filestore_errors"].append(error_msg)
    else:
        logger.warning("⚠️ Gemini client not available - skipping FileSearch deletion")

    # Phase 2: Delete all records from database within a transaction
    # Only proceed if FileStore deletion succeeded or had no errors
    if nuke_results["filestore_errors"]:
        # FileStore deletion had errors - abort database deletion
        logger.error(f"❌ [TRANSACTION ABORTED] FileStore deletion had errors. Aborting database deletion to maintain consistency.")
        logger.error(f"   FileStore errors: {nuke_results['filestore_errors']}")
        nuke_results["database_errors"].append("Aborted: FileStore deletion failed. Database unchanged.")
        nuke_results["transaction_status"] = "aborted"
    else:
        # FileStore deletion succeeded, was skipped, or was already deleted - proceed with database deletion in transaction
        try:
            from shared.db import get_db_connection

            # Step 1: MARK ALL TASKS FOR CANCELLATION VIA REDIS FLAGS
            logger.critical("🔴🔴🔴 MARKING ALL CELERY TASKS FOR CANCELLATION 🔴🔴🔴")
            celery_tasks_marked = 0
            try:
                from knowledgebase_ingestion.celery_app import celery_app
                import redis as redis_lib

                # First: Mark all task IDs from database with cancellation flags
                logger.critical("🛑 [1/3] Setting Redis cancellation flags for all tasks...")
                try:
                    # Build DB-0 and DB-1 URLs from base REDIS_URL
                    base_redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                    # Strip any existing /N suffix then append /0 and /1
                    base_redis_url_stripped = base_redis_url.rsplit('/', 1)[0] if base_redis_url.count('/') >= 3 else base_redis_url
                    redis_url_db0 = f"{base_redis_url_stripped}/0"
                    redis_url_db1 = f"{base_redis_url_stripped}/1"

                    # Connect to BOTH Redis databases (DB0=file tasks, DB1=website tasks)
                    redis_conn_db0 = redis_lib.from_url(redis_url_db0)
                    redis_conn_db1 = redis_lib.from_url(redis_url_db1)

                    async with get_db_connection() as conn:
                        # Get all task IDs from file_uploads
                        file_tasks = await conn.fetch("SELECT celery_task_id FROM file_uploads WHERE celery_task_id IS NOT NULL")
                        website_tasks = await conn.fetch("SELECT celery_task_id FROM scraped_websites WHERE celery_task_id IS NOT NULL")

                        # Set cancellation flags on DB0 for file tasks
                        for t in file_tasks:
                            try:
                                cancelled_key = f"task_cancelled:{t['celery_task_id']}"
                                redis_conn_db0.setex(cancelled_key, 3600, "1")
                                celery_tasks_marked += 1
                                logger.critical(f"🛑 [DB0] MARKED FOR CANCELLATION: {t['celery_task_id']}")
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to mark file task {t['celery_task_id']}: {e}")

                        # Set cancellation flags on DB1 for website tasks
                        for t in website_tasks:
                            try:
                                cancelled_key = f"task_cancelled:{t['celery_task_id']}"
                                redis_conn_db1.setex(cancelled_key, 3600, "1")
                                celery_tasks_marked += 1
                                logger.critical(f"🛑 [DB1] MARKED FOR CANCELLATION: {t['celery_task_id']}")
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to mark website task {t['celery_task_id']}: {e}")

                    redis_conn_db0.close()
                    redis_conn_db1.close()
                    logger.critical(f"✅ [1/3] Marked {celery_tasks_marked} tasks for cancellation on DB0+DB1")

                except Exception as e:
                    logger.warning(f"⚠️ Error marking tasks for cancellation: {e}")

                # Second: Purge all pending queues to clear queued tasks (both DB0 and DB1)
                logger.critical("🛑 [2/3] Purging Redis queues (DB0 file + DB1 website)...")
                try:
                    celery_app.control.purge()  # Purges DB0 (file upload queue)
                    logger.critical("✅ [2/3a] File upload queue (DB0) purged")
                except Exception as e:
                    logger.warning(f"⚠️ Could not purge file queue (DB0): {e}")
                try:
                    from website_crawling.celery_app import celery_app as website_celery_app
                    website_celery_app.control.purge()  # Purges DB1 (website crawling queue)
                    logger.critical("✅ [2/3b] Website crawling queue (DB1) purged")
                except Exception as e:
                    logger.warning(f"⚠️ Could not purge website queue (DB1): {e}")

                # Third: Revoke all tasks to stop pending ones
                logger.critical("🛑 [3/3] Revoking pending tasks...")
                try:
                    celery_app.control.revoke('*', terminate=False)  # Don't send SIGTERM, just revoke
                    logger.critical("✅ [3/3] All pending tasks revoked")
                except Exception as e:
                    logger.warning(f"⚠️ Could not revoke tasks: {e}")

                logger.critical("✅✅✅ ALL CELERY TASKS MARKED FOR CANCELLATION ✅✅✅")
                nuke_results["celery_marked_for_cancellation"] = celery_tasks_marked

            except Exception as e:
                logger.error(f"❌ Error marking tasks for cancellation: {e}")
                nuke_results["celery_cancellation_error"] = str(e)

            # Step 2: Mark all tasks as cancelled in database before deletion
            # This ensures if any task continues running, it's marked as cancelled
            try:
                async with get_db_connection() as conn:
                    await conn.execute("UPDATE file_uploads SET processing_status = 'cancelled' WHERE processing_status IN ('pending', 'processing')")
                    await conn.execute("UPDATE scraped_websites SET processing_status = 'cancelled' WHERE processing_status IN ('pending', 'processing')")
                    logger.warning("✅ Marked all pending/processing tasks as 'cancelled'")
            except Exception as e:
                logger.warning(f"⚠️ Could not mark tasks as cancelled: {e}")

            # Step 3: Delete from database
            async with get_db_connection() as conn:
                # Start explicit transaction for database deletion
                async with conn.transaction():
                    logger.warning("🗑️ Deleting all file_uploads records within transaction...")
                    deleted_files = await conn.execute("DELETE FROM file_uploads")
                    nuke_results["database_files_deleted"] = int(deleted_files.split()[-1]) if deleted_files else 0
                    logger.warning(f"✅ Deleted {nuke_results['database_files_deleted']} file uploads from database")

                    # Delete all scraped_websites
                    logger.warning("🗑️ Deleting all scraped_websites records within transaction...")
                    deleted_scrapes = await conn.execute("DELETE FROM scraped_websites")
                    nuke_results["database_scrapes_deleted"] = int(deleted_scrapes.split()[-1]) if deleted_scrapes else 0
                    logger.warning(f"✅ Deleted {nuke_results['database_scrapes_deleted']} scraped websites from database")

                # Transaction automatically commits on successful completion
                logger.warning(f"✅ Database transaction committed - all records deleted")
                nuke_results["transaction_status"] = "committed"

        except Exception as e:
            # Transaction automatically rolled back on exception
            error_msg = f"Database transaction failed and rolled back: {str(e)}"
            logger.error(f"❌ {error_msg}")
            nuke_results["database_errors"].append(error_msg)
            nuke_results["transaction_status"] = "rolled_back"

    # Summary and determine final status
    transaction_status = nuke_results.get("transaction_status", "unknown")
    has_db_errors = len(nuke_results["database_errors"]) > 0
    has_fs_errors = len(nuke_results["filestore_errors"]) > 0

    logger.warning("⚠️⚠️⚠️ NUCLEAR DELETE COMPLETED ⚠️⚠️⚠️")

    if transaction_status == "committed":
        # Complete success - both FileStore and database cleared
        logger.warning(f"✅ SUCCESS: FileStore and database fully cleared")
        logger.warning(f"📊 Deleted: {nuke_results['database_files_deleted']} files, {nuke_results['database_scrapes_deleted']} scrapes")
        return {
            "success": True,
            "message": f"Nuclear delete successful: Deleted {nuke_results['database_files_deleted']} uploaded files and {nuke_results['database_scrapes_deleted']} scraped websites from database. FileStore cleared.",
            "details": nuke_results,
            "transaction_status": "committed"
        }
    elif transaction_status == "rolled_back":
        # Database transaction failed - rolled back, but FileStore may have been modified
        logger.error(f"❌ PARTIAL FAILURE: FileStore was cleared but database deletion rolled back")
        return {
            "success": False,
            "message": f"Nuclear delete FAILED: FileStore was cleared but database deletion failed and was rolled back. Please contact support. Error: {nuke_results['database_errors'][0] if nuke_results['database_errors'] else 'Unknown'}",
            "details": nuke_results,
            "transaction_status": "rolled_back"
        }
    elif transaction_status == "aborted":
        # FileStore deletion failed, database was not touched
        logger.error(f"❌ FAILURE: FileStore deletion failed, database remains unchanged")
        return {
            "success": False,
            "message": f"Nuclear delete FAILED: FileStore deletion failed. Database unchanged. Error: {nuke_results['filestore_errors'][0] if nuke_results['filestore_errors'] else 'Unknown'}",
            "details": nuke_results,
            "transaction_status": "aborted"
        }
    else:
        # Unknown state
        logger.error(f"⚠️ Unknown transaction state: {transaction_status}")
        return {
            "success": False,
            "message": f"Nuclear delete ended in unknown state. Please review the logs. FileStore errors: {nuke_results['filestore_errors']}, Database errors: {nuke_results['database_errors']}",
            "details": nuke_results,
            "transaction_status": "unknown"
        }


# =============================================================================
# CELERY-BASED ASYNC PROCESSING
# =============================================================================

async def upload_file_celery(
    file: UploadFile,
    display_name: Optional[str] = None,
    user_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Celery-based async upload - returns immediately after creating DB record with pending status.
    Actual processing is dispatched to Celery worker.
    """
    file_service = get_file_service()
    original_filename = sanitize_filename(file.filename or "unknown_file")
    file_display_name = display_name or original_filename
    email = user_email or "admin"

    tmp_path = None

    try:
        # Quick validation
        ext_valid, ext_error = validate_file_extension(original_filename)
        if not ext_valid:
            raise HTTPException(status_code=400, detail=ext_error)

        mime_valid, mime_error = validate_mime_type(file.content_type, original_filename)
        if not mime_valid:
            raise HTTPException(status_code=400, detail=mime_error)

        # Stream to temp file
        tmp_path, file_size = await stream_to_temp_file(file, original_filename)

        # Validate file size
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise HTTPException(status_code=413, detail=size_error)

        # Calculate hash and detect MIME type
        sha256_hash = calculate_sha256(tmp_path)
        detected_mime_type = detect_mime_type_from_extension(original_filename, file.content_type, tmp_path)

        logger.info(f"🔍 [CELERY] Detected MIME: {detected_mime_type} for {original_filename}")

        # Check for duplicates
        duplicate_check = await file_service.handle_duplicate_check(sha256_hash, original_filename, False)
        if not duplicate_check.get("allow", True):
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise HTTPException(status_code=409, detail=duplicate_check.get("detail", "File already exists"))

        # Create initial DB record with processing_status='pending'
        from shared.db import get_db_connection

        user_role_id = await file_service.get_admin_user_role_id(email)
        if user_role_id is None:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise HTTPException(status_code=403, detail="User does not have admin privileges")

        file_record_id = None
        async with get_db_connection() as conn:
            file_record_id = await conn.fetchval(
                """INSERT INTO file_uploads (user_role_id, original_filename, display_name, file_extension,
                   mime_type, file_size, sha256_hash, processing_status, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW()) RETURNING id""",
                user_role_id, original_filename, file_display_name,
                original_filename.rsplit('.', 1)[-1] if '.' in original_filename else '',
                detected_mime_type, file_size, sha256_hash, "pending"
            )

        logger.info(f"✅ [CELERY] Created DB record ID {file_record_id} with status='pending'")

        # Dispatch Celery task for actual processing
        from knowledgebase_ingestion.tasks import process_file_upload_task
        from knowledgebase_ingestion.celery_app import celery_app

        logger.info(f"📤 [TASK_DISPATCH] Preparing to dispatch task for file ID {file_record_id}, filename: {original_filename}, size: {file_size} bytes, mime: {detected_mime_type}")

        task = process_file_upload_task.delay(
            file_id=file_record_id,
            tmp_path=tmp_path,
            original_filename=original_filename,
            file_display_name=file_display_name,
            detected_mime_type=detected_mime_type,
            user_email=email,
            file_size=file_size,
            sha256_hash=sha256_hash
        )

        logger.info(f"✅ [CELERY] Dispatched Celery task {task.id} for file ID {file_record_id}")
        logger.info(f"📊 [TASK_INFO] Task State: {task.state}, Routing: 'file_processing' queue, Timeout: 30 minutes")

        # Store the Celery task_id in database so we can revoke it later if needed
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE file_uploads SET celery_task_id = $1 WHERE id = $2",
                task.id, file_record_id
            )
        logger.info(f"💾 [TASK_TRACKING] Stored celery_task_id {task.id} in database for file {file_record_id}")

        # Return immediate response with pending status
        return {
            "success": True,
            "message": "File upload queued for processing",
            "file": {
                "id": str(file_record_id),
                "original_filename": original_filename,
                "display_name": file_display_name,
                "size_bytes": str(file_size),
                "mime_type": detected_mime_type,
                "processing_status": "pending",
                "created_at": datetime.utcnow().isoformat()
            },
            "task_id": task.id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [CELERY] Error in upload_file_celery: {e}")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))
