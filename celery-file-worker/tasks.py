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
        logger.info(f" [TASK] Starting Celery task for file ID {file_id}")

        # Get current task ID from Celery
        task_id = self.request.id
        logger.info(f" [TASK_ID] Current task ID: {task_id}")

        # Use service layer for processing
        from .service.file_service import FileService
        
        file_service = FileService()
        
        # Run async function in event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            file_service.process_file_content(
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

        logger.info(f" [TASK] Celery task completed for file ID {file_id}")
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
