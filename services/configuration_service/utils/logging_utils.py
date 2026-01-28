import logging
import json
from datetime import datetime
from services.configuration_service.core.database import get_db_connection

logger = logging.getLogger(__name__)

async def log_configuration_change(user_email: str, action: str, details: dict, ip_address: str = None):
    """Log configuration changes for audit purposes"""
    try:
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO configuration_audit_log
                (user_email, action, details, ip_address, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_email, action, json.dumps(details), ip_address, datetime.utcnow()
            )
    except Exception as e:
        logger.warning(f"Failed to log configuration change: {e}")
