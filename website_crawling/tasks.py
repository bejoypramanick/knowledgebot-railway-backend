"""
Celery tasks for website crawling service
Handles async website scraping and crawling with database status tracking
"""

import asyncio
from typing import Dict, Any

from celery import shared_task
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_tasks", "website-crawling")


async def update_website_processing_status(website_id: int, status: str, error_message: str = None):
    """Update website processing status in database"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            if error_message:
                await conn.execute(
                    "UPDATE scraped_websites SET processing_status = $1, error_message = $2, updated_at = NOW() WHERE id = $3",
                    status, error_message, website_id
                )
            else:
                await conn.execute(
                    "UPDATE scraped_websites SET processing_status = $1, error_message = NULL, updated_at = NOW() WHERE id = $3",
                    status, website_id
                )
            logger.info(f"✅ Updated scraped_websites ID {website_id} status to: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update website processing status for ID {website_id}: {e}")


async def process_website_async(
    website_id: int,
    url: str,
    options: Dict[str, Any]
):
    """
    Async website scraping logic
    Handles Crawl4AI scraping, Docling conversion, and Gemini upload
    """
    try:
        await update_website_processing_status(website_id, "processing")

        logger.info(f"🔄 [CELERY] Starting scraping for website ID {website_id}: {url}")

        from website_crawling.service.website_service import WebsiteService

        # Create service and perform scraping
        service = WebsiteService()
        result = await service.scrape_website(url, options)

        if result.get("success"):
            logger.info(f"✅ [CELERY] Website ID {website_id} scraped successfully")
            await update_website_processing_status(website_id, "completed")
        else:
            error_msg = result.get("error", "Unknown scraping error")
            logger.error(f"❌ [CELERY] Website ID {website_id} scraping failed: {error_msg}")
            await update_website_processing_status(website_id, "failed", error_msg)

    except Exception as e:
        error_msg = f"Scraping error: {str(e)}"
        logger.error(f"❌ [CELERY] Unexpected error for website ID {website_id}: {e}")
        await update_website_processing_status(website_id, "failed", error_msg)


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

        # Run async function in event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            process_website_async(
                website_id=website_id,
                url=url,
                options=options
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
