"""
Celery tasks for website crawling service
Handles async website scraping and crawling with database status tracking
"""

import asyncio
from typing import Dict, Any
import os

from celery import shared_task
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_tasks", "website-crawling")


@shared_task(bind=True, max_retries=2)
def scrape_website_task(
    self,
    website_id: int,
    url: str,
    options: Dict[str, Any]
):
    """
    Celery task for async website scraping
    Retries up to 2 times on failure
    """
    try:
        logger.info(f"📋 [TASK] Starting Celery task for website ID {website_id}")

        # Get current task ID from Celery
        task_id = self.request.id
        logger.info(f"🆔 [TASK_ID] Current task ID: {task_id}")

        # Use service layer for processing
        from .service.website_service import WebsiteService
        
        website_service = WebsiteService()
        
        # Run async function in event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            website_service.process_website_async(
                website_id=website_id,
                url=url,
                options=options,
                celery_task_id=task_id
            )
        )

        logger.info(f"✅ [TASK] Celery task completed for website ID {website_id}")

    except Exception as e:
        logger.error(f"❌ [TASK] Error in Celery task for website ID {website_id}: {e}")

        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception as retry_error:
            logger.error(f"❌ [TASK] Max retries exceeded for website ID {website_id}: {retry_error}")
            # Update status to failed after max retries
            loop = asyncio.get_event_loop()
            loop.run_until_complete(
                update_website_processing_status(website_id, "failed", f"Processing failed after retries: {str(e)}")
            )
