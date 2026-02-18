"""
Redis Message Queue Service
Bidirectional messaging between knowledgebase_ingestion and workers
Handles task dispatch and result reporting
"""
import os
import json
import logging
import redis
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger("redis_message_queue")


class RedisMessageQueue:
    """Redis-based message queue for inter-service communication"""

    # Queue names
    FILE_TASK_QUEUE = "file_processing_tasks"  # knowledgebase → file-worker

    def __init__(self):
        """Initialize Redis connection"""
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self._connection = None
        self._init_connection()

    def _init_connection(self):
        """Initialize Redis connection"""
        try:
            self._connection = redis.from_url(self.redis_url)
            # Test connection
            self._connection.ping()
            logger.info(f"✅ Redis message queue initialized: {self.redis_url}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Redis connection: {e}")
            self._connection = None

    def is_available(self) -> bool:
        """Check if Redis is available"""
        return self._connection is not None

    # ========== FILE PROCESSING MESSAGES ==========

    def publish_file_task(
        self,
        celery_task_id: str,
        file_id: Optional[int] = None
    ) -> bool:
        """
        Publish file processing task to queue
        Called by: knowledgebase_ingestion
        Read by: celery-file-worker
        Note: file_id is optional - worker will create DB record and assign it
        """
        if not self.is_available():
            logger.error("❌ Redis not available, cannot publish task")
            return False

        try:
            message = {
                "type": "FILE_PROCESS",
                "celery_task_id": celery_task_id
            }

            message_json = json.dumps(message)
            self._connection.rpush(self.FILE_TASK_QUEUE, message_json)

            logger.info(f"📤 [FILE] Published task: {celery_task_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to publish file task: {e}")
            return False

    def get_file_task(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """
        Get file task from queue (blocking pop)
        Called by: celery-file-worker
        Returns: Parsed message dict or None
        """
        if not self.is_available():
            return None

        try:
            # BLPOP with timeout in seconds
            result = self._connection.blpop(self.FILE_TASK_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                message = json.loads(message_json)
                logger.info(f"📥 [FILE] Received task: file_id={message.get('file_id')}")
                return message
            return None

        except Exception as e:
            logger.error(f"❌ Error getting file task: {e}")
            return None

    def publish_file_result(self, celery_task_id: str) -> bool:
        """
        Publish file processing result
        Called by: celery-file-worker
        Read by: knowledgebase_ingestion
        """
        if not self.is_available():
            logger.error("❌ Redis not available, cannot publish result")
            return False

        try:
            message = {
                "type": "FILE_RESULT",
                "celery_task_id": celery_task_id
            }

            message_json = json.dumps(message)
            self._connection.rpush(self.FILE_RESULT_QUEUE, message_json)

            logger.info(f"📤 [FILE_RESULT] Published: {celery_task_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to publish file result: {e}")
            return False

    def get_file_result(self, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """
        Get file processing result from queue (non-blocking if timeout=0)
        Called by: knowledgebase_ingestion
        Returns: Parsed message dict or None
        """
        if not self.is_available():
            return None

        try:
            # BLPOP with timeout (0 = non-blocking)
            result = self._connection.blpop(self.FILE_RESULT_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                message = json.loads(message_json)
                logger.info(f"📥 [FILE_RESULT] Received: file_id={message.get('file_id')}, status={message.get('status')}")
                return message
            return None

        except Exception as e:
            logger.error(f"❌ Error getting file result: {e}")
            return None

    # ========== WEBSITE PROCESSING MESSAGES ==========

    def publish_web_task(self, celery_task_id: str) -> bool:
        """
        Publish website scraping task to queue
        Called by: knowledgebase_ingestion
        Read by: celery-web-worker
        """
        if not self.is_available():
            logger.error("❌ Redis not available, cannot publish task")
            return False

        try:
            message = {
                "type": "WEB_SCRAPE",
                "celery_task_id": celery_task_id
            }

            message_json = json.dumps(message)
            self._connection.rpush(self.WEB_TASK_QUEUE, message_json)

            logger.info(f"📤 [WEB] Published task: {celery_task_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to publish web task: {e}")
            return False

    def get_web_task(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """
        Get web task from queue (blocking pop)
        Called by: celery-web-worker
        Returns: Parsed message dict or None
        """
        if not self.is_available():
            return None

        try:
            result = self._connection.blpop(self.WEB_TASK_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                message = json.loads(message_json)
                logger.info(f"📥 [WEB] Received task: website_id={message.get('website_id')}")
                return message
            return None

        except Exception as e:
            logger.error(f"❌ Error getting web task: {e}")
            return None

    def publish_web_result(
        self,
        website_id: int,
        celery_task_id: str,
        status: str,  # 'completed', 'failed', 'cancelled'
        result: Dict[str, Any] = None,
        error: str = None
    ) -> bool:
        """
        Publish website scraping result
        Called by: celery-web-worker
        Read by: knowledgebase_ingestion
        """
        if not self.is_available():
            logger.error("❌ Redis not available, cannot publish result")
            return False

        try:
            message = {
                "type": "WEB_RESULT",
                "website_id": website_id,
                "celery_task_id": celery_task_id,
                "status": status,
                "result": result or {},
                "error": error,
                "timestamp": datetime.utcnow().isoformat()
            }

            message_json = json.dumps(message)
            self._connection.rpush(self.WEB_RESULT_QUEUE, message_json)

            logger.info(f"📤 [WEB_RESULT] Published: website_id={website_id}, status={status}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to publish web result: {e}")
            return False

    def get_web_result(self, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """
        Get website scraping result from queue (non-blocking if timeout=0)
        Called by: knowledgebase_ingestion
        Returns: Parsed message dict or None
        """
        if not self.is_available():
            return None

        try:
            result = self._connection.blpop(self.WEB_RESULT_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                message = json.loads(message_json)
                logger.info(f"📥 [WEB_RESULT] Received: website_id={message.get('website_id')}, status={message.get('status')}")
                return message
            return None

        except Exception as e:
            logger.error(f"❌ Error getting web result: {e}")
            return None

    # ========== TASK CANCELLATION & QUEUE CLEARING ==========

    def set_task_cancelled(self, task_id: str) -> bool:
        """
        Set Redis cancel flag for a task (replaces celery_app.control.revoke).
        Checked by processing_service at cancellation points.
        """
        if not self.is_available():
            return False

        try:
            self._connection.set(f"task_cancelled:{task_id}", "1", ex=3600)
            logger.info(f"🛑 Set cancellation flag for task: {task_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error setting task cancellation flag: {e}")
            return False

    def clear_file_task_queue(self) -> bool:
        """Remove all pending file tasks from queue (replaces celery queue purge)."""
        if not self.is_available():
            return False

        try:
            self._connection.delete(self.FILE_TASK_QUEUE)
            logger.info(f"✅ Cleared file task queue: {self.FILE_TASK_QUEUE}")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing file task queue: {e}")
            return False

    def clear_web_task_queue(self) -> bool:
        """Remove all pending web tasks from queue (replaces celery queue purge)."""
        if not self.is_available():
            return False

        try:
            self._connection.delete(self.WEB_TASK_QUEUE)
            logger.info(f"✅ Cleared web task queue: {self.WEB_TASK_QUEUE}")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing web task queue: {e}")
            return False

    # ========== UTILITY METHODS ==========

    def get_queue_length(self, queue_name: str) -> int:
        """Get number of messages in queue"""
        if not self.is_available():
            return 0

        try:
            return self._connection.llen(queue_name)
        except Exception as e:
            logger.error(f"❌ Error getting queue length: {e}")
            return 0

    def clear_queue(self, queue_name: str) -> bool:
        """Clear all messages from queue"""
        if not self.is_available():
            return False

        try:
            self._connection.delete(queue_name)
            logger.info(f"✅ Cleared queue: {queue_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing queue: {e}")
            return False


# Global instance
redis_message_queue = RedisMessageQueue()
