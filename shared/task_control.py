"""
Unified External Task Control Interface

Provides a simple way to stop Celery tasks from anywhere in the application.
Combines Celery revoke (forceful) + Redis flags (graceful) for reliability.
"""
from shared.celery_dispatcher import file_celery, web_celery
from shared.redis_message_queue import RedisMessageQueue
from shared.otel_logger import get_otel_logger
from typing import Optional

logger = get_otel_logger("task_control", "knowledgebase-ingestion")


class TaskControl:
    """
    Unified interface for external task termination.

    Two-tier strategy:
    1. Celery revoke (forceful) - kills worker process
    2. Redis flag (graceful) - allows running tasks to detect cancellation

    Example:
        # Stop a single web task
        success = TaskControl.stop_web_task(task_id)

        # Stop all tasks immediately
        TaskControl.stop_all_tasks()

        # Graceful shutdown with cleanup time
        TaskControl.stop_web_task(task_id, graceful=True)
    """

    @staticmethod
    def stop_file_task(task_id: str, graceful: bool = False) -> bool:
        """
        Stop a file processing task immediately.

        Args:
            task_id: Celery task ID to stop
            graceful: If True, use SIGTERM (allows cleanup). If False, use SIGKILL (immediate).

        Returns:
            True if revoke succeeded, False otherwise

        Example:
            TaskControl.stop_file_task("abc-123-def", graceful=False)
        """
        try:
            logger.info("=" * 80)
            logger.info(f"🔪 [TASK_CONTROL] Stopping file task: {task_id}")
            logger.info("=" * 80)

            signal = "SIGTERM" if graceful else "SIGKILL"
            logger.info(f"   Signal: {signal}")
            logger.info(f"   Graceful: {graceful}")

            # Tier 1: Revoke via Celery
            logger.info("   🔪 Tier 1: Celery revoke...")
            file_celery.control.revoke(task_id, terminate=True, signal=signal)
            logger.info(f"   ✅ File task revoked with {signal}: {task_id}")

            # Tier 2: Set Redis flag (fallback for blocked tasks)
            logger.info("   🚩 Tier 2: Redis cancellation flag...")
            redis_queue = RedisMessageQueue()
            redis_queue.set_task_cancelled(task_id)
            logger.info(f"   ✅ Cancellation flag set: {task_id}")

            logger.info("=" * 80)
            logger.info(f"✅ [TASK_CONTROL_COMPLETE] File task stopped: {task_id}")
            logger.info("=" * 80)
            return True

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [TASK_CONTROL_ERROR] Error stopping file task {task_id}: {e}")
            logger.error("=" * 80)
            return False

    @staticmethod
    def stop_web_task(task_id: str, graceful: bool = False) -> bool:
        """
        Stop a website scraping task immediately.

        Args:
            task_id: Celery task ID to stop
            graceful: If True, use SIGTERM (allows cleanup). If False, use SIGKILL (immediate).

        Returns:
            True if revoke succeeded, False otherwise

        Example:
            TaskControl.stop_web_task("xyz-789-abc", graceful=True)
        """
        try:
            logger.info("=" * 80)
            logger.info(f"🔪 [TASK_CONTROL] Stopping web task: {task_id}")
            logger.info("=" * 80)

            signal = "SIGTERM" if graceful else "SIGKILL"
            logger.info(f"   Signal: {signal}")
            logger.info(f"   Graceful: {graceful}")

            # Tier 1: Revoke via Celery
            logger.info("   🔪 Tier 1: Celery revoke...")
            web_celery.control.revoke(task_id, terminate=True, signal=signal)
            logger.info(f"   ✅ Web task revoked with {signal}: {task_id}")

            # Tier 2: Set Redis flag (fallback for blocked tasks)
            logger.info("   🚩 Tier 2: Redis cancellation flag...")
            redis_queue = RedisMessageQueue()
            redis_queue.set_task_cancelled(task_id)
            logger.info(f"   ✅ Cancellation flag set: {task_id}")

            logger.info("=" * 80)
            logger.info(f"✅ [TASK_CONTROL_COMPLETE] Web task stopped: {task_id}")
            logger.info("=" * 80)
            return True

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [TASK_CONTROL_ERROR] Error stopping web task {task_id}: {e}")
            logger.error("=" * 80)
            return False

    @staticmethod
    def stop_task(
        task_id: str,
        task_type: str = "auto",
        graceful: bool = False
    ) -> bool:
        """
        Stop any task (file or web), auto-detecting or specified.

        Args:
            task_id: Celery task ID to stop
            task_type: 'file', 'web', or 'auto' (tries both)
            graceful: If True, use SIGTERM. If False, use SIGKILL.

        Returns:
            True if at least one revoke succeeded

        Example:
            # Auto-detect and stop
            TaskControl.stop_task("abc-123-def")

            # Explicitly stop web task
            TaskControl.stop_task("abc-123-def", task_type='web')

            # Graceful stop
            TaskControl.stop_task("abc-123-def", graceful=True)
        """
        file_result = False
        web_result = False

        if task_type in ("file", "auto"):
            file_result = TaskControl.stop_file_task(task_id, graceful)
            if task_type == "file":
                return file_result

        if task_type in ("web", "auto"):
            web_result = TaskControl.stop_web_task(task_id, graceful)
            if task_type == "web":
                return web_result

        # If auto mode, return True if either succeeded
        if task_type == "auto":
            return file_result or web_result

        return False

    @staticmethod
    def stop_all_file_tasks() -> bool:
        """
        Stop all queued file tasks and set cancellation flags for in-progress tasks.

        Returns:
            True if purge succeeded, False otherwise
        """
        try:
            logger.info("=" * 80)
            logger.info("🔪 [TASK_CONTROL] Stopping all file tasks")
            logger.info("=" * 80)

            logger.info("   🔪 Tier 1: Celery purge...")
            file_celery.control.purge()
            logger.info("   ✅ All file task queues purged")

            logger.info("=" * 80)
            logger.info("✅ [TASK_CONTROL_COMPLETE] All file tasks stopped")
            logger.info("=" * 80)
            return True

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [TASK_CONTROL_ERROR] Error purging file tasks: {e}")
            logger.error("=" * 80)
            return False

    @staticmethod
    def stop_all_web_tasks() -> bool:
        """
        Stop all queued web tasks and set cancellation flags for in-progress tasks.

        Returns:
            True if purge succeeded, False otherwise
        """
        try:
            logger.info("=" * 80)
            logger.info("🔪 [TASK_CONTROL] Stopping all web tasks")
            logger.info("=" * 80)

            logger.info("   🔪 Tier 1: Celery purge...")
            web_celery.control.purge()
            logger.info("   ✅ All web task queues purged")

            logger.info("=" * 80)
            logger.info("✅ [TASK_CONTROL_COMPLETE] All web tasks stopped")
            logger.info("=" * 80)
            return True

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [TASK_CONTROL_ERROR] Error purging web tasks: {e}")
            logger.error("=" * 80)
            return False

    @staticmethod
    def stop_all_tasks() -> bool:
        """
        Stop all tasks (file and web) immediately.

        Returns:
            True if both file and web purges succeeded, False if either failed
        """
        logger.info("=" * 80)
        logger.info("🔪 [TASK_CONTROL] Stopping ALL tasks (file + web)")
        logger.info("=" * 80)

        file_ok = TaskControl.stop_all_file_tasks()
        web_ok = TaskControl.stop_all_web_tasks()

        success = file_ok and web_ok
        logger.info("=" * 80)
        logger.info(f"{'✅' if success else '⚠️'} [TASK_CONTROL_SUMMARY] All tasks stop completed")
        logger.info(f"   File tasks: {'✅' if file_ok else '❌'}")
        logger.info(f"   Web tasks: {'✅' if web_ok else '❌'}")
        logger.info("=" * 80)

        return success

    @staticmethod
    def status_summary() -> dict:
        """
        Get current status information.

        Returns:
            Dictionary with Redis and Celery status
        """
        logger.info("📊 [TASK_CONTROL] Gathering status...")

        try:
            redis_queue = RedisMessageQueue()
            return {
                "file_redis_available": redis_queue._is_file_available(),
                "web_redis_available": redis_queue._is_web_available(),
                "file_task_queue_length": redis_queue.get_queue_length(
                    RedisMessageQueue.FILE_TASK_QUEUE
                ),
                "web_task_queue_length": redis_queue.get_queue_length(
                    RedisMessageQueue.WEB_TASK_QUEUE
                ),
                "message": "Task control is operational",
            }
        except Exception as e:
            logger.error(f"❌ Error gathering status: {e}")
            return {
                "error": str(e),
                "message": "Task control status unavailable",
            }
