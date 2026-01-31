"""
Consolidated Configuration Router
All configuration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends
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
from ..service.token_usage_service import TokenUsageService
from ..schemas.models import (
    ChatbotConfigRequest, 
    AdminManagementRequest,
    PersonaRequest,
    NotificationRequest,
    FeedbackRequest,
    WidgetConfigRequest
)

# Version: 2.2 - Enhanced debugging with version check
# This version includes detailed logging for get_user_profile debugging
logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/version")
async def get_version():
    """Simple version check endpoint"""
    return {
        "service": "configuration",
        "version": "2.2",
        "status": "enhanced_debugging_deployed",
        "timestamp": "2026-01-31T13:28:00Z"
    }

@router.get("/test")
async def test_endpoint():
    """Simple test endpoint without authentication"""
    logger.info("🔍 TEST ENDPOINT CALLED - SERVICE IS WORKING!")
    return {
        "message": "Configuration service is working!",
        "version": "2.2",
        "timestamp": "2026-01-31T13:35:00Z"
    }

# Simple function to get current user from request state or headers (set by API Gateway middleware)
async def get_current_user(request: Request):
    """Get current user from request state or headers (set by API Gateway middleware)"""
    logger.info("🔍 get_current_user called")
    logger.info(f"🔍 Request headers: {dict(request.headers)}")
    
    # First try request.state (direct API Gateway access)
    if hasattr(request.state, 'user'):
        logger.info(f"🔍 Found user in request.state: {request.state.user}")
        return request.state.user
    
    # Then try headers (proxied from API Gateway)
    user_uid = request.headers.get('X-User-UID')
    user_email = request.headers.get('X-User-Email')
    user_name = request.headers.get('X-User-Name')
    
    logger.info(f"🔍 Headers - UID: {user_uid}, Email: {user_email}, Name: {user_name}")
    
    if user_email:
        user_data = {
            "uid": user_uid,
            "email": user_email,
            "name": user_name or user_email,
            "picture": None  # Not forwarded in headers
        }
        logger.info(f"🔍 Returning user from headers: {user_data}")
        return user_data
    
    # This should not happen if API Gateway is properly configured
    logger.error("🔍 No user found in request.state or headers!")
    logger.error(f"🔍 Available headers: {list(request.headers.keys())}")
    raise HTTPException(status_code=401, detail="User not found in request state or headers")

# Initialize services
config_service = ConfigurationService()
personas_service = PersonasService()
auth_service = AuthService()
chat_log_service = ChatLogService()
notifications_service = NotificationsService(notifications_dao=None)
performance_service = PerformanceService()
feedback_service = FeedbackService()
token_usage_service = TokenUsageService()

# =================================
# DEBUG ENDPOINTS
# =================================

@router.get("/debug/test")
async def debug_test():
    """Test endpoint to verify logging is working"""
    logger.info("🔍 Debug test endpoint called - logging is working!")
    return {
        "success": True,
        "message": "Debug test successful",
        "timestamp": "2026-01-31T14:40:00Z"
    }

# =================================
# CHATBOT CONFIGURATION ENDPOINTS
# =================================

@router.get("/chatbot")
async def get_chatbot_config(cache: bool = True):
    """Get complete chatbot configuration with caching support"""
    try:
        logger.info(f"🔍 GET /chatbot called with cache={cache}")
        config = await config_service.get_chatbot_config()
        logger.info(f"✅ Chatbot config retrieved successfully (cache={cache})")
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"Error getting chatbot config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chatbot")
async def save_chatbot_config(config: ChatbotConfigRequest, request: Request):
    """Save chatbot configuration"""
    try:
        logger.info(f"🔍 POST /chatbot received: {config}")
        logger.info(f"🔍 Request headers: {dict(request.headers)}")
        
        await config_service.save_chatbot_config(config.dict())
        
        logger.info("✅ Chatbot config saved successfully")
        return {"success": True, "message": "Chatbot configuration saved successfully"}
    except Exception as e:
        logger.error(f"❌ Error saving chatbot config: {e}")
        logger.error(f"❌ Error type: {type(e)}")
        logger.error(f"❌ Error details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving chatbot config: {str(e)}")

# =================================
# WIDGET CONFIGURATION ENDPOINTS
# =================================

@router.get("/widget")
async def get_widget_config():
    """Get widget configuration"""
    try:
        config = await config_service.get_widget_config()
        
        # If no config exists, return default configuration
        if not config:
            config = {
                "display_name": "GLOBISTAAN",
                "initial_message": "Hi! What can I help you with?",
                "auto_show_duration": 4,
                "keep_showing_suggested": True,
                "theme": "light",
                "primary_color": "#3b82f6",
                "use_primary_for_header": False,
                "chat_bubble_color": "#f3f4f6",
                "align_bubble": "left",
                "display_chatbot": True,
                "profile_picture_url": "",
                "chat_icon_url": "",
                "profile_picture_filename": "",
                "chat_icon_filename": "",
                "profile_zoom": 1,
                "chat_icon_zoom": 1,
                "profile_position": {"x": 0, "y": 0},
                "chat_icon_position": {"x": 0, "y": 0},
                "suggested_messages": []
            }
            logger.info("🔧 Returning default widget configuration (no data in database)")
        
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"Error getting widget config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/widget")
async def update_widget_config(config: WidgetConfigRequest, request: Request):
    """Update widget configuration"""
    try:
        await config_service.update_widget_config(config.dict())
        return {"success": True, "message": "Widget configuration updated successfully"}
    except Exception as e:
        logger.error(f"Error updating widget config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERSONAS ENDPOINTS
# =================================

@router.get("/personas")
async def get_personas():
    """Get all available personas"""
    try:
        personas = await personas_service.get_all_personas()
        return {"success": True, "data": personas}
    except Exception as e:
        logger.error(f"Error getting personas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/personas/{persona_name}/activate")
async def activate_persona(persona_name: str, request: Request):
    """Activate a specific persona"""
    try:
        result = await personas_service.activate_persona(persona_name, "admin@example.com")
        return {"success": True, "message": f"Persona {persona_name} activated successfully"}
    except Exception as e:
        logger.error(f"Error activating persona: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/personas")
async def create_persona(persona: PersonaRequest, request: Request):
    """Create a new persona"""
    try:
        result = await personas_service.create_persona(persona.dict(), "admin@example.com")
        return {"success": True, "message": "Persona created successfully"}
    except Exception as e:
        logger.error(f"Error creating persona: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ADMIN MANAGEMENT ENDPOINTS
# =================================

@router.get("/admins")
async def get_admin_users():
    """Get all admin users"""
    try:
        admins = await auth_service.get_admin_users()
        return {"success": True, "data": admins}
    except Exception as e:
        logger.error(f"Error getting admin users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admins")
async def add_admin_user(request_data: AdminManagementRequest, request: Request):
    """Add a new admin user"""
    try:
        result = await auth_service.add_admin(request_data.email, "admin@example.com")
        return {"success": True, "message": "Admin user added successfully"}
    except Exception as e:
        logger.error(f"Error adding admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admins/{email}")
async def remove_admin_user(email: str, request: Request):
    """Remove an admin user"""
    try:
        result = await auth_service.remove_admin(email, "admin@example.com")
        return {"success": True, "message": "Admin user removed successfully"}
    except Exception as e:
        logger.error(f"Error removing admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        result = await auth_service.add_human_agent(request_data.email, "admin@example.com")
        return {"success": True, "message": "Human agent added successfully"}
    except Exception as e:
        logger.error(f"Error adding human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/human-agents/{email}")
async def remove_human_agent(email: str, request: Request):
    """Remove a human agent"""
    try:
        result = await auth_service.remove_human_agent(email, "admin@example.com")
        return {"success": True, "message": "Human agent removed successfully"}
    except Exception as e:
        logger.error(f"Error removing human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# CHAT LOG ENDPOINTS
# =================================

@router.get("/chat-logs")
async def get_chat_logs():
    """Get all chat logs"""
    try:
        logs = await chat_log_service.get_all_chat_logs()
        return {"success": True, "data": logs}
    except Exception as e:
        logger.error(f"Error getting chat logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat-logs/{session_id}")
async def delete_chat_log(session_id: str, request: Request):
    """Delete a chat log"""
    try:
        result = await chat_log_service.delete_chat_log(session_id, "admin@example.com")
        return {"success": True, "message": "Chat log deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting chat log: {e}")
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
        result = await notifications_service.update_settings(settings.dict(), "admin@example.com")
        return {"success": True, "message": "Notification settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating notification settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications/send")
async def send_notification(notification: Dict[str, Any], request: Request):
    """Send a notification"""
    try:
        result = await notifications_service.send_notification(notification, "admin@example.com")
        return {"success": True, "message": "Notification sent successfully"}
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ADMIN ENDPOINTS
# =================================

@router.get("/admin/agents/online")
async def get_online_agents():
    """Get online agents"""
    try:
        # For now, return empty list - this should be implemented with proper agent tracking
        return {"success": True, "agents": []}
    except Exception as e:
        logger.error(f"Error getting online agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/chat-sessions")
async def get_admin_chat_sessions(role: str = "admin", status: str = "active", page: int = 1, limit: int = 50):
    """Get chat sessions for admin"""
    try:
        # For now, return empty result - this should be implemented with proper session tracking
        return {"success": True, "sessions": [], "total_count": 0, "page": page}
    except Exception as e:
        logger.error(f"Error getting admin chat sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/unique-id")
async def generate_unique_id():
    """Generate unique user ID"""
    try:
        import uuid
        unique_id = str(uuid.uuid4())
        return {"success": True, "unique_id": unique_id}
    except Exception as e:
        logger.error(f"Error generating unique ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERFORMANCE ENDPOINTS
# =================================

@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get performance metrics"""
    try:
        metrics = await performance_service.get_performance_metrics()
        return {"success": True, "data": metrics}
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/token-usage/detailed")
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None):
    """Get detailed token usage"""
    try:
        usage = await token_usage_service.get_detailed_token_usage(limit, provider, api_call_type)
        return {"success": True, "data": usage}
    except Exception as e:
        logger.error(f"Error getting detailed token usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# FEEDBACK ENDPOINTS
# =================================

@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest, request: Request):
    """Submit feedback"""
    try:
        result = await feedback_service.submit_feedback(feedback.dict(), "admin@example.com")
        return {"success": True, "message": "Feedback submitted successfully"}
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/feedback")
async def get_feedback():
    """Get all feedback"""
    try:
        feedback_list = await feedback_service.get_all_feedback()
        return {"success": True, "data": feedback_list}
    except Exception as e:
        logger.error(f"Error getting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# USER ENDPOINTS
# =================================

@router.get("/users/profile")
async def get_user_profile(user: dict = Depends(get_current_user)):
    """Get user profile information"""
    logger.info("🔍 GET /users/profile called")
    logger.info(f"🔍 User data: {user}")
    
    try:
        # Get user's actual role from database
        user_email = user.get("email")
        logger.info(f"🔍 Getting role for user email: {user_email}")
        
        if not user_email:
            logger.error(f"🔍 No user email found in user data: {user}")
            raise HTTPException(status_code=400, detail="User email not found")
        
        logger.info("🔍 About to call auth_service.get_user_role")
        role_result = await auth_service.get_user_role(user_email)
        logger.info(f"🔍 Role result: {role_result}")
        logger.info(f"🔍 Role result type: {type(role_result)}")
        
        # Check if role_result is serializable
        import json
        try:
            json.dumps(role_result)
            logger.info("✅ Role result is JSON serializable")
        except Exception as e:
            logger.error(f"❌ Role result is NOT JSON serializable: {e}")
            logger.error(f"❌ Role result details: {dir(role_result)}")
        
        user_roles = role_result.get("roles", ["user"])
        logger.info(f"🔍 User roles: {user_roles}")
        
        # Determine primary role (admin > human_agent > user)
        primary_role = "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        logger.info(f"🔍 Primary role: {primary_role}")
        
        # Return authenticated user profile with actual role
        profile = {
            "email": user.get("email"),
            "uid": user.get("uid"),
            "name": user.get("name", user.get("email")),
            "picture": user.get("picture"),
            "role": primary_role,
            "roles": user_roles,  # Include all roles for frontend
            "preferences": {
                "theme": "light",
                "notifications": True
            }
        }
        logger.info("🔍 User profile created successfully")
        
        # Check if profile is serializable
        try:
            json.dumps(profile)
            logger.info("✅ Profile is JSON serializable")
        except Exception as e:
            logger.error(f"❌ Profile is NOT JSON serializable: {e}")
        
        return {"success": True, "data": profile}
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"❌ Error getting user profile: {e}")
        logger.error(f"❌ Error type: {type(e)}")
        logger.error(f"❌ Error details: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/profile")
