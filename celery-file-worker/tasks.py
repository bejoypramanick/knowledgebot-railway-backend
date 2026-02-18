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


async def is_task_cancelled(celery_task_id: str) -> bool:
    """Check if task has been marked for cancellation via Redis"""
    if not celery_task_id:
        return False

    try:
        import redis as redis_lib
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        redis_conn = redis_lib.from_url(redis_url)

        cancelled_key = f"task_cancelled:{celery_task_id}"
        result = redis_conn.exists(cancelled_key)
        redis_conn.close()

        return bool(result)
    except Exception as e:
        logger.warning(f"⚠️ Error checking cancellation status: {e}")
        return False


async def update_file_processing_status(file_id: int, status: str, error_message: str = None):
    """Update file processing status using service layer"""
    try:
        from .service.file_service import FileService
        
        file_service = FileService()
        await file_service.update_file_status(str(file_id), status, error_message)
        logger.info(f"✅ Updated file_uploads ID {file_id} status to: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update file processing status for ID {file_id}: {e}")


async def process_file_async(
    file_id: int,
    tmp_path: str,
    original_filename: str,
    detected_mime_type: str,
    user_email: str,
    file_size: int,
    sha256_hash: str,
    celery_task_id: str = None
):
    """
    Async file processing logic - now uses service layer
    Handles HTML, Docling (PDF/DOCX), and text files
    Checks for cancellation flags before executing
    """
    try:
        # CHECK FOR CANCELLATION BEFORE STARTING
        if await is_task_cancelled(celery_task_id):
            logger.warning(f"❌ [CELERY] Task {celery_task_id} was marked for cancellation - aborting")
            await update_file_processing_status(file_id, "cancelled", "Task cancelled by admin")
            return

        await update_file_processing_status(file_id, "processing")

        logger.info(f"🔄 [CELERY] Starting processing for file ID {file_id}: {original_filename}")

        # Use service layer for processing
        from .service.file_service import FileService
        file_service = FileService()
        
        result = await file_service.process_file_content(
            file_id=file_id,
            tmp_path=tmp_path,
            original_filename=original_filename,
            detected_mime_type=detected_mime_type,
            celery_task_id=celery_task_id
        )
        
        if result.get("success"):
            logger.info(f"✅ [CELERY] File ID {file_id} processed successfully")
            await update_file_processing_status(file_id, "completed")
        else:
            error_msg = result.get("error", "Unknown processing error")
            logger.error(f"❌ [CELERY] File ID {file_id} processing failed: {error_msg}")
            await update_file_processing_status(file_id, "failed", error_msg)

    except Exception as e:
        error_msg = f"Processing error: {str(e)}"
        logger.error(f"❌ [CELERY] Unexpected error for file ID {file_id}: {e}")
        await update_file_processing_status(file_id, "failed", error_msg)
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

        # Get the current task ID from Celery
        task_id = self.request.id
        logger.info(f"🆔 [TASK_ID] Current task ID: {task_id}")

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
                sha256_hash=sha256_hash,
                celery_task_id=task_id
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
