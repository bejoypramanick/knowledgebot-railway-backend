"""
File Processing Service for Celery Worker
Contains ALL file processing logic moved from knowledgebase_ingestion
Handles: validation, Kreuzberg extraction, pgvector ingestion, metadata recording, deletion
"""

import asyncio
import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from fastapi import HTTPException

from shared.otel_logger import get_otel_logger
from shared.kb_quota_service import kb_quota_service
from shared.tenant_context import get_current_tenant_id
from core.config import settings
from shared.kreuzberg_integration import (
    process_with_kreuzberg,
    should_use_kreuzberg_for_file,
    create_markdown_temp_file,
)
from shared.chunking_service import chunking_service
from shared.sqlalchemy_db import get_db_session
from shared.file_metrics import calculate_metrics

from shared.upload_validation import UploadValidationInput
from utils.validation import sanitize_filename, detect_mime_type_from_extension
from utils.files import calculate_sha256
from service.file_service import FileService
from shared.s3_file_storage import s3_file_storage

logger = get_otel_logger("processing_service", "celery-file-worker")


async def process_file_content(
    file_id: str, user_email: str = "admin", celery_task_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete file processing pipeline:
    1. Query database for file details
    2. Download from S3
    3. Validation (extension, MIME, size, duplicates)
    4. Format conversion (HTML→Markdown, PDF→Markdown via Kreuzberg)
    5. Chunking, embeddings, and pgvector ingestion
    6. Database record creation
    7. Delete from S3

    Called directly from Celery task.
    """
    file_service = FileService()
    start_time = time.perf_counter()
    tmp_path = None
    markdown_tmp_path = None

    # Initialize Kreuzberg tracking variables
    processed_by_extractor = False
    extractor_processing_time_ms = 0
    extractor_images_extracted = 0
    extractor_images_with_ocr = 0
    original_file_extension = None
    original_mime_type = None
    char_count = 0
    total_pages = 0
    semantic_chunks = []
    processed_content_s3_key = None

    async def get_file_details_by_task_id(
        celery_task_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Query database to get file details using celery_task_id with Tenacity retry."""
        from dao.fileupload_dao import FileUploadDAO
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
            reraise=True,
        )
        async def _query_file_details() -> Optional[Dict[str, Any]]:
            dao = FileUploadDAO()
            record = await dao.get_file_by_task_id(celery_task_id)
            if record:
                logger.info(
                    f"✅ [DB_QUERY_SUCCESS] Found file record for task_id: {celery_task_id}"
                )
                logger.info(f"   File ID: {record['id']}, S3 Key: {record['s3_key']}")
                return {
                    "file_id": str(record["id"]),
                    "original_filename": record["original_filename"],
                    "file_display_name": record["display_name"],
                    "s3_key": record["s3_key"],
                    "file_size": record["file_size"],
                }
            logger.warning(
                f"⚠️ [DB_QUERY_EMPTY] No file record found for task_id: {celery_task_id}"
            )
            return None

        try:
            return await _query_file_details()
        except Exception as e:
            logger.error(f"❌ Error querying file details by task_id: {e}")
            return None

    try:
        # Log Kreuzberg configuration at the start of processing
        from core.config import settings

        # STEP 1: Query database with file_id to get file details
        logger.info(f"🔍 [DB_QUERY] Getting file details for file_id: {file_id}")

        from dao.fileupload_dao import FileUploadDAO

        dao = FileUploadDAO()
        file_record = await dao.get_file_by_id(file_id)

        if not file_record:
            return {"success": False, "error": f"No file found for file_id: {file_id}"}

        # Extract file details from database record
        original_filename = file_record["original_filename"]
        file_display_name = file_record["display_name"]
        s3_key = file_record["s3_key"]
        file_size = file_record["file_size"]
        user_role_id = file_record["user_role_id"]
        db_mime_type = file_record.get("mime_type")
        original_sha256_hash = file_record.get(
            "sha256_hash"
        )  # Preserve original hash from upload

        logger.info(f"   Display name: {file_display_name}")
        logger.info(f"   S3 key: {s3_key}")
        logger.info(f"   Size: {file_size} bytes")
        logger.info(f"   DB MIME Type: {db_mime_type}")
        logger.info(f"   Original SHA256 Hash: {original_sha256_hash}")

        # Validate s3_key is present
        if not s3_key:
            logger.error(f"❌ [S3] No s3_key found for file_id: {file_id}")
            return {"success": False, "error": "No S3 location found for file"}

        logger.info(f"📋 [S3_KEY] Using s3_key: {s3_key}")

        logger.info(
            f"📋 [FILE_DETAILS] Retrieved: file_id={file_id}, filename={original_filename}, s3_key={s3_key}"
        )

        # No need to generate presigned URLs - kreuzberg service uses s3_key directly
        tmp_path = None

        # STEP 3: VALIDATION PHASE
        logger.info(f"🔍 [VALIDATION] Starting file validation for {original_filename}")

        # Detect MIME type first (needed for validation)
        detected_mime_type = detect_mime_type_from_extension(
            original_filename,
            provided_mime_type=db_mime_type,
        )
        logger.info(
            f"🔍 [VALIDATION] Resolved MIME type: {detected_mime_type} "
            f"(db_mime_type={db_mime_type or 'none'}) for {original_filename}"
        )

        try:
            UploadValidationInput(
                filename=original_filename,
                mime_type=detected_mime_type,
                size_bytes=file_size,
            )
        except ValueError as validation_error:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return {
                "success": False,
                "error": f"Upload validation failed: {validation_error}",
            }

        # Calculate hash (only if we have a local file)
        # If we can't recalculate it (no tmp_path), preserve the original hash from upload
        if tmp_path:
            sha256_hash = calculate_sha256(tmp_path)
            logger.info(f"✅ [HASH] Recalculated SHA256: {sha256_hash}")
        else:
            sha256_hash = original_sha256_hash
            logger.info(
                f"ℹ️  [HASH] Using original SHA256 from upload (no local file to recalculate): {sha256_hash}"
            )

        # Store original file info before any conversion
        original_file_extension = (
            original_filename.rsplit(".", 1)[-1] if "." in original_filename else ""
        )
        original_mime_type = detected_mime_type

        logger.info(
            f"🔍 [ROUTING] Resolved MIME for Kreuzberg routing: {detected_mime_type} "
            f"(db_mime_type={db_mime_type or 'none'}, s3_key={s3_key})"
        )

        # Initialize metrics variables
        content_for_upload = ""
        semantic_chunks = []
        total_pages = 0
        processed_by_extractor = False
        extractor_processing_time_ms = 0
        extractor_images_extracted = 0
        extractor_images_with_ocr = 0
        processed_content_s3_key = None
        char_count = 0

        # STEP 4: FORMAT CONVERSION PHASE
        markdown_tmp_path = None
        processed_successfully = False

        # Route all supported files to Kreuzberg (including HTML)
        if await should_use_kreuzberg_for_file(
            original_filename, detected_mime_type, file_size
        ):
            logger.info(
                f"📄 [ROUTING] Routing {original_filename} to Kreuzberg pipeline"
            )

            try:
                markdown_content, kreuzberg_metadata = await process_with_kreuzberg(
                    s3_key=s3_key,
                    original_filename=original_filename,
                    mime_type=detected_mime_type,
                    worker_type="file",
                    source_id=file_id,
                    source_name=original_filename,
                )

                if markdown_content:
                    processed_by_extractor = True
                    extractor_processing_time_ms = kreuzberg_metadata.get(
                        "processing_time_ms", 0
                    )
                    content_for_upload = markdown_content

                    semantic_chunks = kreuzberg_metadata.get("chunks") or []
                    if not semantic_chunks:
                        raise Exception("Kreuzberg returned no semantic chunks")
                    total_pages = kreuzberg_metadata.get("page_count", 0)

                    # Upload converted markdown to S3 for later download
                    md_filename = original_filename.rsplit(".", 1)[0] + ".md"
                    try:
                        md_success, md_s3_result = await s3_file_storage.upload_file(
                            file_data=content_for_upload.encode("utf-8"),
                            original_filename=md_filename,
                            file_type="processed",
                        )
                        if md_success:
                            processed_content_s3_key = md_s3_result
                            logger.info(
                                f"✅ [S3_MD_UPLOAD] Converted markdown uploaded to S3: {processed_content_s3_key}"
                            )
                    except Exception as md_upload_err:
                        logger.warning(
                            f"⚠️ [S3_MD_UPLOAD] Error uploading markdown to S3: {md_upload_err}"
                        )

                    # Create temporary Markdown file from converted content
                    tmp_path = create_markdown_temp_file(content_for_upload)
                    markdown_tmp_path = tmp_path
                    original_tmp_path = tmp_path

                    original_filename = original_filename.rsplit(".", 1)[0] + ".md"
                    detected_mime_type = "text/markdown"

                    processed_successfully = True
                else:
                    error_msg = kreuzberg_metadata.get(
                        "error", "Kreuzberg processing failed"
                    )
                    logger.error(
                        "❌ [KREUZBERG_EMPTY_EXTRACTION] Extraction returned no markdown "
                        f"for filename={original_filename} mime_type={detected_mime_type} "
                        f"s3_key={s3_key} file_id={file_id} error={error_msg}"
                    )
                    if tmp_path and os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    return {
                        "success": False,
                        "error": f"Kreuzberg processing failed: {error_msg}",
                    }
            except Exception as e:
                logger.error(
                    "❌ [KREUZBERG_PROCESSING_EXCEPTION] Kreuzberg processing raised "
                    f"for filename={original_filename} mime_type={detected_mime_type} "
                    f"s3_key={s3_key} file_id={file_id}: {e}"
                )
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return {
                    "success": False,
                    "error": f"Kreuzberg processing error: {str(e)}",
                }

        # Unsupported format (Raw file)
        else:
            # For raw files, read content if it's text-based to get metrics,
            # otherwise just record the file itself
            from core.config import settings

            if not settings.kreuzberg_enabled:
                logger.info(
                    f"📝 [ROUTING] File doesn't require Kreuzberg processing, using raw text/vector pipeline"
                )
            else:
                logger.info(
                    f"📝 [ROUTING] File type {detected_mime_type} doesn't require Kreuzberg processing, using raw text/vector pipeline"
                )

            # Read local file content for metrics if it's a text/markdown file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    is_text = detected_mime_type in [
                        "text/plain",
                        "text/markdown",
                        "text/html",
                        "application/json",
                    ]
                    if is_text or original_filename.lower().endswith(
                        (".txt", ".md", ".json", ".html")
                    ):
                        with open(
                            tmp_path, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            content_for_upload = f.read()
                            logger.info(
                                f"📝 [METRICS] Read {len(content_for_upload)} chars from raw text file"
                            )
                except Exception as e:
                    logger.warning(
                        f"⚠️ [METRICS] Could not read raw file for metrics: {e}"
                    )

            processed_successfully = True

        # STEP 6: DB VECTOR INSERTION PHASE
        # Initialize variables needed for step 7 database update
        document_name = f"vector_db_file_{file_id}"
        document_uri = f"vector_db_file_{file_id}"
        final_state = "completed"
        storage_processed_at = datetime.utcnow()

        class StorageDocument:
            def __init__(self, name, uri):
                self.name = name
                self.uri = uri

        uploaded_file = StorageDocument(document_name, document_uri)
        storage_metadata = {
            "type": "vector_db",
            "document_name": document_name,
            "uploaded_at": storage_processed_at.isoformat(),
        }

        if processed_successfully or detected_mime_type == "text/markdown":
            logger.info(
                f"🤖 [VECTOR_DB] Uploading chunks to pgvector - Original: {original_filename}..."
            )
            try:
                # Only apply local chunking for raw non-Kreuzberg text inputs.
                if (
                    not semantic_chunks
                    and content_for_upload
                    and not processed_by_extractor
                ):
                    logger.info(
                        f"🧩 [CHUNKING] No chunks found, applying Chonkie to content_for_upload..."
                    )
                    semantic_chunks = await chunking_service.chunk_text(
                        content_for_upload, original_filename
                    )

                from shared.vector_dao import vector_dao

                chunks_to_insert = semantic_chunks

                if chunks_to_insert:
                    # Calculate content size for quota check
                    content_bytes = sum(
                        len(c.get("text") or c.get("content", ""))
                        for c in chunks_to_insert
                    )
                    tenant_id = get_current_tenant_id()
                    if tenant_id:
                        logger.info(
                            f"📊 [QUOTA_CHECK] Checking quota before embedding: content_bytes={content_bytes}"
                        )
                        try:
                            await kb_quota_service.check_quota_before_embedding(
                                tenant_id, content_bytes, f"File '{original_filename}'"
                            )
                        except HTTPException:
                            raise
                        except Exception as e:
                            logger.error(f"❌ [QUOTA_CHECK] Error checking quota: {e}")
                            raise

                    # Generate embeddings using our model-agnostic utility
                    logger.info(
                        f"🧬 Generating embeddings for {len(chunks_to_insert)} file chunks..."
                    )
                    from shared.embeddings import batch_generate_embeddings

                    chunk_texts = [
                        c.get("text") or c.get("content", "") for c in chunks_to_insert
                    ]
                    embeddings = await batch_generate_embeddings(chunk_texts)

                    # Attach embeddings to chunks
                    for i, embedding in enumerate(embeddings):
                        if i < len(chunks_to_insert):
                            chunks_to_insert[i]["embedding"] = embedding

                    success = await vector_dao.batch_insert_chunks(
                        chunks=chunks_to_insert,
                        document_id=file_id,
                        document_type="file",
                    )
                    if not success:
                        logger.warning(
                            f"⚠️ Chunk batch insert failed for file {file_id}"
                        )
                        final_state = "failed"
                    else:
                        logger.info(
                            f"✅ Uploaded {len(chunks_to_insert)} chunks with OpenAI embeddings to vector DB"
                        )
                else:
                    raise Exception(f"No chunks produced for file {file_id}")

                semantic_chunks = []

            except Exception as e:
                logger.error(f"❌ [VECTOR_DB] Error uploading chunks: {e}")
                raise

            # STEP 7: DATABASE UPDATE PHASE
            try:
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    try:
                        with open(markdown_tmp_path, "r", encoding="utf-8") as f:
                            markdown_file_content = f.read()
                        char_count = len(markdown_file_content)
                        logger.info(
                            f"📊 [METRICS] Calculated for {original_filename}: {char_count:,} characters from markdown"
                        )
                    except Exception as me:
                        logger.warning(
                            f"⚠️ Could not calculate char_count from markdown: {me}"
                        )

                # Use the new DAO to update file record with ALL processing data
                from dao.fileupload_dao import FileUploadDAO

                dao = FileUploadDAO()

                current_tenant_id = get_current_tenant_id()
                if current_tenant_id:
                    summary = await kb_quota_service.get_tenant_quota_summary(
                        current_tenant_id
                    )
                    await (
                        kb_quota_service.fail_if_tenant_quota_breached_after_processing(
                            current_tenant_id,
                            summary["used_bytes"] + char_count,
                            "This file upload",
                        )
                    )

                # First update status to processing
                await dao.update_file_status(file_id, "processing")

                # Extract document URI if available
                document_uri = None
                if hasattr(uploaded_file, "uri"):
                    document_uri = uploaded_file.uri

                # Update with all processing data
                extractor_details = (
                    kreuzberg_metadata.get("kreuzberg_metadata", {})
                    if processed_by_extractor
                    else {}
                )
                success = await dao.update_file_with_processing_data(
                    file_id=file_id,
                    storage_document_name=document_name,
                    storage_document_uri=document_uri,
                    storage_backend_state=final_state,
                    file_size=file_size,
                    char_count=char_count,
                    sha256_hash=sha256_hash,
                    metadata={
                        "type": "vector_db",
                        "grounding_source": "pgvector",
                        "retrieval_pipeline": "kreuzberg_rust -> pgvector",
                        "document_name": document_name,
                        "uploaded_at": storage_processed_at.isoformat()
                        if storage_processed_at
                        else None,
                        "markdown_s3_key": extractor_details.get("markdown_s3_key"),
                        "chunks_s3_key": extractor_details.get("chunks_s3_key"),
                        "tables_s3_key": extractor_details.get("tables_s3_key"),
                        "page_count": extractor_details.get("page_count", total_pages),
                        "table_count": extractor_details.get("table_count", 0),
                    },
                    processed_by_extractor=processed_by_extractor,
                    extractor_processing_time_ms=extractor_processing_time_ms,
                    extractor_images_extracted=extractor_images_extracted,
                    extractor_images_with_ocr=extractor_images_with_ocr,
                    original_file_extension=original_file_extension,
                    original_mime_type=original_mime_type,
                    processed_content_s3_key=processed_content_s3_key,
                    total_pages=total_pages,
                )

                if not success:
                    logger.error(
                        f"❌ [DB_ERROR] Failed to update file record for {original_filename}"
                    )
                    logger.error(
                        f"❌ [DB_ERROR] All variables: file_id={file_id}, document_name={document_name}, document_uri={document_uri}"
                    )
                    raise Exception("Database update failed - file orphaned in Gemini")

                logger.info(
                    f"✅ [DB_UPDATE] Updated file record with all processing data, File ID: {file_id}"
                )

                logger.info(
                    f"🧹 [S3_CLEANUP] Cleaning up S3 files after successful vector ingestion"
                )

                # Delete raw upload file (no longer needed)
                if s3_key:
                    try:
                        deleted_raw = await s3_file_storage.delete_file(s3_key)
                        if deleted_raw:
                            logger.info(
                                f"✅ [S3_CLEANUP] Deleted raw file from S3: {s3_key}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ [S3_CLEANUP] Failed to delete raw file from S3: {s3_key}"
                            )
                    except Exception as s3_cleanup_error:
                        logger.warning(
                            f"⚠️ [S3_CLEANUP] Error deleting raw file from S3: {s3_cleanup_error}"
                        )

                retain_md_file = os.getenv("RETAIN_MD_FILE", "false").lower() == "true"

                if processed_content_s3_key:
                    if retain_md_file:
                        logger.info(
                            f"📁 [MD_RETENTION] Retaining processed markdown in S3: {processed_content_s3_key}"
                        )
                        logger.info(
                            f"   RETAIN_MD_FILE=true - file will be available as attachment"
                        )
                    else:
                        try:
                            deleted_processed = await s3_file_storage.delete_file(
                                processed_content_s3_key
                            )
                            if deleted_processed:
                                logger.info(
                                    f"✅ [S3_CLEANUP] Deleted processed markdown from S3: {processed_content_s3_key}"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ [S3_CLEANUP] Failed to delete processed markdown from S3: {processed_content_s3_key}"
                                )
                        except Exception as s3_cleanup_error:
                            logger.warning(
                                f"⚠️ [S3_CLEANUP] Error deleting processed markdown from S3: {s3_cleanup_error}"
                            )

                logger.info(f"✅ [S3_CLEANUP] S3 cleanup completed")

                # Delete temporary local files
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    os.unlink(markdown_tmp_path)
                logger.info(f"✅ [CLEANUP] Cleaned up temporary local files")

                processing_time = time.perf_counter() - start_time
                logger.info(
                    f"✅ [SUCCESS] File processing completed: {original_filename}"
                )
                logger.info(f"   📁 Vector Document: {document_name}")
                logger.info(f"   🗄️  Database ID: {file_id}")
                logger.info(f"   ⏱️  Time: {processing_time:.2f}s")
                logger.info(f"   📊 Size: {file_size} bytes")
                logger.info(f"   📝 Char Count: {char_count:,}")
                logger.info(f"   🔧 Kreuzberg: {processed_by_extractor}")
                if processed_by_extractor:
                    logger.info(
                        f"   ⏱️  Kreuzberg Time: {extractor_processing_time_ms}ms"
                    )
                logger.info(f"   🔐 Hash: {sha256_hash}")

                return {
                    "success": True,
                    "file_id": str(file_id),
                    "status": final_state,
                    "processing_time_seconds": processing_time,
                    "vector_document_name": document_name,
                    "original_filename": original_filename,
                    "file_display_name": file_display_name,
                    "file_size": file_size,
                    "mime_type": detected_mime_type,
                    "sha256_hash": sha256_hash,
                    "char_count": char_count,
                    "processed_by_extractor": processed_by_extractor,
                }

            except Exception as e:
                logger.error(
                    f"❌ [PROCESSING_ERROR] Error processing file {original_filename}: {e}"
                )

                # Update status to failed in database
                if file_id:
                    try:
                        from dao.fileupload_dao import FileUploadDAO

                        dao = FileUploadDAO()
                        await dao.update_file_status(
                            file_id, "failed", error_message=str(e)
                        )
                        logger.info(f"✅ [DB_UPDATE] Updated file status to 'failed'")
                    except Exception as db_error:
                        logger.error(
                            f"❌ [DB_ERROR] Failed to update status to 'failed': {db_error}"
                        )

                # Cleanup on failure
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if markdown_tmp_path and os.path.exists(markdown_tmp_path):
                    os.unlink(markdown_tmp_path)

                return {
                    "success": False,
                    "error": f"Processing error: {str(e)}",
                    "celery_task_id": celery_task_id,
                }

    except Exception as e:
        logger.error(f"❌ Error processing file {original_filename}: {e}")

        # FAILURE: Log error (no Redis publish - UI will see DB updates)
        logger.info(
            f"🧹 [CLEANUP] Cleaning up S3 and temp files for {original_filename}"
        )

        # Delete from S3
        try:
            deleted = await s3_file_storage.delete_file(s3_key)
            if deleted:
                logger.info(f"✅ [S3] Deleted file from S3: {s3_key}")
            else:
                logger.warning(
                    f"⚠️ [S3] Failed to delete from S3, but processing succeeded: {s3_key}"
                )
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
    """Delete a file record and clear worker-owned database state."""
    if not file_id:
        return {"success": False, "error": "file_id is required"}

    file_service = FileService()

    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")

    table_name = "storage_only"
    original_filename = "storage-only file"

    if not file_id.startswith("files/"):
        # Look up in DB
        try:
            from dao.fileupload_dao import FileUploadDAO

            dao = FileUploadDAO()
            record = await dao.get_file_metadata_for_deletion(file_id)

            if record:
                original_filename = record.get("original_filename", "Unknown")
                table_name = "file_uploads"
            else:
                logger.error(f"❌ [DELETE] File not found in database: {file_id}")
                return {"success": False, "error": "File not found"}
        except Exception as e:
            logger.error(f"❌ [DELETE] Error looking up file record: {e}")
            return {"success": False, "error": str(e)}

    deletion_results = {
        "storage": {"success": True, "error": None},
        "postgres": {"success": False, "error": None},
    }

    # Delete from database
    if table_name != "storage_only":
        try:
            async with get_db_session() as session:
                await file_service.delete_file_record(file_id, table_name)
                await session.commit()
                deletion_results["postgres"]["success"] = True
                logger.info(f"✅ Deleted from {table_name}: ID={file_id}")
        except Exception as e:
            deletion_results["postgres"]["error"] = str(e)
            logger.error(f"❌ Error deleting from database: {e}")

    # Determine success
    db_success = deletion_results["postgres"].get("success", False)
    all_operations_succeeded = db_success and deletion_results["storage"].get(
        "success", False
    )

    # SUCCESS: Log completion (no Redis publish - UI will see DB updates)
    if all_operations_succeeded:
        logger.info(
            f"✅ File {original_filename} completely removed from all locations"
        )
        return {
            "success": True,
            "message": f"File deleted successfully",
            "details": deletion_results,
        }
    else:
        logger.error(f"❌ Could not delete {original_filename} completely")
        return {
            "success": False,
            "message": f"File deletion incomplete",
            "details": deletion_results,
            "error": "Some deletions failed",
        }
