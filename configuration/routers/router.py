"""
Consolidated Configuration Router
All configuration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging
import json

from ..service.configuration_service import ConfigurationService
from ..service.personas_service import PersonasService
from ..service.auth_service import AuthService
from ..service.chat_log_service import ChatLogService
from ..service.notifications_service import NotificationsService
from ..service.performance_service import PerformanceService
from ..service.feedback_service import FeedbackService
from ..service.widget_service import WidgetService
from ..service.token_usage_service import TokenUsageService
from ..core.auth_middleware import get_current_user
from ..schemas.models import (
    ChatbotConfigRequest, 
    AdminManagementRequest,
    PersonaRequest,
    NotificationRequest,
    FeedbackRequest,
    WidgetConfigRequest
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
config_service = ConfigurationService()
personas_service = PersonasService()
auth_service = AuthService()
chat_log_service = ChatLogService()
notifications_service = NotificationsService(notifications_dao=None)
performance_service = PerformanceService()
feedback_service = FeedbackService()
widget_service = WidgetService()
token_usage_service = TokenUsageService()

# =================================
# CHATBOT CONFIGURATION ENDPOINTS
# =================================

@router.get("/configuration/chatbot")
async def get_chatbot_config():
    """Get complete chatbot configuration"""
    try:
        config = await config_service.get_chatbot_config()
        return config
    except Exception as e:
        logger.error(f"Error getting chatbot configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/configuration/chatbot")
async def save_chatbot_config(config: ChatbotConfigRequest, request: Request):
    """Save chatbot configuration"""
    try:
        # Get current user for audit
        current_user = await get_current_user(request)
        
        result = await config_service.save_chatbot_config(config, current_user)
        return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving chatbot configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/configuration/metadata")
async def get_configuration_metadata():
    """Get configuration metadata"""
    try:
        metadata = await config_service.get_metadata()
        return {"success": True, "data": metadata}
    except Exception as e:
        logger.error(f"Error getting configuration metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERSONAS ENDPOINTS
# =================================

@router.get("/personas")
async def get_personas():
    """Get all personas with current active persona"""
    try:
        personas = await personas_service.get_personas()
        return personas
    except Exception as e:
        logger.error(f"Error getting personas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/personas/{persona_name}/activate")
async def activate_persona(persona_name: str, request: Request):
    """Activate a specific persona"""
    try:
        current_user = await get_current_user(request)
        result = await personas_service.activate_persona(persona_name, current_user.get('email'))
        return {"success": True, "message": f"Persona {persona_name} activated successfully"}
    except Exception as e:
        logger.error(f"Error activating persona {persona_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/personas")
async def create_persona(persona: PersonaRequest, request: Request):
    """Create a new persona"""
    try:
        current_user = await get_current_user(request)
        result = await personas_service.create_persona(persona.dict(), current_user.get('email'))
        return {"success": True, "message": "Persona created successfully"}
    except Exception as e:
        logger.error(f"Error creating persona: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ADMIN MANAGEMENT ENDPOINTS
# =================================

@router.get("/admin/users")
async def get_admin_users():
    """Get all admin users"""
    try:
        users = await auth_service.get_admins()
        return {"success": True, "data": users}
    except Exception as e:
        logger.error(f"Error getting admin users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/users")
async def add_admin_user(request_data: AdminManagementRequest, request: Request):
    """Add a new admin user"""
    try:
        current_user = await get_current_user(request)
        result = await auth_service.add_admin(request_data.email, current_user.get('email'))
        return {"success": True, "message": "Admin user added successfully"}
    except Exception as e:
        logger.error(f"Error adding admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admin/users/{email}")
async def remove_admin_user(email: str, request: Request):
    """Remove an admin user"""
    try:
        current_user = await get_current_user(request)
        result = await auth_service.remove_admin(email, current_user.get('email'))
        return {"success": True, "message": "Admin user removed successfully"}
    except Exception as e:
        logger.error(f"Error removing admin user {email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HUMAN AGENTS ENDPOINTS
# =================================

@router.get("/human-agents")
async def get_human_agents():
    """Get all human agents"""
    try:
        agents = await auth_service.get_human_agents()
        return {"success": True, "data": agents}
    except Exception as e:
        logger.error(f"Error getting human agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/human-agents")
async def add_human_agent(request_data: AdminManagementRequest, request: Request):
    """Add a new human agent"""
    try:
        current_user = await get_current_user(request)
        result = await auth_service.add_human_agent(request_data.email, current_user.get('email'))
        return {"success": True, "message": "Human agent added successfully"}
    except Exception as e:
        logger.error(f"Error adding human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/human-agents/{email}")
async def remove_human_agent(email: str, request: Request):
    """Remove a human agent"""
    try:
        current_user = await get_current_user(request)
        result = await auth_service.remove_human_agent(email, current_user.get('email'))
        return {"success": True, "message": "Human agent removed successfully"}
    except Exception as e:
        logger.error(f"Error removing human agent {email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# CHAT LOG ENDPOINTS
# =================================

@router.get("/chat-logs")
async def get_chat_logs(limit: int = 50, offset: int = 0):
    """Get chat logs with pagination"""
    try:
        logs = await chat_log_service.get_chat_logs(limit, offset)
        return {"success": True, "data": logs}
    except Exception as e:
        logger.error(f"Error getting chat logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat-logs/search")
async def search_chat_logs(query: str, limit: int = 50):
    """Search chat logs"""
    try:
        logs = await chat_log_service.search_chat_logs(query, limit)
        return {"success": True, "data": logs}
    except Exception as e:
        logger.error(f"Error searching chat logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat-logs/{session_id}")
async def delete_chat_log(session_id: str, request: Request):
    """Delete a chat log"""
    try:
        current_user = await get_current_user(request)
        result = await chat_log_service.delete_chat_log(session_id, current_user.get('email'))
        return {"success": True, "message": "Chat log deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting chat log {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# NOTIFICATIONS ENDPOINTS
# =================================

@router.get("/notifications/settings")
async def get_notification_settings():
    """Get notification settings"""
    try:
        settings = await notifications_service.get_settings()
        return {"success": True, "data": settings}
    except Exception as e:
        logger.error(f"Error getting notification settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications/settings")
async def update_notification_settings(settings: NotificationRequest, request: Request):
    """Update notification settings"""
    try:
        current_user = await get_current_user(request)
        result = await notifications_service.update_settings(settings.dict(), current_user.get("email"))
        return {"success": True, "message": "Notification settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating notification settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications/send")
async def send_notification(notification: Dict[str, Any], request: Request):
    """Send a notification"""
    try:
        current_user = await get_current_user(request)
        result = await notification_service.send_notification(notification, current_user.get("email"))
        return {"success": True, "message": "Notification sent successfully"}
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERFORMANCE ENDPOINTS
# =================================

@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get performance metrics"""
    try:
        metrics = await performance_service.get_metrics()
        return {"success": True, "data": metrics}
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/performance/health")
async def get_health_status():
    """Get system health status"""
    try:
        health = await performance_service.get_health_status()
        return {"success": True, "data": health}
    except Exception as e:
        logger.error(f"Error getting health status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# FEEDBACK ENDPOINTS
# =================================

@router.get("/feedback")
async def get_feedback(limit: int = 50, offset: int = 0):
    """Get feedback with pagination"""
    try:
        feedback = await feedback_service.get_feedback(limit, offset)
        return {"success": True, "data": feedback}
    except Exception as e:
        logger.error(f"Error getting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest, request: Request):
    """Submit feedback"""
    try:
        current_user = await get_current_user(request)
        result = await feedback_service.submit_feedback(feedback.dict(), current_user.get('email'))
        return {"success": True, "message": "Feedback submitted successfully"}
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# USER MANAGEMENT ENDPOINTS
# =================================

@router.get("/users")
async def get_users(limit: int = 50, offset: int = 0):
    """Get users with pagination"""
    try:
        users = await user_service.get_users(limit, offset)
        return {"success": True, "data": users}
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}")
async def get_user(user_id: str):
    """Get user by ID"""
    try:
        user = await user_service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "data": user}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
