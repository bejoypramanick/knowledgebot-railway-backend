"""
Keep-Alive Service for Railway Deployments
Prevents PostgreSQL and services from sleeping due to inactivity
Runs as a background task
"""

import asyncio
from datetime import datetime
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session

logger = get_otel_logger("keepalive_service", "shared")


class KeepAliveService:
    """Service to keep database and microservices alive"""

    def __init__(self, interval_seconds: int = 300):  # 5 minutes
        self.interval_seconds = interval_seconds
        self.task = None
        self.is_running = False

    async def start(self):
        """Start the keep-alive background task"""
        if self.is_running:
            logger.warning("Keep-alive service already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run())
        logger.info(f"✅ Keep-alive service started (interval: {self.interval_seconds}s)")

    async def stop(self):
        """Stop the keep-alive background task"""
        if not self.is_running:
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Keep-alive service stopped")

    async def _run(self):
        """Background task to periodically ping database and services"""
        while self.is_running:
            try:
                await asyncio.sleep(self.interval_seconds)

                if not self.is_running:
                    break

                await self._ping_database()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Keep-alive service error: {e}", extra={"traceback": True})
                # Continue trying even if ping fails
                await asyncio.sleep(10)

    async def _ping_database(self):
        """Ping database with simple health check"""
        try:
            start_time = datetime.now()

            async with get_db_session() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"🔄 Keep-alive ping: database OK ({elapsed_ms:.0f}ms)")

        except Exception as e:
            logger.warning(f"⚠️ Keep-alive ping failed: {e}")


# Global instance
_keepalive_service = KeepAliveService(interval_seconds=300)  # 5 minutes


async def start_keepalive_service(interval_seconds: int = 300):
    """Initialize and start the keep-alive service"""
    _keepalive_service.interval_seconds = interval_seconds
    await _keepalive_service.start()


async def stop_keepalive_service():
    """Stop the keep-alive service"""
    await _keepalive_service.stop()
