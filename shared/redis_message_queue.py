"""
Redis Message Queue Service
Bidirectional messaging between knowledgebase_ingestion and workers
Handles task dispatch and result reporting
"""
import os
import json
import redis
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from shared.otel_logger import get_otel_logger
from shared.redis_factory import resolve_redis_url

logger = get_otel_logger("redis_message_queue", "messaging")


def _redact_redis_url(redis_url: str) -> str:
    """Redact sensitive info (password) from Redis URL for logging."""
    if not redis_url:
        return redis_url
    try:
        parsed = urlparse(redis_url)
        # Redact password if present
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            redacted = urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            return redacted
        return redis_url
    except Exception:
        # If parsing fails, return original
        return redis_url


class RedisMessageQueue:
    """Redis-based message queue for inter-service communication"""

    # Queue names
    FILE_TASK_QUEUE = "file_processing_tasks"      # knowledgebase → file-worker
    FILE_RESULT_QUEUE = "file_processing_results"  # file-worker → knowledgebase
    WEB_TASK_QUEUE = "web_crawling_tasks"          # knowledgebase → web-worker
    WEB_RESULT_QUEUE = "web_crawling_results"      # web-worker → knowledgebase
    EXTRACT_TASK_QUEUE = "kreuzberg_extraction_tasks"      # workers → kreuzberg-worker
    EXTRACT_RESULT_QUEUE = "kreuzberg_extraction_results"  # kreuzberg-worker → workers

    def __init__(self):
        """Initialize Redis connections for both databases"""
        self.file_redis_url = resolve_redis_url(
            primary_env_var='file_task_queue',
            db_env_var='FILE_TASK_QUEUE_REDIS_DB',
            default_db=0,
        )
        self.web_redis_url = resolve_redis_url(
            primary_env_var='web_task_queue',
            db_env_var='WEB_TASK_QUEUE_REDIS_DB',
            default_db=1,
        )

        self._file_connection = None
        self._web_connection = None
        self._init_connections()

    def _init_connections(self):
        """Initialize Redis connections for both databases"""
        if self.file_redis_url:
            try:
                self._file_connection = redis.from_url(self.file_redis_url)
                self._file_connection.ping()
                logger.info(f"✅ File Redis connection initialized: {_redact_redis_url(self.file_redis_url)}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize file Redis connection: {e}")
                self._file_connection = None

        if self.web_redis_url:
            try:
                self._web_connection = redis.from_url(self.web_redis_url)
                self._web_connection.ping()
                logger.info(f"✅ Web Redis connection initialized: {_redact_redis_url(self.web_redis_url)}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize web Redis connection: {e}")
                self._web_connection = None

    def is_available(self) -> bool:
        """Check if at least one Redis connection is available"""
        return (
            self._file_connection is not None
            or self._web_connection is not None
        )

    def _is_file_available(self) -> bool:
        """Check if file Redis connection is available"""
        return self._file_connection is not None

    def _is_web_available(self) -> bool:
        """Check if web Redis connection is available"""
        return self._web_connection is not None

    def _get_connection(self, worker_type: str):
        """Return the Redis connection for the requested worker type."""
        return self._web_connection if worker_type == "web" else self._file_connection

    def _set_connection(self, worker_type: str, connection) -> None:
        """Store a Redis connection for the requested worker type."""
        if worker_type == "web":
            self._web_connection = connection
        else:
            self._file_connection = connection

    def _redis_url_for_worker(self, worker_type: str) -> Optional[str]:
        """Return the Redis URL for the requested worker type."""
        return self.web_redis_url if worker_type == "web" else self.file_redis_url

    def _reset_connection(self, worker_type: str):
        """Reconnect after Railway/Redis closes an idle or stale socket."""
        redis_url = self._redis_url_for_worker(worker_type)
        if not redis_url:
            self._set_connection(worker_type, None)
            return None

        current = self._get_connection(worker_type)
        if current is not None:
            try:
                current.close()
            except Exception:
                pass

        try:
            connection = redis.from_url(redis_url)
            connection.ping()
            self._set_connection(worker_type, connection)
            logger.info(f"✅ Reconnected {worker_type} Redis: {_redact_redis_url(redis_url)}")
            return connection
        except Exception as e:
            logger.error(f"❌ Failed to reconnect {worker_type} Redis: {e}")
            self._set_connection(worker_type, None)
            return None

    def _with_redis_retry(self, worker_type: str, operation_name: str, operation):
        """Run a Redis operation, reconnecting once if the socket is stale."""
        connection = self._get_connection(worker_type)
        if connection is None:
            connection = self._reset_connection(worker_type)
            if connection is None:
                return None

        try:
            return operation(connection)
        except (redis.ConnectionError, redis.TimeoutError, TimeoutError, OSError) as e:
            logger.warning(
                f"⚠️ Redis {operation_name} failed for {worker_type}; reconnecting and retrying once: {e}"
            )
            connection = self._reset_connection(worker_type)
            if connection is None:
                return None
            try:
                return operation(connection)
            except Exception as retry_error:
                logger.error(f"❌ Redis {operation_name} retry failed for {worker_type}: {retry_error}")
                return None
        except Exception as e:
            logger.error(f"❌ Redis {operation_name} failed for {worker_type}: {e}")
            return None

    # ========== FILE PROCESSING MESSAGES ==========

    def publish_file_task(
        self,
        celery_task_id: str,
        file_id: Optional[str] = None
    ) -> bool:
        """
        Publish file processing task to queue
        Called by: knowledgebase_ingestion
        Read by: celery-file-worker
        Note: file_id is optional - worker will create DB record and assign it
        """
        if not self._is_file_available():
            logger.error("❌ File Redis not available, cannot publish task")
            return False

        try:
            message = {
                "type": "FILE_PROCESS",
                "celery_task_id": celery_task_id
            }

            message_json = json.dumps(message)
            self._file_connection.rpush(self.FILE_TASK_QUEUE, message_json)

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
        if not self._is_file_available():
            return None

        try:
            # BLPOP with timeout in seconds
            result = self._file_connection.blpop(self.FILE_TASK_QUEUE, timeout=timeout)
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
        if not self._is_file_available():
            logger.error("❌ File Redis not available, cannot publish result")
            return False

        try:
            message = {
                "type": "FILE_RESULT",
                "celery_task_id": celery_task_id
            }

            message_json = json.dumps(message)
            self._file_connection.rpush(self.FILE_RESULT_QUEUE, message_json)

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
        if not self._is_file_available():
            return None

        try:
            # BLPOP with timeout (0 = non-blocking)
            result = self._file_connection.blpop(self.FILE_RESULT_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                message = json.loads(message_json)
                logger.info(f"📥 [FILE_RESULT] Received: file_id={message.get('file_id')}, status={message.get('status')}")
                return message
            return None

        except Exception as e:
            logger.error(f"❌ Error getting file result: {e}")
            return None

    # ========== KREUZBERG EXTRACTION MESSAGES ==========

    def publish_extract_task(self, message: Dict[str, Any]) -> bool:
        """Publish an extraction job for the dedicated Kreuzberg worker."""
        worker_type = message.get("worker_type", "file")
        message_json = json.dumps(message)

        def _publish(connection):
            connection.rpush(self.EXTRACT_TASK_QUEUE, message_json)
            return True

        published = self._with_redis_retry(worker_type, "publish extraction task", _publish)
        if published:
            logger.info(
                f"📤 [EXTRACT] Published {worker_type} task:"
                f" job_id={message.get('job_id')}"
                f" document_id={message.get('document_id')}"
            )
            return True

        logger.error(f"❌ {worker_type} Redis not available, cannot publish extraction task")
        return False

    def get_extract_task(self, timeout: int = 1, worker_type: str = "file") -> Optional[Dict[str, Any]]:
        """Get an extraction task from the dedicated Kreuzberg worker queue."""
        def _pop(connection):
            result = connection.blpop(self.EXTRACT_TASK_QUEUE, timeout=timeout)
            if result:
                _, message_json = result
                return json.loads(message_json)
            return None

        message = self._with_redis_retry(worker_type, "get extraction task", _pop)
        if message:
            logger.info(
                f"📥 [EXTRACT] Received {worker_type} task:"
                f" job_id={message.get('job_id')}"
                f" document_id={message.get('document_id')}"
            )
        return message

    def publish_extract_result(self, message: Dict[str, Any]) -> bool:
        """Publish the extraction result for downstream workers."""
        worker_type = message.get("worker_type", "file")
        queue_name = message.get("reply_channel") or self.EXTRACT_RESULT_QUEUE
        message_json = json.dumps(message)

        def _publish(connection):
            connection.rpush(queue_name, message_json)
            return True

        published = self._with_redis_retry(worker_type, "publish extraction result", _publish)
        if published:
            logger.info(
                f"📤 [EXTRACT_RESULT] Published {worker_type} result:"
                f" job_id={message.get('job_id')}"
                f" status={message.get('status')}"
            )
            return True

        logger.error(f"❌ {worker_type} Redis not available, cannot publish extraction result")
        return False

    def get_extract_result(self, timeout: int = 0, queue_name: Optional[str] = None, worker_type: str = "file") -> Optional[Dict[str, Any]]:
        """Get an extraction result message."""
        result_queue = queue_name or self.EXTRACT_RESULT_QUEUE

        def _pop(connection):
            result = connection.blpop(result_queue, timeout=timeout)
            if result:
                _, message_json = result
                return json.loads(message_json)
            return None

        message = self._with_redis_retry(worker_type, "get extraction result", _pop)
        if message:
            logger.info(
                f"📥 [EXTRACT_RESULT] Received {worker_type} result:"
                f" job_id={message.get('job_id')}"
                f" status={message.get('status')}"
            )
        return message

    # ========== WEBSITE PROCESSING MESSAGES ==========

    def publish_web_task(
        self,
        celery_task_id: str,
        website_id: str = None,
        url: str = None,
        max_depth: int = 2,
        max_pages: int = 100,
        max_concurrent: int = 10,
        delay_between_requests: float = 0.0,
        user_email: str = "admin",
        options: dict = None
    ) -> bool:
        """
        Publish website scraping task to queue with full task data.
        Called by: knowledgebase_ingestion
        Read by: celery-web-worker
        """
        if not self._is_web_available():
            logger.error("❌ Web Redis not available, cannot publish task")
            return False

        try:
            message = {
                "type": "WEB_SCRAPE",
                "celery_task_id": celery_task_id,
                "website_id": website_id,
                "url": url,
                "max_depth": max_depth,
                "max_pages": max_pages,
                "max_concurrent": max_concurrent,
                "delay_between_requests": delay_between_requests,
                "user_email": user_email,
                "options": options or {}
            }

            message_json = json.dumps(message)
            self._web_connection.rpush(self.WEB_TASK_QUEUE, message_json)

            logger.info(f"📤 [WEB] Published task: {celery_task_id} for {url}")
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
        if not self._is_web_available():
            return None

        try:
            result = self._web_connection.blpop(self.WEB_TASK_QUEUE, timeout=timeout)
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
        website_id: str,
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
        if not self._is_web_available():
            logger.error("❌ Web Redis not available, cannot publish result")
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
            self._web_connection.rpush(self.WEB_RESULT_QUEUE, message_json)

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
        if not self._is_web_available():
            return None

        try:
            result = self._web_connection.blpop(self.WEB_RESULT_QUEUE, timeout=timeout)
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
        Sets flag in both databases to ensure it's found regardless of task type.
        """
        success = False

        # Try file Redis
        if self._is_file_available():
            try:
                self._file_connection.set(f"task_cancelled:{task_id}", "1", ex=3600)
                success = True
            except Exception as e:
                logger.error(f"❌ Error setting cancellation flag in file Redis: {e}")

        # Try web Redis
        if self._is_web_available():
            try:
                self._web_connection.set(f"task_cancelled:{task_id}", "1", ex=3600)
                success = True
            except Exception as e:
                logger.error(f"❌ Error setting cancellation flag in web Redis: {e}")

        if success:
            logger.info(f"🛑 Set cancellation flag for task: {task_id}")
        else:
            logger.error(f"❌ Could not set cancellation flag in any Redis connection: {task_id}")

        return success

    def clear_file_task_queue(self) -> bool:
        """Remove all pending file tasks from queue (replaces celery queue purge)."""
        if not self._is_file_available():
            return False

        try:
            self._file_connection.delete(self.FILE_TASK_QUEUE)
            logger.info(f"✅ Cleared file task queue from DB 0: {self.FILE_TASK_QUEUE}")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing file task queue: {e}")
            return False

    def clear_web_task_queue(self) -> bool:
        """Remove all pending web tasks from queue (replaces celery queue purge)."""
        if not self._is_web_available():
            return False

        try:
            self._web_connection.delete(self.WEB_TASK_QUEUE)
            logger.info(f"✅ Cleared web task queue from DB 1: {self.WEB_TASK_QUEUE}")
            return True
        except Exception as e:
            logger.error(f"❌ Error clearing web task queue: {e}")
            return False

    # ========== UTILITY METHODS ==========

    def get_queue_length(self, queue_name: str) -> int:
        """Get number of messages in queue (checks both databases)"""
        total = 0

        if self._is_file_available():
            try:
                total += self._file_connection.llen(queue_name)
            except Exception as e:
                logger.error(f"❌ Error getting queue length from file Redis: {e}")

        if self._is_web_available():
            try:
                total += self._web_connection.llen(queue_name)
            except Exception as e:
                logger.error(f"❌ Error getting queue length from web Redis: {e}")

        return total

    def clear_queue(self, queue_name: str) -> bool:
        """Clear all messages from queue (clears from both databases)"""
        success = False

        if self._is_file_available():
            try:
                self._file_connection.delete(queue_name)
                success = True
            except Exception as e:
                logger.error(f"❌ Error clearing queue from file Redis: {e}")

        if self._is_web_available():
            try:
                self._web_connection.delete(queue_name)
                success = True
            except Exception as e:
                logger.error(f"❌ Error clearing queue from web Redis: {e}")

        if success:
            logger.info(f"✅ Cleared queue: {queue_name}")
        else:
            logger.error(f"❌ Could not clear queue {queue_name} from any Redis connection")

        return success


# Global instance
redis_message_queue = RedisMessageQueue()
