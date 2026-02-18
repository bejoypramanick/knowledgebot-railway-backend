"""
Celery tasks for file processing worker
Handles async file processing with database status tracking
"""

import asyncio
from typing import Dict, Any

from celery_app import celery_app
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_tasks", "celery-file-worker")


@celery_app.task(bind=True, max_retries=2)
def process_file_upload_task(
    self,
    original_filename: str,
    file_display_name: str,
    s3_key: str,
    file_size: int,
    user_email: str
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
    logger.info(f"🚀 [TASK] Starting file processing task: {task_id}")
    logger.info(f"📄 [FILE] {original_filename} (display: {file_display_name}, size: {file_size} bytes)")
    logger.info(f"   S3 Key: {s3_key}")

    try:
        from service.processing_service import ProcessingService

        processing_service = ProcessingService()

        result = asyncio.run(
            processing_service.process_file_content(
                original_filename=original_filename,
                file_display_name=file_display_name,
                s3_key=s3_key,
                file_size=file_size,
                user_email=user_email,
                celery_task_id=task_id
            )
        )

        logger.info(f"✅ [TASK] File processing completed: {task_id}")
        logger.info(
            f"📊 [RESULT] File ID: {result.get('file_id')}, "
            f"Status: {result.get('status')}, "
            f"Time: {result.get('processing_time_seconds')}s"
        )

        return result

    except Exception as e:
        logger.error(f"❌ [TASK] Error in file processing task {task_id}: {e}", exc_info=True)

        # Retry with exponential backoff (60s, then 120s)
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception:
            logger.error(f"❌ [TASK] Max retries exceeded for file {original_filename}")
            return {
                "success": False,
                "error": f"Processing failed after {self.max_retries} retries: {str(e)}"
            }