async def update_user_profile(profile_data: Dict[str, Any], user: dict = Depends(get_current_user)):
    """Update user profile information"""
    try:
        # Mock update - in real implementation, this would update user in database
        return {"success": True, "message": "Profile updated successfully"}
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users")
async def get_all_users(user: dict = Depends(get_current_user)):
    """Get all users (admin only)"""
    try:
        # Check if current user is admin using database
        current_user_email = user.get("email")
        current_user_role = await auth_service.get_user_role(current_user_email)
        
        if "admin" not in current_user_role.get("roles", []):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Get all admins and human agents from database
        admins = await auth_service.get_admins()
        human_agents = await auth_service.get_human_agents()
        
        # Combine and format users
        users = []
        
        # Add admins
        for admin in admins:
            users.append({
                "email": admin.get("email"),
                "role": "admin",
                "status": "active",
                "added_at": admin.get("created_at")
            })
        
        # Add human agents
        for agent in human_agents:
            users.append({
                "email": agent.get("email"),
                "role": "human_agent",
                "status": "active",
                "added_at": agent.get("created_at")
            })
        
        return {"success": True, "data": users}
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "service": "configuration",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "config_service": "healthy",
                "personas_service": "healthy",
                "auth_service": "healthy",
                "chat_log_service": "healthy",
                "notifications_service": "healthy",
                "performance_service": "healthy",
                "feedback_service": "healthy",
                "token_usage_service": "healthy"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
