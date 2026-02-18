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


async def is_task_cancelled(celery_task_id: str) -> bool:
    """Check if task has been marked for cancellation via Redis"""
    if not celery_task_id:
        return False

    try:
        import redis as redis_lib
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
        redis_conn = redis_lib.from_url(redis_url)

        cancelled_key = f"task_cancelled:{celery_task_id}"
        result = redis_conn.exists(cancelled_key)
        redis_conn.close()

        return bool(result)
    except Exception as e:
        logger.warning(f"⚠️ Error checking cancellation status: {e}")
        return False


async def process_website_async(
    website_id: int,
    url: str,
    options: Dict[str, Any],
    celery_task_id: str = None
):
    """
    Async website scraping logic
    Handles Crawl4AI scraping, Docling conversion, and Gemini upload
    Checks for cancellation flags before executing
    """
    try:
        # CHECK FOR CANCELLATION BEFORE STARTING
        if await is_task_cancelled(celery_task_id):
            logger.warning(f"❌ [CELERY] Task {celery_task_id} was marked for cancellation - aborting")
            from .service.website_service import WebsiteService
            website_service = WebsiteService()
            await website_service.update_website_status(website_id, "cancelled", "Task cancelled by admin")
            return

        from .service.website_service import WebsiteService
        website_service = WebsiteService()
        await website_service.update_website_status(website_id, "processing")

        logger.info(f"🔄 [CELERY] Starting scraping for website ID {website_id}: {url}")

        # Use service layer for processing
        from .service.website_service import WebsiteService
        
        website_service = WebsiteService()
        result = await website_service.scrape_website(url, options, celery_task_id=celery_task_id, website_id=website_id)
        
        if result.get("success"):
            logger.info(f"✅ [CELERY] Website ID {website_id} scraped successfully")
            await website_service.update_website_status(website_id, "completed")
        else:
            error_msg = result.get("error", "Unknown scraping error")
            logger.error(f"❌ [CELERY] Website ID {website_id} scraping failed: {error_msg}")
            await website_service.update_website_status(website_id, "failed", error_msg)

    except Exception as e:
        error_msg = f"Scraping error: {str(e)}"
        logger.error(f"❌ [CELERY] Unexpected error for website ID {website_id}: {e}")
        await website_service.update_website_status(website_id, "failed", error_msg)


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
        logger.info(f"📋 [TASK] Starting Celery task for website ID {website_id}: {url}")

        # Get current task ID from Celery
        task_id = self.request.id
        logger.info(f"🆔 [TASK_ID] Current task ID: {task_id}")

        # Run async function in event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            process_website_async(
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