async def update_user(user_id: str, user_data: Dict[str, Any], request: Request):
    """Update user"""
    try:
        current_user = await get_current_user(request)
        result = await user_service.update_user(user_id, user_data, current_user.get('email'))
        return {"success": True, "message": "User updated successfully"}
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# WIDGET CONFIGURATION ENDPOINTS
# =================================

@router.get("/widget/config")
async def get_widget_config():
    """Get widget configuration"""
    try:
        config = await widget_service.get_widget_config()
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"Error getting widget config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/widget/config")
async def save_widget_config(config: WidgetConfigRequest, request: Request):
    """Save widget configuration"""
    try:
        current_user = await get_current_user(request)
        result = await widget_service.save_widget_config(config.dict(), current_user.get('email'))
        return {"success": True, "message": "Widget configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving widget config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# TOKEN USAGE ENDPOINTS
# =================================

@router.get("/token-usage/summary")
async def get_token_usage_summary():
    """Get token usage summary"""
    try:
        summary = await token_usage_service.get_summary()
        return {"success": True, "data": summary}
    except Exception as e:
        logger.error(f"Error getting token usage summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/token-usage/detailed")
async def get_detailed_token_usage(limit: int = 50, provider: Optional[str] = None):
    """Get detailed token usage"""
    try:
        usage = await token_usage_service.get_detailed_usage(limit, provider)
        return {"success": True, "data": usage}
    except Exception as e:
        logger.error(f"Error getting detailed token usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/token-usage/export")
async def export_token_usage(format: str = "csv"):
    """Export token usage data"""
    try:
        data = await token_usage_service.export_usage(format)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Error exporting token usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ADMIN CHAT SESSIONS ENDPOINTS
# =================================

@router.post("/admin/chat-sessions/{session_id}/request-agent")
async def request_human_agent(session_id: str):
    """Request a human agent for a chat session."""
    try:
        logger.info(f"Requesting human agent for session {session_id}")
        result = await config_service.request_human_agent(session_id)
        return result
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")

# =================================
# WIDGET CONFIGURATION ENDPOINTS
# =================================

@router.get("/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    try:
        # Service handles all data transformation
        data = await config_service.get_widget_config_with_transform()
        
        from fastapi.responses import JSONResponse
        response = JSONResponse(content=data)
        response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
        return response
    except Exception as e:
        logger.error(f"Error fetching widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching widget configuration: {str(e)}")

@router.post("/configuration/widget")
async def save_widget_config(config: Dict[str, Any], request: Request):
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
            value = config.get(field, None)
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
        if config.get("suggested_messages") is not None:
            await config_service.clear_suggested_messages()
            for i, message in enumerate(config["suggested_messages"]):
                if message and isinstance(message, str):
                    await config_service.add_suggested_message(message, i)
        
        if update_data:
            await config_service.update_widget_config(update_data)
        
        return {"success": True, "message": "Widget configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving widget configuration: {str(e)}")

@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...), type: str = Form(...)):
    """Upload image for widget configuration."""
    try:
        from fastapi import UploadFile, Form
        
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
        
        if type not in ["profile", "chatIcon", "headerIcon"]:
            raise HTTPException(status_code=400, detail="Invalid image type. Must be 'profile', 'chatIcon', or 'headerIcon'")
        
        # Read file content
        content = await file.read()
        
        # For now, just return success with a placeholder URL
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
        
        return {
            "success": True,
            "script": script,
            "config": config
        }
        
    except Exception as e:
        logger.error(f"Error generating widget script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating widget script: {str(e)}")

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "service": "configuration",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
