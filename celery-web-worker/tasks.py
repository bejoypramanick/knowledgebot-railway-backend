"""
Celery tasks for website crawling worker
Handles async website scraping and crawling with database status tracking
"""

import asyncio
from typing import Dict, Any
from fastapi import HTTPException

from celery_app import celery_app
from shared.otel_logger import get_otel_logger, set_task_id
from shared.tenant_context import tenant_context

logger = get_otel_logger("celery_tasks", "celery-web-worker")


def _redact_crawler_options(options: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(options or {})
    if redacted.get("crawler_cookies"):
        redacted["crawler_cookies"] = "[redacted]"
    if redacted.get("crawler_headers"):
        redacted["crawler_headers"] = "[redacted]"
    return redacted


@celery_app.task(bind=True, max_retries=2)
def scrape_website_task(self, website_id: str, url: str, options: Dict[str, Any]):
    """
    Celery task for async website scraping.
    Retries up to 2 times on failure with exponential backoff (60s, 120s).
    """
    task_id = self.request.id
    retry_count = self.request.retries

    # Set task ID in context so it appears in all logs
    set_task_id(task_id)

    logger.info("=" * 80)
    logger.info("🚀 [CELERY_TASK_RECEIVED] Website scraping task RECEIVED by worker")
    logger.info("=" * 80)
    logger.info(
        f"⏰ [TIMESTAMP] Task received at: {__import__('datetime').datetime.utcnow().isoformat()}"
    )
    logger.info(f"📋 [TASK_ID] Celery Task ID: {task_id}")
    logger.info(f"👷 [WORKER_INFO] Worker name: {self.request.hostname}")
    logger.info(
        f"🔄 [RETRY_INFO] Retry Count: {retry_count}, Max Retries: {self.max_retries}"
    )
    logger.info(f"🌐 [WEBSITE_PARAMS] Website ID: {website_id}")
    logger.info(f"🌐 [WEBSITE_PARAMS] URL: {url}")
    logger.info(f"🌐 [WEBSITE_PARAMS] Options: {_redact_crawler_options(options)}")
    logger.info(
        f"📊 [REQUEST_INFO] Host={self.request.hostname}, retries={retry_count}, delivery={self.request.delivery_info}"
    )

    try:
        logger.info("=" * 80)
        logger.info("📦 [PROCESSING_START] Beginning website scraping process")
        logger.info("=" * 80)

        logger.info("🔍 [SERVICE_LOAD] Attempting to load WebsiteService...")
        try:
            # Ensure celery-web-worker directory is in Python path
            import sys
            import os

            worker_dir = os.path.dirname(__file__)
            if worker_dir not in sys.path:
                sys.path.insert(0, worker_dir)
                logger.info(f"   Added to sys.path: {worker_dir}")

            from service.website_service import WebsiteService

            logger.info(
                "✅ [SERVICE_LOAD_SUCCESS] WebsiteService imported successfully"
            )
        except Exception as import_err:
            logger.error(
                f"❌ [SERVICE_LOAD_ERROR] Failed to import WebsiteService: {import_err}"
            )
            logger.error(f"   Error type: {type(import_err).__name__}")
            logger.error(f"   Python path: {sys.path}")
            raise

        logger.info("🔧 [SERVICE_INIT] Instantiating WebsiteService...")
        website_service = WebsiteService()
        logger.info(
            "✅ [SERVICE_INIT_SUCCESS] WebsiteService instantiated successfully"
        )

        logger.info("⚙️  [PROCESS_CALL] About to call process_website_async()...")
        logger.info(f"   Parameters:")
        logger.info(f"     - website_id: {website_id}")
        logger.info(f"     - url: {url}")
        logger.info(f"     - options: {_redact_crawler_options(options)}")
        logger.info(f"     - celery_task_id: {task_id}")

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
        with tenant_context(
            tenant_id=options.get("tenant_id"),
            tenant_slug=options.get("tenant_slug"),
            user_role_id=options.get("user_role_id"),
            user_email=options.get("user_email"),
        ):
            loop.run_until_complete(
                website_service.process_website_async(
                    website_id=website_id,
                    url=url,
                    options=options,
                    celery_task_id=task_id,
                )
            )

        logger.info("=" * 80)
        logger.info("✅ [CELERY_TASK_COMPLETE] Website scraping completed successfully")
        logger.info("=" * 80)
        logger.info(f"🌐 [RESULT] Website ID: {website_id}")
        logger.info(f"🌐 [RESULT] URL: {url}")
        logger.info(f"📋 [RESULT] Task ID: {task_id}")
        logger.info(
            f"⏰ [TIMESTAMP] Task completed at: {__import__('datetime').datetime.utcnow().isoformat()}"
        )

    except Exception as e:
        is_quota_error = (
            isinstance(e, HTTPException)
            and e.status_code == 409
            and isinstance(e.detail, dict)
            and e.detail.get("code") == "kb_quota_exceeded"
        )
        import traceback

        logger.error("=" * 80)
        logger.error(f"❌ [CELERY_TASK_ERROR] ERROR in website scraping task {task_id}")
        logger.error("=" * 80)
        logger.error(
            f"⏰ [TIMESTAMP] Error occurred at: {__import__('datetime').datetime.utcnow().isoformat()}"
        )
        logger.error(f"🌐 [WEBSITE] Website ID: {website_id}")
        logger.error(f"🌐 [WEBSITE] URL: {url}")
        logger.error(f"🚨 [ERROR_TYPE] {type(e).__name__}")
        logger.error(f"🚨 [ERROR_MESSAGE] {str(e)}")
        logger.error(f"🚨 [ERROR_DETAILS] Full traceback:")
        logger.error(traceback.format_exc())
        logger.error(
            f"🔄 [RETRY_INFO] Current Attempt: {retry_count + 1}, Max Retries: {self.max_retries}"
        )
        logger.error(
            f"⏱️  [BACKOFF] Next retry in: {60 * (2**retry_count)}s (exponential backoff)"
        )

        if is_quota_error:
            # Mark website as failed in database
            try:
                logger.info(
                    "💾 [DB_UPDATE] Marking website as failed due to KB quota breach..."
                )
                from dao.scraping_dao import ScrapingDAO

                dao = ScrapingDAO()
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                with tenant_context(
                    tenant_id=options.get("tenant_id"),
                    tenant_slug=options.get("tenant_slug"),
                    user_role_id=options.get("user_role_id"),
                    user_email=options.get("user_email"),
                ):
                    loop.run_until_complete(
                        dao.update_website_status(
                            website_id,
                            "failed",
                            e.detail.get("message"),
                        )
                    )
            except Exception as dao_err:
                logger.error(
                    f"❌ [DB_UPDATE] Failed to mark quota-blocked website as failed: {dao_err}"
                )

            return {"success": False, "error": e.detail.get("message")}

        # Retry with exponential backoff (60s, then 120s)
        try:
            countdown = 60 * (2**self.request.retries)
            logger.info(f"🔁 [RETRY] Retrying task {task_id} in {countdown}s...")
            raise self.retry(exc=e, countdown=countdown)
        except Exception:
            logger.error("=" * 80)
            logger.error(
                f"❌ [MAX_RETRIES_EXCEEDED] Failed to scrape website ID {website_id}"
            )
            logger.error("=" * 80)
            logger.error(f"🌐 [WEBSITE] Website ID: {website_id}")
            logger.error(f"🌐 [WEBSITE] URL: {url}")
            logger.error(f"🚨 [ERROR] {type(e).__name__}: {str(e)}")
            logger.error(
                f"🔄 [RETRY_INFO] Max retries exceeded after {self.max_retries} attempts"
            )

            # Update status to failed after max retries
            try:
                logger.info(
                    "💾 [DB_UPDATE] Updating website status to failed in database..."
                )
                from dao.scraping_dao import ScrapingDAO

                dao = ScrapingDAO()

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
                with tenant_context(
                    tenant_id=options.get("tenant_id"),
                    tenant_slug=options.get("tenant_slug"),
                    user_role_id=options.get("user_role_id"),
                    user_email=options.get("user_email"),
                ):
                    loop.run_until_complete(
                        dao.update_website_status(
                            website_id,
                            "failed",
                            f"Processing failed after {self.max_retries} retries: {str(e)}",
                        )
                    )
                logger.info(
                    f"✅ [DB_UPDATE] Website status updated to failed for ID {website_id}"
                )
            except Exception as dao_err:
                logger.error(
                    f"❌ [DB_UPDATE] Failed to update website status to failed: {dao_err}"
                )

            return {"success": False, "error": e.detail.get("message")}
