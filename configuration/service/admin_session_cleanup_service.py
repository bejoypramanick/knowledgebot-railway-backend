"""
Admin Session Cleanup Service
Periodically expires old sessions and deletes archived action logs
"""

import asyncio
from typing import Optional
from datetime import datetime

from shared.otel_logger import get_otel_logger
from ..dao.admin_session_dao import AdminSessionDAO
from ..dao.admin_action_dao import AdminActionDAO

logger = get_otel_logger("admin_session_cleanup", "configuration")


class AdminSessionCleanupService:
    """Service for cleaning up expired sessions and old action logs"""

    def __init__(
        self,
        session_retention_days: int = 90,
        action_retention_days: int = 365,
    ):
        """
        Initialize cleanup service with retention policies.

        Args:
            session_retention_days: How many days to keep session records (default: 90)
            action_retention_days: How many days to keep action logs (default: 365)
        """
        self.session_dao = AdminSessionDAO()
        self.action_dao = AdminActionDAO()
        self.session_retention_days = session_retention_days
        self.action_retention_days = action_retention_days
        self.is_running = False

    async def run_once(self) -> dict:
        """Run cleanup operations once and return results."""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "sessions_expired": 0,
            "sessions_deleted": 0,
            "actions_deleted": 0,
            "errors": []
        }

        try:
            # Expire old sessions
            expired_count = await self.session_dao.expire_old_sessions()
            results["sessions_expired"] = expired_count
            logger.info(f"✅ Expired {expired_count} old sessions")

            # Clean up session records
            deleted_sessions = await self.session_dao.cleanup_old_sessions(
                days=self.session_retention_days
            )
            results["sessions_deleted"] = deleted_sessions
            logger.info(f"✅ Deleted {deleted_sessions} old session records")

            # Clean up action logs
            deleted_actions = await self.action_dao.cleanup_old_actions(
                days=self.action_retention_days
            )
            results["actions_deleted"] = deleted_actions
            logger.info(f"✅ Deleted {deleted_actions} old action logs")

        except Exception as e:
            error_msg = f"Cleanup error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            results["errors"].append(error_msg)

        return results

    async def start_periodic_cleanup(self, interval_minutes: int = 5):
        """
        Start periodic cleanup job.

        Args:
            interval_minutes: How often to run cleanup (default: 5 minutes)
        """
        if self.is_running:
            logger.warning("⚠️ Cleanup service is already running")
            return

        self.is_running = True
        logger.info(f"🚀 Starting admin session cleanup service (interval: {interval_minutes} min)")

        interval_seconds = interval_minutes * 60

        try:
            while self.is_running:
                try:
                    await self.run_once()
                except Exception as e:
                    logger.error(f"❌ Periodic cleanup failed: {e}")

                # Wait for next interval
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("🛑 Admin session cleanup service stopped")
            self.is_running = False
        except Exception as e:
            logger.error(f"❌ Cleanup service error: {e}")
            self.is_running = False

    def stop_periodic_cleanup(self):
        """Stop the periodic cleanup service."""
        logger.info("🛑 Stopping admin session cleanup service")
        self.is_running = False


# Global cleanup service instance
_cleanup_service: Optional[AdminSessionCleanupService] = None


def get_cleanup_service(
    session_retention_days: int = 90,
    action_retention_days: int = 365,
) -> AdminSessionCleanupService:
    """Get or create global cleanup service instance."""
    global _cleanup_service

    if _cleanup_service is None:
        _cleanup_service = AdminSessionCleanupService(
            session_retention_days=session_retention_days,
            action_retention_days=action_retention_days,
        )

    return _cleanup_service


async def start_cleanup_service(interval_minutes: int = 5):
    """Start the global cleanup service."""
    service = get_cleanup_service()
    await service.start_periodic_cleanup(interval_minutes=interval_minutes)


def stop_cleanup_service():
    """Stop the global cleanup service."""
    if _cleanup_service:
        _cleanup_service.stop_periodic_cleanup()
