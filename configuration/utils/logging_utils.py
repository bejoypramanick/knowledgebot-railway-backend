from shared.logging_config import get_railway_logger

from ..service.configuration_service import configuration_service

logger = get_railway_logger(__name__)

async def log_configuration_change(user_email: str, action: str, details: dict, ip_address: str = None):
    """Log configuration changes for audit purposes"""
    try:
        # Use service to log configuration change
        await configuration_service.log_audit_change(user_email, action, details, ip_address)
        logger.info(f"Configuration change logged: {action} by {user_email}")
    except Exception as e:
        logger.error(f"Failed to log configuration change: {e}")
