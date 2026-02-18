"""
Celery tasks for website crawling worker
Handles async website scraping and crawling with database status tracking
"""

import asyncio
from typing import Dict, Any

from celery_app import celery_app
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_tasks", "celery-web-worker")


@celery_app.task(bind=True, max_retries=2)
def scrape_website_task(
    self,
    website_id: int,
    url: str,
    options: Dict[str, Any]
):
    """
    Celery task for async website scraping.
    Retries up to 2 times on failure with exponential backoff (60s, 120s).
    """
    task_id = self.request.id
    logger.info(f"📋 [TASK] Starting website scraping task: {task_id}")
    logger.info(f"🌐 [WEBSITE] ID: {website_id}, URL: {url}")

    try:
        from service.website_service import WebsiteService

        website_service = WebsiteService()

        asyncio.run(
            website_service.process_website_async(
                website_id=website_id,
                url=url,
                options=options,
                celery_task_id=task_id
            )
        )

        logger.info(f"✅ [TASK] Website scraping completed: {task_id} for website ID {website_id}")

    except Exception as e:
        logger.error(f"❌ [TASK] Error in website scraping task {task_id} for website ID {website_id}: {e}", exc_info=True)

        # Retry with exponential backoff (60s, then 120s)
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception:
            logger.error(f"❌ [TASK] Max retries exceeded for website ID {website_id}")
            # Update status to failed after max retries
            try:
                from dao.scraping_dao import ScrapingDAO
                dao = ScrapingDAO()
                asyncio.run(dao.update_website_status(website_id, "failed", f"Processing failed after retries: {str(e)}"))
            except Exception as dao_err:
                logger.error(f"❌ [TASK] Failed to update website status to failed: {dao_err}")
