import json
import os
import tempfile
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
import asyncpg
from typing import Optional

from services.configuration_service.core.database import get_db_connection
from services.configuration_service.schemas.models import WidgetConfigRequest
from services.configuration_service.utils.logging_utils import log_configuration_change
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Widget Configuration"])

@router.get("/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    try:
        async with get_db_connection() as conn:
            from services.configuration_service.dao.widget_dao import WidgetDAO
            dao = WidgetDAO(conn)

            # Get main widget configuration
            row = await dao.get_widget_config()

            # Get suggested messages
            suggested_messages = await dao.get_suggested_messages()

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
        async with get_db_connection() as conn:
            from services.configuration_service.dao.widget_dao import WidgetDAO
            dao = WidgetDAO(conn)

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
                await dao.clear_suggested_messages()
                for i, message in enumerate(config.suggested_messages):
                    if message and isinstance(message, str):
                        await dao.add_suggested_message(message, i)

            if update_data:
                existing_id = await dao.get_existing_id()
                if existing_id:
                    await dao.update_widget_config(existing_id, update_data)
                else:
                    await dao.insert_widget_config(update_data)

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

@router.post("/widget/upload-image")
async def upload_widget_image(
    file: UploadFile = File(...),
    type: str = Form(...),  # 'profile', 'chatIcon', or 'headerIcon'
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Upload widget related images (profile, chat icon, header icon) to R2 storage."""
    
    # Access r2_storage from app state
    r2_storage = getattr(request.app.state, 'r2_storage', None)
    
    if not r2_storage:
        # Fallback if global variable is used (for backward compatibility during migration)
        # But we aim to use app.state
        raise HTTPException(status_code=503, detail="R2 storage not configured")

    if type not in ['profile', 'chatIcon', 'headerIcon']:
        raise HTTPException(status_code=400, detail="Invalid image type. Must be 'profile', 'chatIcon', or 'headerIcon'")

    # Validate file type
    allowed_content_types = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, WEBP, and GIF are allowed.")

    # Validate file size (max 2MB)
    MAX_SIZE = 2 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 2MB.")
    
    # Reset file cursor for further reading if needed (not needed for small files read into memory)
    
    try:
        # Create a temp file to upload
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename or "")[1]) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Upload to R2
            # prefix = f"widget/{type}" # Unused prefix?
            result = await r2_storage.upload_file(
                file_path=tmp_path,
                content_type=file.content_type,
                metadata={'original_filename': file.filename or "unknown", 'user': current_user.get('email', 'unknown')}
            )
            
            if not result or not result.get('url'):
                # Fallback path if public_url is not configured
                # In a real system, we'd provide a proxy URL through our API
                raise HTTPException(status_code=500, detail="Failed to generate public URL for uploaded file")

            logger.info(f"Successfully uploaded {type} image: {result['url']}")
            return {
                "url": result['url'],
                "filename": file.filename
            }
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to R2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")
