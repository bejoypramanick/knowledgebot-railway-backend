"""
Result Handler Service
Listens to Redis result queues and updates database accordingly
Runs as background task in knowledgebase_ingestion
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from shared.redis_message_queue import redis_message_queue
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("result_handler", "knowledgebase-ingestion")


class ResultHandler:
    """Handle processing results from Redis queues and update database"""

    def __init__(self):
        self.running = False
        self.poll_interval = 2  # seconds between polling Redis

    async def start(self):
        """Start the result handler background task"""
        self.running = True
        logger.info("🚀 Starting Redis result handler...")

        try:
            while self.running:
                try:
                    # Check for file processing results
                    await self._process_file_results()

                    # Check for web processing results
                    await self._process_web_results()

                    # Small delay before next poll
                    await asyncio.sleep(self.poll_interval)

                except Exception as e:
                    logger.error(f"❌ Error in result handler loop: {e}", exc_info=True)
                    await asyncio.sleep(self.poll_interval)

        except asyncio.CancelledError:
            logger.info("⏸️ Result handler cancelled")
            self.running = False
        except Exception as e:
            logger.error(f"❌ Result handler crashed: {e}", exc_info=True)
            self.running = False

    async def stop(self):
        """Stop the result handler"""
        logger.info("🛑 Stopping result handler...")
        self.running = False

    async def _process_file_results(self):
        """Process file processing results from Redis"""
        try:
            # Non-blocking get from result queue
            result_message = redis_message_queue.get_file_result(timeout=0)

            if not result_message:
                return  # No results waiting

            file_id = result_message.get('file_id')
            celery_task_id = result_message.get('celery_task_id')
            status = result_message.get('status')  # 'completed', 'failed', 'cancelled'
            error = result_message.get('error')
            result = result_message.get('result', {})

            logger.info(f"📥 [FILE_RESULT] Processing file result: file_id={file_id}, status={status}")

            # Update database
            async with get_db_connection() as conn:
                if status == "completed":
                    # Success: Update file record with completion details
                    await conn.execute(
                        """UPDATE file_uploads
                           SET processing_status = 'completed',
                               updated_at = NOW()
                           WHERE id = $1""",
                        file_id
                    )
                    logger.info(f"✅ [FILE_DB] Updated file {file_id} to completed")

                elif status == "failed":
                    # Failure: Update with error message
                    await conn.execute(
                        """UPDATE file_uploads
                           SET processing_status = 'failed',
                               error_message = $1,
                               updated_at = NOW()
                           WHERE id = $2""",
                        error or "Unknown error",
                        file_id
                    )
                    logger.error(f"❌ [FILE_DB] Updated file {file_id} to failed: {error}")

                elif status == "cancelled":
                    # Cancellation: Update status
                    await conn.execute(
                        """UPDATE file_uploads
                           SET processing_status = 'cancelled',
                               error_message = 'Task cancelled by user',
                               updated_at = NOW()
                           WHERE id = $1""",
                        file_id
                    )
                    logger.warning(f"⏸️ [FILE_DB] Updated file {file_id} to cancelled")

        except Exception as e:
            logger.error(f"❌ Error processing file result: {e}", exc_info=True)

    async def _process_web_results(self):
        """Process website scraping results from Redis"""
        try:
            # Non-blocking get from result queue
            result_message = redis_message_queue.get_web_result(timeout=0)

            if not result_message:
                return  # No results waiting

            website_id = result_message.get('website_id')
            celery_task_id = result_message.get('celery_task_id')
            status = result_message.get('status')  # 'completed', 'failed', 'cancelled'
            error = result_message.get('error')
            result = result_message.get('result', {})

            logger.info(f"📥 [WEB_RESULT] Processing website result: website_id={website_id}, status={status}")

            # Update database
            async with get_db_connection() as conn:
                if status == "completed":
                    # Success: Update website record with completion details
                    await conn.execute(
                        """UPDATE scraped_websites
                           SET processing_status = 'completed',
                               updated_at = NOW()
                           WHERE id = $1""",
                        website_id
                    )
                    logger.info(f"✅ [WEB_DB] Updated website {website_id} to completed")

                elif status == "failed":
                    # Failure: Update with error message
                    await conn.execute(
                        """UPDATE scraped_websites
                           SET processing_status = 'failed',
                               error_message = $1,
                               updated_at = NOW()
                           WHERE id = $2""",
                        error or "Unknown error",
                        website_id
                    )
                    logger.error(f"❌ [WEB_DB] Updated website {website_id} to failed: {error}")

                elif status == "cancelled":
                    # Cancellation: Update status
                    await conn.execute(
                        """UPDATE scraped_websites
                           SET processing_status = 'cancelled',
                               error_message = 'Task cancelled by user',
                               updated_at = NOW()
                           WHERE id = $1""",
                        website_id
                    )
                    logger.warning(f"⏸️ [WEB_DB] Updated website {website_id} to cancelled")

        except Exception as e:
            logger.error(f"❌ Error processing web result: {e}", exc_info=True)


# Global result handler instance
_result_handler = None


def get_result_handler() -> ResultHandler:
    """Get or create global result handler instance"""
    global _result_handler
    if _result_handler is None:
        _result_handler = ResultHandler()
    return _result_handler


async def start_result_handler():
    """Start the result handler background task"""
    handler = get_result_handler()
    await handler.start()


async def stop_result_handler():
    """Stop the result handler"""
    handler = get_result_handler()
    await handler.stop()
