"""
File Processing Service for Celery Worker
Contains ALL file processing logic moved from knowledgebase_ingestion
Handles: validation, Gemini uploads, metadata recording, deletion
"""

import asyncio
import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from shared.otel_logger import get_otel_logger
from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.core.config import settings
from knowledgebase_ingestion.service.docling_integration import (
    process_with_docling,
    should_use_docling_for_file,
    create_markdown_temp_file
)
from shared.file_search import get_file_search_store_by_display_name
from shared.html_processor import extract_content_from_html
from shared.db import get_db_connection

from ..utils.validation import (
    validate_file_extension,
    validate_file_size,
    validate_mime_type,
    sanitize_filename,
    detect_mime_type_from_extension
)
from ..utils.files import calculate_sha256, stream_to_temp_file
from .file_service import FileService

logger = get_otel_logger("processing_service", "celery-file-worker")


async def process_with_gemini(
    tmp_path: str,
    file_display_name: str,
    original_filename: str,
    mime_type: str,
    user_email: str = None,
    file_search_store_name: str = None
) -> Tuple[Any, str, datetime, Dict[str, Any]]:
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


async def process_file_content(
    original_filename: str,
    file_display_name: str,
    s3_key: str,
    file_size: int,
    user_email: str = "admin",
    celery_task_id: str = None
) -> Dict[str, Any]:
    """
    Complete file processing pipeline:
    1. Download from S3
    2. Validation (extension, MIME, size, duplicates)
    3. Format conversion (HTML→Markdown, PDF→Markdown via Docling)
    4. Gemini upload
    5. Database record creation
    6. Delete from S3

    Called directly from Celery task.
    """
    file_service = FileService()
    start_time = time.perf_counter()
    tmp_path = None
    markdown_tmp_path = None

    try:
        # S3 DOWNLOAD PHASE
        logger.info(f"📥 [S3] Downloading file from S3: {s3_key}")
        from shared.s3_file_storage import s3_file_storage

        success, result = await s3_file_storage.download_file(s3_key)
        if not success:
            logger.error(f"❌ [S3] Download failed: {result}")
            raise Exception(f"S3 download failed: {result}")

        file_bytes = result
        logger.info(f"✅ [S3] Downloaded {len(file_bytes)} bytes from S3")

        # Create temp file from downloaded bytes
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{original_filename}") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        logger.info(f"✅ Created temp file: {tmp_path}")

        # VALIDATION PHASE
        logger.info(f"🔍 [VALIDATION] Starting file validation for {original_filename}")

        # Validate file extension
        ext_valid, ext_error = validate_file_extension(original_filename)
        if not ext_valid:
            logger.error(f"❌ [VALIDATION] Extension invalid: {ext_error}")
            raise Exception(f"Extension validation failed: {ext_error}")

        # Validate MIME type
        mime_valid, mime_error = validate_mime_type("", original_filename)
        if not mime_valid:
            logger.error(f"❌ [VALIDATION] MIME type invalid: {mime_error}")
            raise Exception(f"MIME validation failed: {mime_error}")

        # Validate file size
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            logger.error(f"❌ [VALIDATION] File size invalid: {size_error}")
            raise Exception(f"Size validation failed: {size_error}")

        # Calculate hash and detect MIME type
        sha256_hash = calculate_sha256(tmp_path)
        detected_mime_type = detect_mime_type_from_extension(original_filename, "", tmp_path)

        logger.info(f"🔍 [ROUTING] Detected MIME: {detected_mime_type} for {original_filename}")

        # Check for duplicates
        duplicate_check = await file_service.handle_duplicate_check(sha256_hash, original_filename, False)
        if not duplicate_check.get("allow", True):
            logger.error(f"❌ [VALIDATION] Duplicate file detected")
            raise Exception(f"Duplicate file: {duplicate_check.get('detail', 'File already exists')}")

        # FORMAT CONVERSION PHASE
        markdown_tmp_path = None
        processed_successfully = False

        # 1. Route HTML files to HTML-specific pipeline
        if detected_mime_type == 'text/html' or original_filename.lower().endswith(('.html', '.htm')):
            logger.info(f"🌐 [ROUTING] Routing {original_filename} to HTML-specific pipeline")
            try:
                markdown_content, html_metadata = extract_content_from_html(tmp_path)

                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    original_tmp_path = tmp_path
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    processed_successfully = True
                    logger.info(f"✅ [HTML] Extracted {len(markdown_content)} characters from HTML")
                else:
                    error_msg = html_metadata.get("error", "HTML extraction failed")
                    logger.error(f"❌ [HTML] Extraction failed for {original_filename}: {error_msg}")
                    raise Exception(f"HTML extraction failed: {error_msg}")
            except Exception as e:
                logger.error(f"❌ [HTML] Unexpected error: {e}")
                raise

        # 2. Route PDFs and other Docling-supported files
        elif await should_use_docling_for_file(original_filename, detected_mime_type, file_size):
            logger.info(f"📄 [ROUTING] Routing {original_filename} to Docling pipeline")

            try:
                markdown_content, docling_metadata = await process_with_docling(
                    tmp_path,
                    original_filename,
                    detected_mime_type
                )

                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    original_tmp_path = tmp_path
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    processed_successfully = True
                    logger.info(f"✅ [DOCLING] Converted {original_filename} to markdown")
                else:
                    error_msg = docling_metadata.get("error", "Docling processing failed")
                    logger.error(f"❌ [DOCLING] Processing failed: {error_msg}")
                    raise Exception(f"Document conversion failed: {error_msg}")
            except Exception as e:
                logger.error(f"❌ [DOCLING] Error: {e}")
                raise
        else:
            logger.info(f"📝 [ROUTING] Skipping special processing for {detected_mime_type}")
            processed_successfully = True

        # GEMINI UPLOAD PHASE
        logger.info(f"🚀 [GEMINI] Initiating upload for {original_filename}")
        uploaded_file, final_state, gemini_processed_at, file_search_metadata = await process_with_gemini(
            tmp_path, file_display_name, original_filename, detected_mime_type, user_email
        )

        if final_state != "ACTIVE":
            logger.error(f"❌ Gemini upload failed: {final_state}")
            raise Exception(f"Gemini upload failed: Final state={final_state}")

        # DATABASE PHASE
        logger.info(f"💾 [DATABASE] Creating database record")
        file_record_id = await file_service.record_metadata(
            user_email=user_email,
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

        if not file_record_id:
            logger.error(f"❌ Database record creation failed")
            raise Exception("Database metadata recording failed")

        processing_time = time.perf_counter() - start_time
        logger.info(f"✅ [SUCCESS] Upload completed for {original_filename}")
        logger.info(f"   📁 Gemini File ID: {uploaded_file.name}")
        logger.info(f"   🗄️  Database ID: {file_record_id}")
        logger.info(f"   ⏱️  Time: {processing_time:.2f}s")
        logger.info(f"   📊 Size: {file_size} bytes")
        logger.info(f"   🔐 Hash: {sha256_hash}")

        return {
            "success": True,
            "message": "File processing completed",
            "file_id": file_record_id,
            "gemini_file_id": uploaded_file.name,
            "processing_time": processing_time
        }

    except Exception as e:
        logger.error(f"❌ Error processing file {original_filename}: {e}", exc_info=True)
        raise
    finally:
        # Cleanup: Delete from S3 and remove temporary files
        logger.info(f"🧹 [CLEANUP] Cleaning up S3 and temp files for {original_filename}")

        # Delete from S3
        try:
            from shared.s3_file_storage import s3_file_storage
            deleted = await s3_file_storage.delete_file(s3_key)
            if deleted:
                logger.info(f"✅ [S3] Deleted file from S3: {s3_key}")
            else:
                logger.warning(f"⚠️ [S3] Failed to delete from S3, but processing succeeded: {s3_key}")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ [S3] Error during S3 cleanup: {cleanup_error}")

        # Delete temporary files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.debug(f"✅ Deleted temp file: {tmp_path}")
            except:
                pass

        if markdown_tmp_path and os.path.exists(markdown_tmp_path):
            try:
                os.unlink(markdown_tmp_path)
                logger.debug(f"✅ Deleted markdown temp file: {markdown_tmp_path}")
            except:
                pass


async def delete_file_logic(file_id: str) -> Dict[str, Any]:
    """Delete a file from Gemini FileSearch and database with proper metadata handling."""
    if not file_id:
        return {"success": False, "error": "file_id is required"}

    genai_client = get_genai_client()
    file_service = FileService()

    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")

    gemini_file_name = file_id
    table_name = "gemini_only"
    original_filename = "Gemini-only file"
    file_search_metadata = None

    if not file_id.startswith("files/"):
        # Look up in DB
        try:
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
                        return {"success": False, "error": "File not found"}
        except Exception as e:
            logger.error(f"❌ [DELETE] Error looking up file record: {e}")
            return {"success": False, "error": str(e)}

    deletion_results = {
        "gemini": {"success": False, "error": None},
        "file_search": {"success": False, "error": None},
        "postgres": {"success": False, "error": None}
    }

    # Delete from FileSearch store
    if genai_client and file_search_metadata:
        try:
            if isinstance(file_search_metadata, str):
                metadata = json.loads(file_search_metadata)
            else:
                metadata = file_search_metadata

            if metadata.get('type') == 'file_search' and metadata.get('file_search_store_name') and metadata.get('document_name'):
                store_name = metadata['file_search_store_name']
                document_name = metadata['document_name']

                logger.info(f"📤 Deleting from FileSearch store: {store_name}")
                try:
                    genai_client.file_search_stores.documents.delete(name=document_name)
                    deletion_results["file_search"]["success"] = True
                    logger.info(f"✅ [FILESEARCH] Deleted document: {document_name}")
                except Exception as e:
                    if "404" in str(e) or "not found" in str(e).lower():
                        deletion_results["file_search"]["error"] = "Document not found (already deleted)"
                        logger.warning(f"⚠️ Document already deleted: {document_name}")
                    else:
                        deletion_results["file_search"]["error"] = str(e)
                        logger.error(f"❌ Error deleting document: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Could not parse metadata for FileSearch deletion: {e}")

    # Delete raw file from Gemini
    if genai_client and gemini_file_name and not gemini_file_name.startswith("documents/"):
        try:
            logger.info(f"📤 Deleting raw file from Gemini: {gemini_file_name}")
            genai_client.files.delete(name=gemini_file_name)
            deletion_results["gemini"]["success"] = True
            logger.info(f"✅ Deleted raw file: {gemini_file_name}")
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                deletion_results["gemini"]["error"] = "File not found (already deleted)"
                logger.warning(f"⚠️ File already deleted: {gemini_file_name}")
            else:
                deletion_results["gemini"]["error"] = str(e)
                logger.error(f"❌ Error deleting raw file: {e}")

    # Delete from database
    if table_name != "gemini_only":
        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    await file_service.delete_file_record(file_id, table_name)
                    deletion_results["postgres"]["success"] = True
                    logger.info(f"✅ Deleted from {table_name}: ID={file_id}")
        except Exception as e:
            deletion_results["postgres"]["error"] = str(e)
            logger.error(f"❌ Error deleting from database: {e}")

    # Determine success
    db_success = deletion_results["postgres"].get("success", False)
    all_operations_succeeded = db_success and (deletion_results["file_search"].get("success", False) or deletion_results["gemini"].get("success", False) or table_name == "gemini_only")

    if all_operations_succeeded:
        logger.info(f"✅ File {original_filename} completely removed from all locations")
        return {
            "success": True,
            "message": f"File deleted successfully",
            "details": deletion_results
        }
    else:
        logger.error(f"❌ Could not delete {original_filename} completely")
        return {
            "success": False,
            "message": f"File deletion incomplete",
            "details": deletion_results,
            "error": "Some deletions failed"
        }
