import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from configuration.core.logging_config import get_railway_logger

from ..schemas.models import WidgetConfigRequest
from ..service.configuration_service import configuration_service
from ..utils.logging_utils import log_configuration_change

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Widget Configuration"])

@router.get("/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    try:
        # Service handles all data transformation
        data = await configuration_service.get_widget_config_with_transform()
        
        response = JSONResponse(content=data)
        response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
        return response
    except Exception as e:
        logger.error(f"Error fetching widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching widget configuration: {str(e)}")

@router.post("/configuration/widget")
async def save_widget_config(
    config: WidgetConfigRequest,
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Save widget configuration"""
    try:
        # Build update map
        update_data = {}
        fields_map = {
            "display_name": "display_name",
            "initial_message": "initial_message",
            "auto_show_duration": "auto_show_duration",
            "keep_showing_suggested": "keep_showing_suggested",
            "theme": "theme",
            "primary_color": "primary_color",
            "use_primary_for_header": "use_primary_for_header",
            "chat_bubble_color": "chat_bubble_color",
            "align_bubble": "align_bubble",
            "display_chatbot": "display_chatbot",
            "profile_picture_url": "profile_picture_url",
            "chat_icon_url": "chat_icon_url",
            "profile_zoom": "profile_zoom",
            "chat_icon_zoom": "chat_icon_zoom",
            "profile_position": "profile_position",
            "chat_icon_position": "chat_icon_position",
            "profile_picture_filename": "profile_picture_filename",
            "chat_icon_filename": "chat_icon_filename"
        }

        for field, db_field in fields_map.items():
            value = getattr(config, field, None)
            if value is not None:
                if field in ['profile_position', 'chat_icon_position']:
                    if hasattr(value, 'dict'):
                        value = json.dumps(value.dict())
                    elif isinstance(value, dict):
                        value = json.dumps(value)
                    else:
                        value = json.dumps({"x": 0, "y": 0})
                update_data[db_field] = value

        # Handle suggested_messages
        if config.suggested_messages is not None:
            await configuration_service.clear_suggested_messages()
            for i, message in enumerate(config.suggested_messages):
                if message and isinstance(message, str):
                    await configuration_service.add_suggested_message(message, i)

        if update_data:
            await configuration_service.update_widget_config(update_data)

            # Log the configuration change (non-blocking)
            try:
                await log_configuration_change(
                    user_email=current_user.get('email'),
                    action='widget_config_update',
                    details=config.dict(exclude_unset=True),
                    ip_address=request.client.host if request else None
                )
            except Exception as e:
                logger.warning(f"Failed to log widget configuration change: {e}")
                # Don't fail the configuration save if logging fails

            return {"success": True, "message": "Widget configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving widget configuration: {str(e)}")

# Images are now persisted directly in PostgreSQL database
# No R2 storage upload needed
