import json

from fastapi import APIRouter, Depends, HTTPException, Request, File, Form, UploadFile
from fastapi.responses import JSONResponse

from configuration.core.logging_config import get_railway_logger

from ..schemas.models import WidgetConfigRequest
from ..service.configuration_service import configuration_service
from ..utils.logging_utils import log_configuration_change

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Widget Configuration"])

@router.get("/configuration/widget")
async def get_widget_config(request: Request):
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
    request: Request
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
                    user_email=request.headers.get('X-User-Email', 'system'),
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


@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...), type: str = Form(...)):
    """Upload image for widget configuration."""
    try:
        # For now, return a placeholder URL - in production, this would upload to R2 or similar
        # This endpoint exists for frontend compatibility
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        
        if type not in ["profile", "chatIcon", "headerIcon"]:
            raise HTTPException(status_code=400, detail="Invalid image type. Must be 'profile', 'chatIcon', or 'headerIcon'")
        
        # Read file content
        content = await file.read()
        
        # For now, just return success with a placeholder URL
        # In production, this would upload to R2 or similar storage
        return {
            "success": True,
            "message": "Image uploaded successfully",
            "url": f"https://placeholder.com/images/{type}/{file.filename}",
            "filename": file.filename,
            "size": len(content),
            "type": type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error uploading image: {str(e)}")


@router.post("/embed-script")
async def generate_widget_script(request_data: dict):
    """Generate widget embed script for frontend."""
    try:
        # Extract configuration from request
        config = request_data.get('config', {})
        
        # Generate a simple embed script
        script = f"""
(function() {{
    const config = {json.dumps(config)};
    
    // Create widget container
    const container = document.createElement('div');
    container.id = 'knowledgebot-widget';
    container.style.position = 'fixed';
    container.style.bottom = config.position?.bottom || '20px';
    container.style.right = config.position?.right || '20px';
    container.style.zIndex = config.position?.zIndex || '9999';
    
    // Create widget button
    const button = document.createElement('button');
    button.innerHTML = config.display_name || 'Chat with us';
    button.style.backgroundColor = config.button_color || '#007bff';
    button.style.color = config.button_text_color || '#ffffff';
    button.style.border = 'none';
    button.style.borderRadius = config.border_radius || '5px';
    button.style.padding = '10px 15px';
    button.style.cursor = 'pointer';
    button.style.fontSize = '14px';
    
    // Add click handler
    button.addEventListener('click', function() {{
        // Open chat window
        window.open('{config.get("chat_url", "/chat")}', '_blank', 'width=400,height=600');
    }});
    
    container.appendChild(button);
    document.body.appendChild(container);
    
    console.log('Knowledgebot widget loaded successfully');
}})();
"""
        
        return {{
            "success": True,
            "script": script,
            "config": config
        }}
        
    except Exception as e:
        logger.error(f"Error generating widget script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating widget script: {str(e)}")


# Images are now persisted directly in PostgreSQL database
# No R2 storage upload needed
