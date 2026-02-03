"""
Widget Configuration Service for Widget Management
Provides business logic layer for widget configuration operations
"""
from typing import Any, Dict, List, Optional

from configuration.core.otel_logger import get_otel_logger
from configuration.dao.widget_config_dao import WidgetConfigDAO

logger = get_otel_logger("widget_config_service", "configuration")

class WidgetConfigService:
    """Service layer for widget configuration operations"""

    def __init__(self):
        self._widget_dao = WidgetConfigDAO()
    
    # Widget Configuration Methods
   
    async def get_widget_config(self):
        """Get complete widget configuration with all data transformations"""
        try:
            # Get main widget configuration
            widget_config = await self._widget_dao.get_widget_config()
            if not widget_config:
                widget_config = {}
            
            # Get suggested messages
            suggested_messages = await self._widget_dao.get_suggested_messages()
            
            # Transform configuration for frontend
            transformed_config = {
                "display_name": widget_config.get("display_name", "Chat Assistant"),
                "initial_message": widget_config.get("initial_message", "Hello! How can I help you today?"),
                "auto_show_duration": widget_config.get("auto_show_duration", 5),
                "keep_showing_suggested": widget_config.get("keep_showing_suggested", True),
                "theme": widget_config.get("theme", "light"),
                "primary_color": widget_config.get("primary_color", "#3b82f6"),
                "use_primary_for_header": widget_config.get("use_primary_for_header", True),
                "chat_bubble_color": widget_config.get("chat_bubble_color", "#f3f4f6"),
                "align_bubble": widget_config.get("align_bubble", "bottom-right"),
                "profile_picture_url": widget_config.get("profile_picture_url", ""),
                "chat_icon_url": widget_config.get("chat_icon_url", ""),
                "chat_header": widget_config.get("chat_header", ""),
                "chat_welcome_message": widget_config.get("chat_welcome_message", ""),
                "suggested_messages": suggested_messages,
                "profile_zoom": widget_config.get("profile_zoom", 100),
                "chat_icon_zoom": widget_config.get("chat_icon_zoom", 100)
            }
            
            logger.info("✅ Widget config retrieved successfully")
            return transformed_config
            
        except Exception as e:
            logger.error(f"Error getting widget configuration: {e}")
            raise


    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration"""
        try:
            await self._widget_dao.update_widget_config(config_data)
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise
    

    async def update_widget_image(self, image_type: str, data_url: str, filename: str) -> bool:
        """Update widget image (profile, chatIcon, or headerIcon)"""
        try:
            result = await self._widget_dao.update_widget_image(image_type, data_url, filename)
            logger.info(f"✅ Widget image '{image_type}' updated successfully")
            return result
        except Exception as e:
            logger.error(f"Error updating widget image: {e}")
            raise
