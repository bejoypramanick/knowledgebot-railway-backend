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
    retry_count = self.request.retries

    logger.info("=" * 80)
    logger.info("🚀 [CELERY_TASK_START] Website scraping task started")
    logger.info("=" * 80)
    logger.info(f"📋 [TASK_ID] Celery Task ID: {task_id}")
    logger.info(f"🔄 [RETRY_INFO] Retry Count: {retry_count}, Max Retries: {self.max_retries}")
    logger.info(f"🌐 [WEBSITE_PARAMS] Website ID: {website_id}")
    logger.info(f"🌐 [WEBSITE_PARAMS] URL: {url}")
    logger.info(f"🌐 [WEBSITE_PARAMS] Options: {options}")

    try:
        logger.info("🔍 [PROCESSING] Loading WebsiteService...")
        from service.website_service import WebsiteService

        website_service = WebsiteService()
        logger.info("✅ [PROCESSING] WebsiteService loaded successfully")

        logger.info("⚙️  [PROCESSING] Calling process_website_async() with all parameters...")
        asyncio.run(
            website_service.process_website_async(
                website_id=website_id,
                url=url,
                options=options,
                celery_task_id=task_id
            )
        )

        logger.info("=" * 80)
        logger.info("✅ [CELERY_TASK_COMPLETE] Website scraping completed successfully")
        logger.info("=" * 80)
        logger.info(f"🌐 [RESULT] Website ID: {website_id}")
        logger.info(f"🌐 [RESULT] URL: {url}")
        logger.info(f"📋 [RESULT] Task ID: {task_id}")

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [CELERY_TASK_ERROR] Error in website scraping task {task_id}")
        logger.error("=" * 80)
        logger.error(f"🌐 [WEBSITE] Website ID: {website_id}")
        logger.error(f"🌐 [WEBSITE] URL: {url}")
        logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
        logger.error(f"🔄 [RETRY_INFO] Current Attempt: {retry_count + 1}, Max Retries: {self.max_retries}")
        logger.error(f"⏱️  [BACKOFF] Next retry in: {60 * (2 ** retry_count)}s (exponential backoff)", exc_info=True)

        # Retry with exponential backoff (60s, then 120s)
        try:
            countdown = 60 * (2 ** self.request.retries)
            logger.info(f"🔁 [RETRY] Retrying task {task_id} in {countdown}s...")
            raise self.retry(exc=e, countdown=countdown)
        except Exception:
            logger.error("=" * 80)
            logger.error(f"❌ [MAX_RETRIES_EXCEEDED] Failed to scrape website ID {website_id}")
            logger.error("=" * 80)
            logger.error(f"🌐 [WEBSITE] Website ID: {website_id}")
            logger.error(f"🌐 [WEBSITE] URL: {url}")
            logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
            logger.error(f"🔄 [RETRY_INFO] Max retries exceeded after {self.max_retries} attempts")

            # Update status to failed after max retries
            try:
                logger.info("💾 [DB_UPDATE] Updating website status to failed in database...")
                from dao.scraping_dao import ScrapingDAO
                dao = ScrapingDAO()
                asyncio.run(
                    dao.update_website_status(
                        website_id,
                        "failed",
                        f"Processing failed after {self.max_retries} retries: {str(e)}"
                    )
                )
                logger.info(f"✅ [DB_UPDATE] Website status updated to failed for ID {website_id}")
            except Exception as dao_err:
                logger.error(f"❌ [DB_UPDATE] Failed to update website status to failed: {dao_err}", exc_info=True)
