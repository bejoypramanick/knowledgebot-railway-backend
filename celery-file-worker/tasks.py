"""
Celery tasks for file processing worker
Handles async file processing with database status tracking
"""

import os
import sys
import asyncio
from typing import Dict, Any
from celery.exceptions import SoftTimeLimitExceeded

from celery_app import celery_app
from shared.otel_logger import get_otel_logger, set_task_id

logger = get_otel_logger("celery_tasks", "celery-file-worker")


@celery_app.task(bind=True, max_retries=2)
def process_file_upload_task(
    self,
    file_id: str,
    user_email: str
):
    """
    Celery task for async file processing.
    Retries up to 2 times on failure with exponential backoff (60s, 120s).

    Args:
        file_id: Database ID of the file to process
        user_email: User email for logging context

    Handles:
    - Query database for file details
    - Download file from S3
    - File validation (extension, MIME type, size)
    - Format conversion (HTML→Markdown, PDF→Markdown)
    - Gemini FileSearch upload
    - Database metadata recording
    - Delete from S3
    """
    task_id = self.request.id
    retry_count = self.request.retries

    # Set task ID in context so it appears in all logs
    set_task_id(task_id)

    logger.info("=" * 80)
    logger.info("🚀 [CELERY_TASK_START] File processing task started")
    logger.info("=" * 80)
    logger.info(f"📋 [TASK_ID] Celery Task ID: {task_id}")
    logger.info(f"🔄 [RETRY_INFO] Retry Count: {retry_count}, Max Retries: {self.max_retries}")
    logger.info(f"📄 [FILE_PARAMS] File ID: {file_id}")
    logger.info(f"👤 [USER_INFO] Email: {user_email}")

    try:
        logger.info("🔍 [PROCESSING] Loading processing functions...")
        
        # Ensure celery-file-worker directory is in Python path (do this right before import)
        worker_dir = os.path.dirname(__file__)
        if worker_dir not in sys.path:
            sys.path.insert(0, worker_dir)
            logger.info(f"   Added to sys.path: {worker_dir}")
        
        logger.info(f"🔍 [DEBUG] sys.path (first 5): {sys.path[:5]}")
        logger.info(f"🔍 [DEBUG] Current dir: {os.getcwd()}")
        logger.info(f"🔍 [DEBUG] Worker dir: {worker_dir}")
        
        from service.processing_service import process_file_content
        logger.info("✅ [PROCESSING] process_file_content loaded successfully")

        logger.info(f"⚙️  [PROCESSING] Calling process_file_content() with file_id {file_id}")
        
        # Get or create event loop for this worker process
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Run the async function
        result = loop.run_until_complete(
            process_file_content(
                file_id=file_id,
                user_email=user_email,
                celery_task_id=task_id
            )
        )

        logger.info("=" * 80)
        logger.info("✅ [CELERY_TASK_COMPLETE] File processing completed successfully")
        logger.info("=" * 80)
        
        # Safely handle result - it might be None if exception occurred
        if result:
            logger.info(f"📊 [RESULT] File ID: {result.get('file_id')}")
            logger.info(f"📊 [RESULT] Status: {result.get('status')}")
            logger.info(f"📊 [RESULT] Processing Time: {result.get('processing_time_seconds')}s")
            logger.info(f"📊 [RESULT] Success: {result.get('success')}")
        else:
            logger.warning("⚠️ [RESULT] Result is None - processing may have failed")

        return result

    except SoftTimeLimitExceeded:
        logger.error("=" * 80)
        logger.error(f"⏱️  [TIMEOUT] Task exceeded time limit (35 minutes)")
        logger.error("=" * 80)
        logger.error(f"📄 [FILE] File ID: {file_id}")
        logger.error(f"⏱️  [TIMEOUT] Task was killed due to timeout")
        logger.error(f"💡 [HINT] File may be too large or docling queue is backed up")
        
        # Mark file as failed in database
        try:
            from dao.fileupload_dao import FileUploadDAO
            dao = FileUploadDAO()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                dao.update_file_status(file_id, "failed", "Processing timeout (35 minutes)")
            )
            logger.info(f"✅ [DB_UPDATE] Marked file {file_id} as failed due to timeout")
        except Exception as db_err:
            logger.error(f"❌ [DB_UPDATE] Failed to update file status: {db_err}")
        
        return {
            "success": False,
            "error": "Processing timeout (35 minutes) - file may be too large or docling queue is backed up"
        }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [CELERY_TASK_ERROR] Error in file processing task {task_id}")
        logger.error("=" * 80)
        logger.error(f"📄 [FILE] File ID: {file_id}")
        logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
        logger.error(f"🔄 [RETRY_INFO] Current Attempt: {retry_count + 1}, Max Retries: {self.max_retries}")
        logger.error(f"⏱️  [BACKOFF] Next retry in: {60 * (2 ** retry_count)}s (exponential backoff)")

        # Retry with exponential backoff (60s, then 120s)
        try:
            countdown = 60 * (2 ** self.request.retries)
            logger.info(f"🔁 [RETRY] Retrying task {task_id} in {countdown}s...")
            raise self.retry(exc=e, countdown=countdown)
        except Exception as retry_exc:
            logger.error("=" * 80)
            logger.error(f"❌ [MAX_RETRIES_EXCEEDED] Failed to process file ID: {file_id}")
            logger.error("=" * 80)
            logger.error(f"📄 [FILE] File ID: {file_id}")
            logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
            logger.error(f"🔄 [RETRY_INFO] Max retries exceeded after {self.max_retries} attempts")

            return {
                "success": False,
                "error": f"Processing failed after {self.max_retries} retries: {str(e)}"
            }
