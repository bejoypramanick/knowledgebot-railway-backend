"""Background scheduler for health monitoring checks."""
import asyncio
import logging
from shared.otel_logger import get_otel_logger
from typing import Optional

from health_monitoring.core.config import settings
from health_monitoring.service.health_monitoring_service import HealthMonitoringService

logger = get_otel_logger(__name__, "health_monitoring")


class HealthCheckerScheduler:
    """Background task scheduler for health checks."""

    _instance: Optional['HealthCheckerScheduler'] = None
    _task: Optional[asyncio.Task] = None
    _running: bool = False

    @classmethod
    def get_instance(cls) -> 'HealthCheckerScheduler':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = HealthCheckerScheduler()
        return cls._instance

    async def start(self):
        """Start the health check scheduler."""
        if self._running:
            logger.warning("⚠️ Health check scheduler already running")
            return

        logger.info(f"🚀 Starting health check scheduler (interval: {settings.health_check_interval_seconds}s)")
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        """Stop the health check scheduler."""
        if not self._running:
            logger.warning("⚠️ Health check scheduler not running")
            return

        logger.info("🛑 Stopping health check scheduler")
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("✅ Health check scheduler stopped")

    async def _run(self):
        """Main scheduler loop."""
        first_run = True

        while self._running:
            try:
                # Run immediately on first startup, then wait for next interval
                if not first_run:
                    await asyncio.sleep(settings.health_check_interval_seconds)

                if not self._running:
                    break

                logger.info("🔍 Running health checks...")
                await HealthMonitoringService.check_all_services()
                logger.info("✅ Health checks completed")

                first_run = False

            except asyncio.CancelledError:
                logger.info("🛑 Health check scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in health check scheduler: {e}")
                # Continue running even if a check fails
                first_run = False

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running and (self._task is not None and not self._task.done())


# Global instance access
def get_scheduler() -> HealthCheckerScheduler:
    """Get the health checker scheduler instance."""
    return HealthCheckerScheduler.get_instance()
