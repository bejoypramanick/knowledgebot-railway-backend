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


@shared_task(bind=True, max_retries=2)
def process_file_upload_task(
    self,
    original_filename: str,
    file_display_name: str,
    s3_key: str,
    file_size: int,
    user_email: str
):
    """
    Celery task for async file processing
    Retries up to 2 times on failure

    Worker creates DB record and handles all processing:
    - Download file from S3
    - File validation (extension, MIME type, size)
    - Duplicate detection (by SHA256 hash)
    - Format conversion (HTML→Markdown, PDF→Markdown)
    - Gemini FileSearch upload
    - Database metadata recording
    - Delete from S3
    """
    try:
        # Get current task ID from Celery
        task_id = self.request.id
        logger.info(f"🚀 [TASK] Starting file processing task: {task_id}")
        logger.info(f"📄 [FILE] {original_filename} (display: {file_display_name}, size: {file_size} bytes)")
        logger.info(f"   S3 Key: {s3_key}")

        # Use processing service for all file logic
        from .service.processing_service import ProcessingService

        processing_service = ProcessingService()

        # Run async function in event loop
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
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
        logger.info(f"📊 [RESULT] File ID: {result.get('file_id')}, Status: {result.get('status')}, Time: {result.get('processing_time_seconds')}s")

        return result

    except Exception as e:
        logger.error(f"❌ [TASK] Error in file processing task {task_id}: {e}", exc_info=True)

        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception as retry_error:
            logger.error(f"❌ [TASK] Max retries exceeded for file {original_filename}: {retry_error}")
            # Return failure result
            return {
                "success": False,
                "error": f"Processing failed after {self.request.retries} retries: {str(e)}"
            }
