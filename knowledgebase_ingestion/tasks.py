"""
Celery tasks for knowledgebase ingestion service
Handles async file processing with database status tracking
"""

import asyncio
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

from celery import shared_task
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_tasks", "knowledgebase-ingestion")


async def update_file_processing_status(file_id: int, status: str, error_message: str = None):
    """Update file processing status in database"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            if error_message:
                await conn.execute(
                    "UPDATE file_uploads SET processing_status = $1, error_message = $2, updated_at = NOW() WHERE id = $3",
                    status, error_message, file_id
                )
            else:
                await conn.execute(
                    "UPDATE file_uploads SET processing_status = $1, error_message = NULL, updated_at = NOW() WHERE id = $2",
                    status, file_id
                )
            logger.info(f"✅ Updated file_uploads ID {file_id} status to: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update file processing status for ID {file_id}: {e}")


async def process_file_async(
    file_id: int,
    tmp_path: str,
    original_filename: str,
    file_display_name: str,
    detected_mime_type: str,
    user_email: str,
    file_size: int,
    sha256_hash: str
):
    """
    Async file processing logic
    Handles HTML, Docling (PDF/DOCX), and text files
    """
    try:
        await update_file_processing_status(file_id, "processing")

        logger.info(f"🔄 [CELERY] Starting processing for file ID {file_id}: {original_filename}")

        from knowledgebase_ingestion.service.ingestion_service import (
            process_with_gemini
        )
        from knowledgebase_ingestion.service.docling_integration import (
            process_with_docling,
            should_use_docling_for_file,
            create_markdown_temp_file
        )
        from shared.html_processor import extract_content_from_html

        markdown_tmp_path = None
        docling_metadata = {}

        # 1. Route HTML files
        if detected_mime_type == 'text/html' or original_filename.lower().endswith(('.html', '.htm')):
            logger.info(f"🌐 [CELERY] Processing HTML file: {original_filename}")
            try:
                markdown_content, html_metadata = extract_content_from_html(tmp_path)

                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    logger.info(f"✅ [HTML] Extracted content")
                else:
                    error_msg = html_metadata.get("error", "HTML extraction failed")
                    logger.error(f"❌ [HTML] Failed: {error_msg}")
                    await update_file_processing_status(file_id, "failed", error_msg)
                    return
            except Exception as e:
                logger.error(f"❌ [HTML] Error: {e}")
                await update_file_processing_status(file_id, "failed", str(e))
                return

        # 2. Route Docling files
        elif await should_use_docling_for_file(original_filename, detected_mime_type, file_size):
            logger.info(f"📄 [CELERY] Processing with Docling: {original_filename}")
            try:
                markdown_content, docling_metadata = await process_with_docling(
                    tmp_path,
                    original_filename,
                    detected_mime_type
                )

                if markdown_content:
                    markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                    tmp_path = markdown_tmp_path
                    original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                    detected_mime_type = 'text/markdown'
                    logger.info(f"✅ [DOCLING] Converted to markdown")
                else:
                    error_msg = docling_metadata.get("error", "Docling processing failed")
                    logger.error(f"❌ [DOCLING] Failed: {error_msg}")
                    await update_file_processing_status(file_id, "failed", error_msg)
                    return
            except Exception as e:
                logger.error(f"❌ [DOCLING] Error: {e}")
                await update_file_processing_status(file_id, "failed", str(e))
                return

        # 3. Upload to Gemini
        logger.info(f"🚀 [CELERY] Uploading to Gemini for file ID {file_id}")
        try:
            uploaded_file, final_state, gemini_processed_at, file_search_metadata = await process_with_gemini(
                tmp_path, file_display_name, original_filename, detected_mime_type, user_email
            )

            if final_state != "ACTIVE":
                error_msg = f"Gemini upload failed - state: {final_state}"
                logger.error(f"❌ [GEMINI] {error_msg}")
                await update_file_processing_status(file_id, "failed", error_msg)
                return

            # 4. Update database with Gemini results
            from shared.db import get_db_connection

            metadata_json = json.dumps(file_search_metadata or {})

            async with get_db_connection() as conn:
                await conn.execute(
                    """UPDATE file_uploads SET
                       gemini_file_name = $1,
                       gemini_file_uri = $2,
                       gemini_state = $3,
                       metadata = $4::jsonb,
                       processing_status = $5,
                       error_message = NULL,
                       updated_at = NOW()
                       WHERE id = $6""",
                    uploaded_file.name,
                    getattr(uploaded_file, 'uri', None),
                    final_state,
                    metadata_json,
                    "completed",
                    file_id
                )

            logger.info(f"✅ [CELERY] File ID {file_id} processing completed successfully")

        except Exception as e:
            error_msg = f"Gemini processing error: {str(e)}"
            logger.error(f"❌ [GEMINI] {error_msg}")
            await update_file_processing_status(file_id, "failed", error_msg)
            return

    except Exception as e:
        logger.error(f"❌ [CELERY] Unexpected error for file ID {file_id}: {e}")
        await update_file_processing_status(file_id, "failed", str(e))
    finally:
        # Cleanup temp files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass


@shared_task(bind=True, max_retries=2)
def process_file_upload_task(
    self,
    file_id: int,
    tmp_path: str,
    original_filename: str,
    file_display_name: str,
    detected_mime_type: str,
    user_email: str,
    file_size: int,
    sha256_hash: str
):
    """
    Celery task for async file processing
    Retries up to 2 times on failure
    """
    try:
        logger.info(f"📋 [TASK] Starting Celery task for file ID {file_id}")

        # Run async function in event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            process_file_async(
                file_id=file_id,
                tmp_path=tmp_path,
                original_filename=original_filename,
                file_display_name=file_display_name,
                detected_mime_type=detected_mime_type,
                user_email=user_email,
                file_size=file_size,
                sha256_hash=sha256_hash
            )
        )

        logger.info(f"✅ [TASK] Celery task completed for file ID {file_id}")

    except Exception as e:
        logger.error(f"❌ [TASK] Error in Celery task for file ID {file_id}: {e}")

        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception as retry_error:
            logger.error(f"❌ [TASK] Max retries exceeded for file ID {file_id}: {retry_error}")
            # Update status to failed after max retries
            loop = asyncio.get_event_loop()
            loop.run_until_complete(
                update_file_processing_status(file_id, "failed", f"Processing failed after retries: {str(e)}")
            )
