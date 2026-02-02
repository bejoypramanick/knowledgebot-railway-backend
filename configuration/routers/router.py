"""
Consolidated Configuration Router
All configuration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Dict, List, Any, Optional
import json

from configuration.core.otel_logger import get_otel_logger
from ..service.configuration_service import ConfigurationService
from ..service.auth_service import AuthService
from ..service.chat_log_service import ChatLogService
from ..service.notifications_service import NotificationsService
from ..service.performance_service import PerformanceService
from ..service.feedback_service import FeedbackService
from ..service.token_usage_service import TokenUsageService
from ..schemas.models import (
    ChatbotConfigRequest,
    AdminManagementRequest,
    NotificationRequest,
    FeedbackRequest,
    WidgetConfigRequest
)

# Version: 2.2 - Enhanced debugging with version check
# This version includes detailed logging for get_user_profile debugging
logger = get_otel_logger("configuration_router", "configuration")
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
auth_service = AuthService()
chat_log_service = ChatLogService()
notifications_service = NotificationsService(notifications_dao=None)
performance_service = PerformanceService()
feedback_service = FeedbackService()
token_usage_service = TokenUsageService()

# =================================
# CHATBOT CONFIGURATION ENDPOINTS
# =================================

@router.get("/chatAgentConfig")
async def get_chatbot_config(cache: bool = True):
    """Get complete chatbot configuration with caching support"""
    try:
        logger.info(f"🔍 GET /chatAgentConfig called with cache={cache}")
        config = await config_service.get_chatAgent_config()
        logger.info(f"✅ Chatbot config retrieved successfully (cache={cache})")
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"Error getting chatbot config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chatAgentConfig")
async def save_chatbot_config(config: ChatbotConfigRequest, request: Request):
    """Save chatbot configuration"""
    try:
        logger.info(f"🔍 POST /chatAgentConfig received: {config}")
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

@router.post("/widget/embed-script")
async def generate_widget_embed_script(request: Request):
    """Generate widget embed script based on configuration"""
    try:
        body = await request.json()
        embed_type = body.get("embedType", "bubble")
        theme = body.get("theme", "light")
        primary_color = body.get("primaryColor", "#3b82f6")
        position = body.get("position", "bottom-right")
        widget_url = body.get("widgetUrl", "https://your-widget-url.com")

        if embed_type == "iframe":
            script = f'''<!-- Knowledgebot Widget - Iframe Embed -->
<iframe
    src="{widget_url}"
    style="position: fixed; {position.replace('-', ': 20px; ')}; width: 400px; height: 600px; border: none; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999;"
    title="Chat Widget"
></iframe>'''
        else:
            # Bubble embed (default)
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
            position: '{position}'
        }});
    }};
    d.head.appendChild(s);
}})();
</script>'''

        return {
            "success": True,
            "script": script,
            "embedType": embed_type
        }
    except Exception as e:
        logger.error(f"Error generating embed script: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import UploadFile, File, Form
import base64
import os

@router.post("/widget/upload-image")
async def upload_widget_image(
    file: UploadFile = File(...),
    type: str = Form(...)  # profile, chatIcon, headerIcon
):
    """Upload an image for the widget (profile picture, chat icon, or header icon)"""
    try:
        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
            )

        # Validate image type parameter
        valid_types = ["profile", "chatIcon", "headerIcon"]
        if type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type. Allowed types: {', '.join(valid_types)}"
            )

        # Read file content
        content = await file.read()

        # Convert to base64 data URL for storage
        base64_content = base64.b64encode(content).decode('utf-8')
        data_url = f"data:{file.content_type};base64,{base64_content}"

        # Store in widget_configuration table via service
        await config_service.update_widget_image(type, data_url, file.filename)

        return {
            "success": True,
            "url": data_url,
            "filename": file.filename,
            "type": type,
            "message": f"Image uploaded successfully for {type}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading widget image: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERSONAS ENDPOINT
# =================================

@router.get("/personas")
async def get_personas():
    """Get all available personas with active status details"""
    try:
        config = await config_service.get_chatAgent_config()
        all_personas = config.get("available_personas", [])

        # Format personas with proper timestamps
        formatted_personas = []
        for p in all_personas:
            formatted_personas.append({
                "id": str(p.get("id", "")),
                "persona_name": p.get("persona_name", ""),
                "system_prompt": p.get("system_prompt", ""),
                "is_active": p.get("is_active", False),
                "created_at": p.get("created_at").isoformat() if hasattr(p.get("created_at"), "isoformat") else str(p.get("created_at", "")),
                "updated_at": p.get("updated_at").isoformat() if hasattr(p.get("updated_at"), "isoformat") else str(p.get("updated_at", ""))
            })

        # Filter active personas
        active_personas = [p for p in formatted_personas if p.get("is_active")]

        # Get current active persona (first active one)
        current_active = active_personas[0] if active_personas else None

        return {
            "success": True,
            "data": {
                "all_personas": formatted_personas,
                "active_personas": active_personas,
                "current_active_persona": current_active,
                "total_count": len(formatted_personas),
                "active_count": len(active_personas)
            }
        }
    except Exception as e:
        logger.error(f"Error getting personas: {e}")
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
        result = await auth_service.add_admin(request_data.email)
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

@router.get("/admin/human-agents")
async def get_human_agents_admin():
    """Get all human agents (admin alias endpoint)"""
    return await get_human_agents()

@router.post("/human-agents")
async def add_human_agent(request_data: AdminManagementRequest, request: Request):
    """Add a new human agent"""
    try:
        result = await auth_service.add_human_agent(request_data.email)
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

@router.get("/notifications")
async def get_notifications(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False
):
    """Get user notifications with pagination"""
    try:
        user_email = request.headers.get("X-User-Email", "user@example.com")
        notifications = await notifications_service.get_notifications(user_email, limit, offset, unread_only)
        # Calculate unread count
        unread_count = len([n for n in notifications if not n.get("read", False)])
        return {
            "notifications": notifications,
            "total_count": len(notifications),
            "unread_count": unread_count
        }
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications")
async def create_notification(request: Request):
    """Create a new notification"""
    try:
        body = await request.json()
        user_email = request.headers.get("X-User-Email", "user@example.com")
        result = await notifications_service.create_notification(body, user_email)
        return {
            "success": True,
            "notification_id": str(result.get("notification_id", ""))
        }
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/notifications/mark-read")
async def mark_notifications_read(request: Request):
    """Mark specific notifications as read"""
    try:
        body = await request.json()
        notification_ids = body.get("notification_ids", [])
        updated_count = await notifications_service.mark_as_read(notification_ids)
        return {"success": True, "updated_count": updated_count}
    except Exception as e:
        logger.error(f"Error marking notifications as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/notifications/mark-all-read")
async def mark_all_notifications_read(request: Request):
    """Mark all notifications as read for the user"""
    try:
        user_email = request.headers.get("X-User-Email", "user@example.com")
        updated_count = await notifications_service.mark_all_as_read(user_email)
        return {"success": True, "updated_count": updated_count}
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
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
async def get_admin_chat_sessions(
    request: Request,
    agent_id: str = None,
    role: str = "admin",
    status: str = "active",
    page: int = 1,
    limit: int = 50
):
    """Get chat sessions for admin with real database integration"""
    try:
        # Get user email from request headers
        user_email = request.headers.get("X-User-Email", "admin@example.com")

        # Use chat_log_service to get sessions from real database
        sessions, total_count = await chat_log_service.get_chat_sessions(
            role=role,
            user_email=user_email,
            archive_status=status,
            page=page,
            limit=limit,
            agent_id=agent_id
        )

        # Convert sessions to dict format for JSON response
        sessions_data = []
        for session in sessions:
            if hasattr(session, 'dict'):
                sessions_data.append(session.dict())
            elif hasattr(session, '__dict__'):
                sessions_data.append(session.__dict__)
            else:
                sessions_data.append(session)

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        return {
            "success": True,
            "sessions": sessions_data,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }
    except Exception as e:
        logger.error(f"Error getting admin chat sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/chat-sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get all messages for a specific chat session"""
    try:
        messages = await chat_log_service.get_session_messages(session_id)

        # Format messages for response
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "id": str(msg.get("id", "")),
                "text": msg.get("content", ""),
                "sender": msg.get("role", "user"),
                "timestamp": msg.get("created_at").isoformat() if msg.get("created_at") else None,
                "session_id": session_id
            })

        return {
            "success": True,
            "messages": formatted_messages,
            "session_id": session_id
        }
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/messages")
async def send_agent_message(session_id: str, request: Request):
    """Send a message from an agent to a customer in a chat session"""
    try:
        body = await request.json()
        text = body.get("text", "")
        agent_id = body.get("agent_id", request.headers.get("X-User-Email", "agent@example.com"))

        if not text:
            raise HTTPException(status_code=400, detail="Message text is required")

        message_id = await chat_log_service.send_agent_message(session_id, agent_id, text)

        return {
            "success": True,
            "message_id": str(message_id),
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending agent message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/admin/chat-sessions/{session_id}/archive")
async def archive_session(session_id: str, request: Request):
    """Archive a chat session"""
    try:
        body = await request.json()
        archive_status = body.get("status", "archived")
        user_email = request.headers.get("X-User-Email", "admin@example.com")

        await chat_log_service.archive_chat_session(session_id, archive_status, user_email)

        return {
            "success": True,
            "message": f"Session {archive_status} successfully",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/end-agent")
async def end_agent_session(session_id: str, request: Request):
    """End a chat session from the agent side"""
    try:
        user_email = request.headers.get("X-User-Email", "agent@example.com")

        await chat_log_service.update_chat_session(
            session_id=session_id,
            user_email=user_email,
            status="closed"
        )

        return {
            "success": True,
            "message": "Session ended by agent",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending agent session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/end-customer")
async def end_customer_session(session_id: str, request: Request):
    """End a chat session from the customer side"""
    try:
        user_email = request.headers.get("X-User-Email", "customer@example.com")

        await chat_log_service.end_customer_session(session_id, user_email)

        return {
            "success": True,
            "message": "Session ended by customer",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending customer session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/transfer")
async def transfer_session(session_id: str, request: Request):
    """Transfer a chat session to another agent"""
    try:
        body = await request.json()
        target_agent_email = body.get("target_agent_email")
        user_email = request.headers.get("X-User-Email", "agent@example.com")

        if not target_agent_email:
            raise HTTPException(status_code=400, detail="Target agent email is required")

        await chat_log_service.transfer_chat_session(session_id, user_email, target_agent_email)

        return {
            "success": True,
            "message": f"Session transferred to {target_agent_email}",
            "session_id": session_id,
            "transferred_to": target_agent_email
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/feedback")
async def update_session_feedback(session_id: str, request: Request):
    """Update feedback for a chat session"""
    try:
        body = await request.json()
        feedback = body.get("feedback")  # positive or negative
        user_type = body.get("user_type", "customer")  # customer or agent
        user_email = request.headers.get("X-User-Email", "user@example.com")

        if feedback not in ["positive", "negative"]:
            raise HTTPException(status_code=400, detail="Feedback must be 'positive' or 'negative'")

        await chat_log_service.update_chat_session(
            session_id=session_id,
            user_email=user_email,
            feedback=feedback,
            user_type=user_type
        )

        # Also record in chat_feedback table via service
        await chat_log_service.record_session_feedback(session_id, feedback, user_type)

        return {
            "success": True,
            "message": "Feedback recorded",
            "session_id": session_id,
            "feedback": feedback
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating session feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/{session_id}/request-agent")
async def request_human_agent(session_id: str):
    """Request a human agent for a chat session"""
    try:
        assigned_agent = await chat_log_service.request_human_agent(session_id)

        return {
            "success": True,
            "message": "Human agent assigned",
            "agent_assigned": assigned_agent,
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/unique-id")
async def create_or_get_unique_id(request: Request):
    """Create or get unique user ID by email and role"""
    try:
        body = await request.json()
        email = body.get("email")
        role = body.get("role", "customer")

        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        result = await auth_service.get_or_create_unique_id(email, role)
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating/getting unique ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/unique-id")
async def get_user_unique_id(email: str, role: str = "customer"):
    """Get unique ID for a user by email and role"""
    try:
        result = await auth_service.get_or_create_unique_id(email, role)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error getting user unique ID: {e}")
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
    """Submit feedback for a chat message"""
    try:
        user_email = request.headers.get("X-User-Email", "anonymous@example.com")
        result = await feedback_service.submit_feedback(
            message_id=feedback.message_id,
            session_id=feedback.session_id,
            feedback=feedback.feedback,
            user_email=user_email
        )
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
        try:
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
            
        except Exception as e:
            logger.error(f"❌ Error getting user role: {e}")
            # Fallback to user role if auth service fails
            user_roles = ["user"]
            logger.info(f"🔍 Using fallback roles: {user_roles}")
        
        # Determine primary role (admin > human_agent > user)
        primary_role = "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        logger.info(f"🔍 Primary role: {primary_role}")
        
        # Return authenticated user profile with actual role
        profile = {
            "email": user.get("email"),
            "uid": user.get("uid"),
            "display_name": user.get("name", user.get("email")),  # Frontend expects display_name
            "photo_url": user.get("picture"),  # Frontend expects photo_url
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
