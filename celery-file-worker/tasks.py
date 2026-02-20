"""
Celery tasks for file processing worker
Handles async file processing with database status tracking
"""

import asyncio
from typing import Dict, Any

from celery_app import celery_app
from shared.otel_logger import get_otel_logger, set_task_id

logger = get_otel_logger("celery_tasks", "celery-file-worker")


@celery_app.task(bind=True, max_retries=2)
def process_file_upload_task(
    self,
    original_filename: str,
    file_display_name: str,
    s3_key: str,
    file_size: int,
    user_email: str,
    user_role_id: int = None
):
    """
    Celery task for async file processing.
    Retries up to 2 times on failure with exponential backoff (60s, 120s).

    Handles:
    - Download file from S3
    - File validation (extension, MIME type, size)
    - Duplicate detection (by SHA256 hash)
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
    logger.info(f"📄 [FILE_PARAMS] Original Filename: {original_filename}")
    logger.info(f"📄 [FILE_PARAMS] Display Name: {file_display_name}")
    logger.info(f"📄 [FILE_PARAMS] Size: {file_size} bytes")
    logger.info(f"📄 [FILE_PARAMS] S3 Key: {s3_key}")
    logger.info(f"👤 [USER_INFO] Email: {user_email}")
    logger.info(f"👤 [USER_INFO] Role ID: {user_role_id}")

    try:
        logger.info("🔍 [PROCESSING] Loading processing functions...")
        
        # Ensure celery-file-worker directory is in Python path (do this right before import)
        import sys
        import os
        worker_dir = os.path.dirname(__file__)
        if worker_dir not in sys.path:
            sys.path.insert(0, worker_dir)
            logger.info(f"   Added to sys.path: {worker_dir}")
        
        logger.info(f"🔍 [DEBUG] sys.path (first 5): {sys.path[:5]}")
        logger.info(f"🔍 [DEBUG] Current dir: {os.getcwd()}")
        logger.info(f"🔍 [DEBUG] Worker dir: {worker_dir}")
        
        from service.processing_service import process_file_content
        logger.info("✅ [PROCESSING] process_file_content loaded successfully")

        logger.info("⚙️  [PROCESSING] Calling process_file_content() with all parameters...")
        result = asyncio.run(
            process_file_content(
                original_filename=original_filename,
                file_display_name=file_display_name,
                s3_key=s3_key,
                file_size=file_size,
                user_email=user_email,
                user_role_id=user_role_id,
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

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [CELERY_TASK_ERROR] Error in file processing task {task_id}")
        logger.error("=" * 80)
        logger.error(f"📄 [FILE] {original_filename}")
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
            logger.error(f"❌ [MAX_RETRIES_EXCEEDED] Failed to process file {original_filename}")
            logger.error("=" * 80)
            logger.error(f"📄 [FILE] {original_filename}")
            logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
            logger.error(f"🔄 [RETRY_INFO] Max retries exceeded after {self.max_retries} attempts")

            return {
                "success": False,
                "error": f"Processing failed after {self.max_retries} retries: {str(e)}"
            }
