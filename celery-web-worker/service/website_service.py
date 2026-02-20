"""
Website Service for Celery Website Crawling Worker
Handles business logic for website crawling operations
"""
import os
from typing import Dict, List, Any, Optional
from dao.scraping_dao import ScrapingDAO
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("website_service", "celery-web-worker")

class WebsiteService:
    def __init__(self):
        self.scraping_dao = ScrapingDAO()

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website by ID."""
        return await self.scraping_dao.get_website_by_id(website_id)

    async def update_website_status(self, website_id: int, status: str, error_message: str = None):
        """Update website processing status."""
        try:
            await self.scraping_dao.update_website_status(website_id, status, error_message)
            logger.info(f"✅ Updated website {website_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update website {website_id} status: {e}")
            return False

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all website records."""
        return await self.scraping_dao.get_all_websites()

    async def delete_website_record(self, url: str):
        """Delete website record."""
        try:
            await self.scraping_dao.delete_website_record(url)
            logger.info(f"✅ Deleted website record for {url}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete website record for {url}: {e}")
            return False

    async def create_website_record(self, website_data: Dict[str, Any]) -> Optional[int]:
        """Create new website record."""
        try:
            website_id = await self.scraping_dao.record_scraped_metadata(website_data)
            if website_id:
                logger.info(f"✅ Created website record {website_id}")
                return website_id
            else:
                logger.error("❌ Failed to create website record")
                return None
        except Exception as e:
            logger.error(f"❌ Error creating website record: {e}")
            return None

    async def process_website_async(self, website_id: int, url: str, options: Dict[str, Any],
                              celery_task_id: str = None):
        """Process website content - delegates to processing service"""
        try:
            # ✅ CHECK FOR CANCELLATION BEFORE STARTING
            if await self.is_task_cancelled(celery_task_id):
                logger.warning(f"❌ [CELERY] Task {celery_task_id} was marked for cancellation - aborting")
                await self.update_website_status(website_id, "cancelled", "Task cancelled by admin")
                return

            await self.update_website_status(website_id, "processing")

            logger.info(f"🔄 [CELERY] Starting scraping for website ID {website_id}: {url}")

            # Use processing service for all website logic
            from .processing_service import ProcessingService
            from models.value_objects import ProcessingRequest, CrawlConfig
            processing_service = ProcessingService()

            # Extract parameters from options
            extracted_user_role_id = options.get("user_role_id")
            logger.info(f"👤 [USER_ROLE] Extracted user_role_id from options: {extracted_user_role_id} (type: {type(extracted_user_role_id).__name__})")

            # Build ProcessingRequest with CrawlConfig
            crawl_config = CrawlConfig(
                max_depth=options.get("max_depth", 2),
                max_pages=options.get("max_pages", 1000),  # Increased default for sitemaps
                max_concurrent=options.get("max_concurrent", 10),
                delay_between_requests=options.get("delay_between_requests", 0.0)
            )

            processing_request = ProcessingRequest(
                website_id=website_id,
                url=url,
                crawl_config=crawl_config,
                user_email=options.get("user_email", "admin"),
                user_role_id=extracted_user_role_id,
                celery_task_id=celery_task_id,
                replace_existing=options.get("replace_existing", False),
                options=options
            )

            result = await processing_service.process_website_content(processing_request)

            if result.get("success"):
                logger.info(f"✅ [CELERY] Website ID {website_id} processed successfully")
                await self.update_website_status(website_id, "completed")
            else:
                error_msg = result.get("error", "Unknown processing error")
                logger.error(f"❌ [CELERY] Website ID {website_id} processing failed: {error_msg}")
                await self.update_website_status(website_id, "failed", error_msg)

        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            logger.error(f"❌ [CELERY] Unexpected error for website ID {website_id}: {e}")
            await self.update_website_status(website_id, "failed", error_msg)

    async def is_task_cancelled(self, celery_task_id: str) -> bool:
        """Check if task has been marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            # Use WEB_REDIS_URL (DB 1) for web tasks
            redis_url = os.getenv('WEB_REDIS_URL', 'redis://localhost:6379/1')

            try:
                redis_conn = redis_lib.from_url(redis_url, socket_connect_timeout=2)
                cancelled_key = f"task_cancelled:{celery_task_id}"
                result = redis_conn.exists(cancelled_key)
                redis_conn.close()
                return bool(result)
            except redis_lib.ConnectionError as conn_err:
                # Redis not available - not critical, just skip cancellation check
                # This is common in local development without Redis
                logger.debug(f"ℹ️ Redis unavailable for cancellation check (this is OK): {redis_url}")
                return False
        except Exception as e:
            logger.debug(f"ℹ️ Skipping cancellation check: {e}")
            return False
