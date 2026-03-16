"""
Widget Configuration Service for Widget Management
Provides business logic layer for widget configuration operations
"""
from typing import Any, Dict, List, Optional, Tuple

from shared.otel_logger import get_otel_logger
from configuration.dao.widget_config_dao import WidgetConfigDAO

logger = get_otel_logger("widget_config_service", "configuration")

class WidgetConfigService:
    """Service layer for widget configuration operations"""

    def __init__(self):
        self._widget_config_dao = WidgetConfigDAO()
    
    # Widget Configuration Methods
   
    async def get_widget_config(self):
        """Get complete widget configuration with all data transformations"""
        try:
            # Get main widget configuration
            widget_config = await self._widget_config_dao.get_widget_config()
            if not widget_config:
                widget_config = {}
            
            # Get suggested messages
            suggested_messages = await self._widget_config_dao.get_suggested_messages()
            
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
            logger.info("=" * 100)
            logger.info("🔄 UPDATING WIDGET CONFIGURATION")
            logger.info("=" * 100)
            logger.info(f"📥 Received config_data keys: {list(config_data.keys())}")
            
            # Check if display_chatbot is being changed
            old_config = await self.get_widget_config()
            old_display_chatbot = old_config.get("display_chatbot", True)
            new_display_chatbot = config_data.get("display_chatbot", True)
            
            # Extract suggested messages if present
            suggested_messages = config_data.pop('suggested_messages', None)
            logger.info(f"📋 Extracted suggested_messages from config_data: {suggested_messages} (type: {type(suggested_messages).__name__})")
            
            if suggested_messages is not None:
                logger.info(f"📋 Suggested messages found:")
                for i, msg in enumerate(suggested_messages, 1):
                    logger.info(f"   [{i}] {msg}")

            # Update main widget configuration
            await self._widget_config_dao.update_widget_config(config_data)
            logger.info(f"✅ Main widget configuration updated")

            # Update suggested messages if provided
            if suggested_messages is not None:
                logger.info(f"💾 Updating {len(suggested_messages)} suggested messages in database...")
                await self._widget_config_dao.update_suggested_messages(suggested_messages)
                logger.info(f"✅ Suggested messages updated successfully")
            else:
                logger.info(f"⚠️ No suggested_messages key found in config_data - skipping update")
            
            logger.info("=" * 100)
            
            # Broadcast state change if display_chatbot changed
            if old_display_chatbot != new_display_chatbot:
                logger.info(f"Display chatbot changed from {old_display_chatbot} to {new_display_chatbot}")
                try:
                    from .widget_realtime_service import widget_realtime_service
                    await widget_realtime_service.broadcast_state_change("display_chatbot")
                except Exception as e:
                    logger.error(f"Error broadcasting state change: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error updating widget config: {e}")
            logger.info("=" * 100)
            raise
    

    async def update_widget_image(self, image_type: str, image_data: bytes, filename: str) -> Tuple[str, str]:
        """
        Update widget image by uploading to Railway storage and updating database with URL.
        
        Args:
            image_type: Type of image ('profile', 'chatIcon', 'headerIcon')
            image_data: Raw image data bytes
            filename: Original filename
            
        Returns:
            Tuple of (storage_url, storage_filename)
        """
        try:
            result = await self._widget_config_dao.update_widget_image(image_type, image_data, filename)
            logger.info(f"✅ Widget image '{image_type}' updated successfully")
            return result
        except Exception as e:
            logger.error(f"Error updating widget image: {e}")
            raise

    async def update_widget_config_with_images(self, config_data: Dict[str, Any], profile_file=None, chat_icon_file=None):
        """
        Update widget configuration with optional image uploads in a single transaction.
        
        Args:
            config_data: Widget configuration data
            profile_file: Optional profile image file (UploadFile)
            chat_icon_file: Optional chat icon image file (UploadFile)
            
        Returns:
            None (raises exception on error)
        """
        try:
            # Handle image uploads if present and update config with URLs
            if profile_file and profile_file.filename:
                image_data = await profile_file.read()
                image_url, image_filename = await self.update_widget_image('profile', image_data, profile_file.filename)
                config_data['profile_picture_url'] = image_url
                config_data['profile_picture_filename'] = image_filename
                logger.info(f"✅ Profile image uploaded and URL updated: {profile_file.filename}")
            
            if chat_icon_file and chat_icon_file.filename:
                image_data = await chat_icon_file.read()
                image_url, image_filename = await self.update_widget_image('chatIcon', image_data, chat_icon_file.filename)
                config_data['chat_icon_url'] = image_url
                config_data['chat_icon_filename'] = image_filename
                logger.info(f"✅ Chat icon image uploaded and URL updated: {chat_icon_file.filename}")
            
            # Update widget configuration with image URLs
            await self.update_widget_config(config_data)
                
        except Exception as e:
            logger.error(f"Error in update_widget_config_with_images: {e}")
            raise

    async def generate_embed_script(self, embed_type: str = "bubble", widget_url: str = "https://your-widget-url.com", fallback_config: Dict[str, Any] = None):
        """
        Generate widget embed script based on latest widget configuration
        
        Args:
            embed_type: Type of embed ("bubble" or "iframe")
            widget_url: Base URL for the widget
            fallback_config: Optional fallback config values
            
        Returns:
            Dictionary containing script, embed type, and config info
        """
        try:
            # Get the latest widget configuration from database
            config = await self.get_widget_config()
            
            # Use actual config values or fallback to provided config
            theme = config.get("theme", fallback_config.get("theme", "light") if fallback_config else "light")
            primary_color = config.get("primary_color", fallback_config.get("primaryColor", "#3b82f6") if fallback_config else "#3b82f6")
            position = config.get("align_bubble", fallback_config.get("position", fallback_config.get("alignBubble", "right"))) if fallback_config else config.get("align_bubble", "right")
            chat_bubble_color = config.get("chat_bubble_color", fallback_config.get("chatBubbleColor", "#000000")) if fallback_config else config.get("chat_bubble_color", "#000000")
            display_chatbot = config.get("display_chatbot", fallback_config.get("displayChatbot", True)) if fallback_config else config.get("display_chatbot", True)
            
            # Convert position format for CSS
            position_css = "bottom-right" if position == "right" else "bottom-left"

            if embed_type == "iframe":
                script = f'''<!-- Knowledgebot Widget - Iframe Embed -->
<iframe
    src="{widget_url}"
    style="position: fixed; {position_css.replace('-', ': 20px; ')}; width: 400px; height: 600px; border: none; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999;"
    title="Chat Widget"
></iframe>'''
            else:
                # Bubble embed (default) - use actual config values
                script = f'''<!-- Knowledgebot Widget - Bubble Embed -->
<script>
(function() {{
    var w = window;
    var d = document;
    var s = d.createElement('script');
    s.src = '{widget_url}/widget.js';
    s.async = true;
    s.onload = function() {{
        w.KnowledgeBot.init({{
            theme: '{theme}',
            primaryColor: '{primary_color}',
            position: '{position_css}',
            chatBubbleColor: '{chat_bubble_color}',
            displayChatbot: {str(display_chatbot).lower()},
            profilePictureUrl: '{config.get("profile_picture_url", "")}',
            chatIconUrl: '{config.get("chat_icon_url", "")}',
            displayName: '{config.get("display_name", "AI Assistant")}',
            initialMessage: '{config.get("initial_message", "Hello! How can I help you?")}'
        }});
    }};
    d.head.appendChild(s);
}})();
</script>'''

            return {
                "success": True,
                "script": script,
                "embedType": embed_type,
                "config": {
                    "theme": theme,
                    "primaryColor": primary_color,
                    "position": position_css,
                    "chatBubbleColor": chat_bubble_color,
                    "displayChatbot": display_chatbot
                }
            }
        except Exception as e:
            logger.error(f"Error generating embed script: {e}")
            raise
