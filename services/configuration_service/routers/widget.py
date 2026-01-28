import json
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import JSONResponse
from typing import Optional

from ..core.database import get_db_connection
from ..schemas.models import WidgetConfigRequest
from ..utils.logging_utils import log_configuration_change
from ..servcie.configuration_service import configuration_service
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Widget Configuration"])

@router.get("/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    try:
        # Get main widget configuration
        row = await configuration_service.get_widget_config()

        # Get suggested messages
        suggested_messages = await configuration_service.get_suggested_messages()

        if not row:
            # Return default configuration
            data = {
                "display_name": "GLOBISTAAN",
                "initial_message": "Hi! What can I help you with?",
                "auto_show_duration": 4,
                "suggested_messages": [],
                "keep_showing_suggested": True,
                "theme": "light",
                "primary_color": "#3B81F6",
                "use_primary_for_header": True,
                "chat_bubble_color": "#3B81F6",
                "align_bubble": "right",
                "display_chatbot": True,
                "profile_picture_url": None,
                "chat_icon_url": None,
                "profile_zoom": 1.0,
                "chat_icon_zoom": 1.0,
                "profile_position": {"x": 0, "y": 0},
                "chat_icon_position": {"x": 0, "y": 0}
            }
            response = JSONResponse(content=data)
            response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
            return response

            # Build data object
            data = {
                "display_name": row["display_name"],
                "initial_message": row["initial_message"],
                "auto_show_duration": row["auto_show_duration"],
                "suggested_messages": suggested_messages,
                "keep_showing_suggested": row["keep_showing_suggested"],
                "theme": row["theme"],
                "primary_color": row["primary_color"],
                "use_primary_for_header": row["use_primary_for_header"],
                "chat_bubble_color": row["chat_bubble_color"],
                "align_bubble": row["align_bubble"],
                "display_chatbot": row["display_chatbot"] if row["display_chatbot"] is not None else True,
                "profile_picture_url": row["profile_picture_url"],
                "chat_icon_url": row["chat_icon_url"],
            }
            
            data["profile_zoom"] = float(row.get("profile_zoom", 1.0)) if row.get("profile_zoom") is not None else 1.0
            data["chat_icon_zoom"] = float(row.get("chat_icon_zoom", 1.0)) if row.get("chat_icon_zoom") is not None else 1.0
            data["profile_position"] = row.get("profile_position") if isinstance(row.get("profile_position"), dict) else {"x": 0, "y": 0}
            data["chat_icon_position"] = row.get("chat_icon_position") if isinstance(row.get("chat_icon_position"), dict) else {"x": 0, "y": 0}
            
            if "profile_picture_filename" in row:
                data["profile_picture_filename"] = row.get("profile_picture_filename")
            if "chat_icon_filename" in row:
                data["chat_icon_filename"] = row.get("chat_icon_filename")

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
            dao = await configuration_service._get_widget_dao()
            await dao.clear_suggested_messages()
            for i, message in enumerate(config.suggested_messages):
                if message and isinstance(message, str):
                    await dao.add_suggested_message(message, i)

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
