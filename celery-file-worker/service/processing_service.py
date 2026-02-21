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
from core.ai import get_genai_client
from core.config import settings
from shared.docling_integration import (
    process_with_docling,
    should_use_docling_for_file,
    create_markdown_temp_file
)
from shared.file_search import get_file_search_store_by_display_name
from shared.html_processor import extract_content_from_html
from shared.db import get_db_connection
from shared.file_metrics import calculate_metrics

from utils.validation import (
    validate_file_extension,
    validate_file_size,
    validate_mime_type,
    sanitize_filename,
    detect_mime_type_from_extension
)
from utils.files import calculate_sha256, stream_to_temp_file
from service.file_service import FileService

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
    file_id: int,
    user_email: str = "admin",
    celery_task_id: str = None
) -> Dict[str, Any]:
    """
    Complete file processing pipeline:
    1. Query database for file details
    2. Download from S3
    3. Validation (extension, MIME, size, duplicates)
    4. Format conversion (HTML→Markdown, PDF→Markdown via Docling)
    4. Gemini upload
    5. Database record creation
    6. Delete from S3

    Called directly from Celery task.
    """
    file_service = FileService()
    start_time = time.perf_counter()
    tmp_path = None
    markdown_tmp_path = None
    
    # Initialize Docling tracking variables
    processed_by_docling = False
    docling_processing_time_ms = None
    docling_images_extracted = 0
    docling_images_with_ocr = 0
    original_file_extension = None
    original_mime_type = None
    char_count = 0

    async def get_file_details_by_task_id(celery_task_id: str) -> Optional[Dict[str, Any]]:
        """Query database to get file details using celery_task_id"""
        try:
            from shared.db import get_db_connection
            
            # Add retry logic for database connection issues
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with get_db_connection() as conn:
                        record = await conn.fetchrow(
                            "SELECT id, original_filename, display_name, s3_key, file_size "
                            "FROM file_uploads WHERE celery_task_id = $1",
                            celery_task_id
                        )
                        if record:
                            logger.info(f"✅ [DB_QUERY_SUCCESS] Found file record for task_id: {celery_task_id}")
                            logger.info(f"   File ID: {record['id']}, S3 Key: {record['s3_key']}")
                            return {
                                "file_id": str(record["id"]),
                                "original_filename": record["original_filename"],
                                "file_display_name": record["display_name"],
                                "s3_key": record["s3_key"],
                                "file_size": record["file_size"]
                            }
                        logger.warning(f"⚠️ [DB_QUERY_EMPTY] No file record found for task_id: {celery_task_id}")
                        return None
                except Exception as conn_err:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ [DB_RETRY] Connection error (attempt {attempt + 1}/{max_retries}): {conn_err}")
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        raise
        except Exception as e:
            logger.error(f"❌ Error querying file details by task_id: {e}")
            return None

    try:
        # Log docling configuration at the start of processing
        from core.config import settings
        logger.info(f"⚙️  [CONFIG] DOCLING_ENABLED={settings.docling_enabled}")

        # STEP 1: Query database with file_id to get file details
        logger.info(f"🔍 [DB_QUERY] Getting file details for file_id: {file_id}")
        
        from shared.db import get_db_connection
        
        async with get_db_connection() as conn:
            file_record = await conn.fetchrow("""
                SELECT id, user_role_id, original_filename, display_name, 
                       s3_key, file_size, mime_type, processing_status
                FROM file_uploads 
                WHERE id = $1
            """, file_id)
        
        if not file_record:
            logger.error(f"❌ [DB_QUERY] No file found for file_id: {file_id}")
            return {
                "success": False,
                "error": f"No file found for file_id: {file_id}"
            }
        
        # Extract file details from database record
        original_filename = file_record['original_filename']
        file_display_name = file_record['display_name']
        s3_key = file_record['s3_key']
        file_size = file_record['file_size']
        user_role_id = file_record['user_role_id']
        
        logger.info(f"✅ [DB_QUERY] File found: {original_filename}")
        logger.info(f"   Display name: {file_display_name}")
        logger.info(f"   S3 key: {s3_key}")
        logger.info(f"   Size: {file_size} bytes")
        
        # Validate s3_key is present
        if not s3_key:
            logger.error(f"❌ [S3] No s3_key found for file_id: {file_id}")
            return {
                "success": False,
                "error": "No S3 location found for file"
            }
        
        logger.info(f"📋 [S3_KEY] Using s3_key: {s3_key}")
        
        logger.info(f"📋 [FILE_DETAILS] Retrieved: file_id={file_id}, filename={original_filename}, s3_key={s3_key}")

        # STEP 2: GENERATE PRESIGNED URL (instead of downloading)
        logger.info(f"� [S3] Generating presigned URL for S3 object: {s3_key}")
        from shared.s3_file_storage import s3_file_storage

        success, result = s3_file_storage.generate_presigned_url(s3_key, expiration=3600)
        if not success:
            logger.error(f"❌ [S3] Failed to generate presigned URL: {result}")
            return {
                "success": False,
                "error": f"Failed to generate presigned URL: {result}"
            }

        presigned_url = result
        logger.info(f"✅ [S3] Generated presigned URL for {s3_key}")
        logger.info(f"🔍 [DEBUG] presigned_url type: {type(presigned_url)}")
        logger.info(f"🔍 [DEBUG] presigned_url length: {len(presigned_url) if presigned_url else 'None'}")
        logger.info(f"🔍 [DEBUG] presigned_url starts with http: {presigned_url.startswith('http') if presigned_url else 'None'}")

        # No need to create temp files - docling service will download directly
        tmp_path = None  # Not used with presigned URL approach

        # STEP 3: VALIDATION PHASE
        logger.info(f"🔍 [VALIDATION] Starting file validation for {original_filename}")

        # Detect MIME type first (needed for validation)
        detected_mime_type = detect_mime_type_from_extension(original_filename)
        logger.info(f"🔍 [VALIDATION] Detected MIME type: {detected_mime_type} for {original_filename}")

        # Validate file extension
        ext_valid, ext_error = validate_file_extension(original_filename)
        if not ext_valid:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return {
                "error": f"Extension validation failed: {ext_error}"
            }

        # Validate MIME type
        mime_valid, mime_error = validate_mime_type(detected_mime_type, original_filename)
        if not mime_valid:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return {
                "success": False,
                "error": f"Invalid MIME type: {mime_error}"
            }

        # Validate file size
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return {
                "success": False,
                "error": f"Size validation failed: {size_error}"
            }

        # Calculate hash
        sha256_hash = calculate_sha256(tmp_path)
        
        # Store original file info before any conversion
        original_file_extension = original_filename.rsplit('.', 1)[-1] if '.' in original_filename else ''
        original_mime_type = detected_mime_type
        
        logger.info(f"🔍 [ROUTING] Detected MIME: {detected_mime_type} for {original_filename}")

        # STEP 4: FORMAT CONVERSION PHASE - Use Docling for all supported formats
        markdown_tmp_path = None
        processed_successfully = False

        # Route all supported files to Docling (including HTML)
        if await should_use_docling_for_file(original_filename, detected_mime_type, file_size):
            logger.info(f"📄 [ROUTING] Routing {original_filename} to Docling pipeline")
            
            try:
                logger.info(f"🔍 [DEBUG] About to call process_with_docling with presigned_url: {presigned_url}")
                markdown_content, docling_metadata = await process_with_docling(
                    presigned_url=presigned_url  # Use presigned URL only
                )
                logger.info(f"🔍 [DEBUG] process_with_docling returned: markdown_content={bool(markdown_content)}, metadata_keys={list(docling_metadata.keys()) if docling_metadata else 'None'}")

                if markdown_content:
                    # Capture Docling metadata
                    processed_by_docling = True
                    docling_processing_time_ms = docling_metadata.get('processing_time_ms', 0)
                    docling_images_extracted = docling_metadata.get('images_extracted', 0)
                    docling_images_with_ocr = docling_metadata.get('images_with_ocr', 0)
                    
                    logger.info(f"📊 [DOCLING_METADATA] Processing time: {docling_processing_time_ms}ms, "
                              f"Images: {docling_images_extracted}, OCR: {docling_images_with_ocr}")
                    
                    markdown_tmp_path = create_markdown_temp_file(markdown_content)
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
                    return {
                        "success": False,
                        "error": f"Docling processing failed: {error_msg}"
                    }
            except Exception as e:
                logger.error(f"❌ [DOCLING] Unexpected error: {e}")
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return {
                    "success": False,
                    "error": f"Docling processing error: {str(e)}"
                }

        # Unsupported format
        else:
            # Mark as processed successfully and send file raw to Gemini API
            from core.config import settings
            if not settings.docling_enabled:
                logger.info(f"📝 [ROUTING] DOCLING_ENABLED=false, sending {original_filename} raw to Gemini API")
            else:
                logger.info(f"📝 [ROUTING] File type {detected_mime_type} doesn't require docling processing, sending raw to Gemini API")
            processed_successfully = True

        # STEP 6: GEMINI UPLOAD PHASE
        if processed_successfully or detected_mime_type == 'text/markdown':
            logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {file_display_name}, Original: {original_filename}, MIME: {detected_mime_type}...")
            try:
                from core.ai import get_genai_client
                genai_client = get_genai_client()
                if not genai_client:
                    logger.error("❌ Gemini client not available")
                    raise Exception("Gemini client not configured")

                # Detect proper MIME type - use magic bytes from file path
                final_mime_type = detect_mime_type_from_extension(original_filename, detected_mime_type, tmp_path)

                # Create display name
                if file_display_name != original_filename:
                    gemini_display_name = f"{file_display_name} | {original_filename}"
                else:
                    gemini_display_name = original_filename

                logger.info(f"📦 Looking up FileSearch store: {settings.gemini_file_search_store_name}")

                # Look up store by display name
                from shared.file_search import get_file_search_store_by_display_name
                file_search_store_name = get_file_search_store_by_display_name(
                    genai_client,
                    display_name=settings.gemini_file_search_store_name
                )

                if not file_search_store_name:
                    logger.error(f"❌ FileSearch store '{settings.gemini_file_search_store_name}' not found")
                    raise Exception(f"FileSearch store '{settings.gemini_file_search_store_name}' not found")

                logger.info(f"✅ Found store: {file_search_store_name}")

                logger.info(f"📤 Uploading to FileSearch store: {file_search_store_name}")
                
                # Build config with mime_type inside (like web worker does)
                upload_config = {
                    'display_name': gemini_display_name,
                    'custom_metadata': [
                        {'key': 'original_filename', 'string_value': original_filename},
                        {'key': 'user_email', 'string_value': user_email or 'admin'},
                        {'key': 'celery_task_id', 'string_value': celery_task_id}
                    ]
                }
                
                # Explicitly set MIME type for markdown files (inside config, like web worker)
                if detected_mime_type == 'text/markdown' or tmp_path.endswith('.md'):
                    upload_config['mime_type'] = 'text/markdown'
                    logger.info(f"📝 [MIME] Explicitly setting mime_type='text/markdown' for {original_filename}")
                
                operation = genai_client.file_search_stores.upload_to_file_search_store(
                    file=tmp_path,
                    file_search_store_name=file_search_store_name,
                    config=upload_config
                )

                if not operation:
                    logger.error(f"❌ [GEMINI] Failed to create upload operation")
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
                    logger.info(f"� [METADATA] Stored FileSearch info: store={file_search_store_name}, document={document_name}")
                else:
                    logger.error(f"❌ [GEMINI] Upload failed - no document_name in response: {operation}")
                    raise Exception("FileSearch upload failed - no document returned")

            except Exception as e:
                logger.error(f"❌ [GEMINI] Error uploading to FileSearch: {e}")
                raise

            # STEP 7: DATABASE UPDATE PHASE
            try:
                # Calculate char_count from markdown content
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    try:
                        with open(markdown_tmp_path, 'r', encoding='utf-8') as f:
                            markdown_content = f.read()
                        char_count = len(markdown_content)
                        logger.info(f"📊 [METRICS] Calculated for {original_filename}: {char_count:,} characters")
                    except Exception as me:
                        logger.warning(f"⚠️ Could not calculate char_count from markdown: {me}")

                # Use the new DAO to update file record with ALL processing data
                from dao.fileupload_dao import FileUploadDAO
                dao = FileUploadDAO()
                
                # First update status to processing
                await dao.update_file_status(int(file_id), 'processing')
                
                # Extract document URI if available
                document_uri = None
                if hasattr(uploaded_file, 'uri'):
                    document_uri = uploaded_file.uri
                
                # Update with all processing data
                success = await dao.update_file_with_processing_data(
                    file_id=int(file_id),
                    gemini_file_name=document_name,
                    gemini_file_uri=document_uri,
                    gemini_state=final_state,
                    file_size=file_size,
                    char_count=char_count,
                    sha256_hash=sha256_hash,
                    metadata={
                        'type': 'file_search',
                        'file_search_store_name': file_search_store_name,
                        'document_name': document_name,
                        'uploaded_at': gemini_processed_at.isoformat() if gemini_processed_at else None
                    },
                    processed_by_docling=processed_by_docling,
                    docling_processing_time_ms=docling_processing_time_ms,
                    docling_images_extracted=docling_images_extracted,
                    docling_images_with_ocr=docling_images_with_ocr,
                    original_file_extension=original_file_extension,
                    original_mime_type=original_mime_type
                )

                if not success:
                    logger.error(f"❌ [DB_ERROR] Failed to update file record for {original_filename}")
                    raise Exception("Database update failed - file orphaned in Gemini")

                logger.info(f"✅ [DB_UPDATE] Updated file record with all processing data, File ID: {file_id}")

                # STEP 8: S3 CLEANUP PHASE
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    os.unlink(markdown_tmp_path)

                processing_time = time.perf_counter() - start_time
                logger.info(f"✅ [SUCCESS] File processing completed: {original_filename}")
                logger.info(f"   📁 Gemini Document: {document_name}")
                logger.info(f"   🗄️  Database ID: {file_id}")
                logger.info(f"   ⏱️  Time: {processing_time:.2f}s")
                logger.info(f"   📊 Size: {file_size} bytes")
                logger.info(f"   📝 Char Count: {char_count:,}")
                logger.info(f"   🔧 Docling: {processed_by_docling}")
                if processed_by_docling:
                    logger.info(f"   ⏱️  Docling Time: {docling_processing_time_ms}ms")
                    logger.info(f"   🖼️  Images: {docling_images_extracted} (OCR: {docling_images_with_ocr})")
                logger.info(f"   🔐 Hash: {sha256_hash}")

                return {
                    "success": True,
                    "file_id": str(file_id),
                    "status": final_state,
                    "processing_time_seconds": processing_time,
                    "gemini_document_name": document_name,
                    "original_filename": original_filename,
                    "file_display_name": file_display_name,
                    "file_size": file_size,
                    "mime_type": detected_mime_type,
                    "sha256_hash": sha256_hash,
                    "char_count": char_count,
                    "processed_by_docling": processed_by_docling
                }

            except Exception as e:
                logger.error(f"❌ [PROCESSING_ERROR] Error processing file {original_filename}: {e}")
                
                # Update status to failed in database
                if file_id:
                    try:
                        from dao.fileupload_dao import FileUploadDAO
                        dao = FileUploadDAO()
                        await dao.update_file_status(int(file_id), 'failed', error_message=str(e))
                        logger.info(f"✅ [DB_UPDATE] Updated file status to 'failed'")
                    except Exception as db_error:
                        logger.error(f"❌ [DB_ERROR] Failed to update status to 'failed': {db_error}")

                # Cleanup on failure
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    os.unlink(markdown_tmp_path)

                return {
                    "success": False,
                    "error": f"Processing error: {str(e)}",
                    "celery_task_id": celery_task_id
                }

    except Exception as e:
        logger.error(f"❌ Error processing file {original_filename}: {e}")

        # FAILURE: Log error (no Redis publish - UI will see DB updates)
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
                    # Use force=True to delete document with all its parts/chunks
                    genai_client.file_search_stores.documents.delete(
                        name=document_name,
                        config={"force": True}
                    )
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

    # SUCCESS: Log completion (no Redis publish - UI will see DB updates)
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
