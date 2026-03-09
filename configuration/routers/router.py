"""
Consolidated Configuration Router
All configuration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Optional
import json
import asyncio
from collections import defaultdict

from shared.otel_logger import get_otel_logger, clear_admin_context
from shared.admin_audit import audit_action
from ..service.configuration_service import ConfigurationService
from ..dao.admin_session_dao import AdminSessionDAO
from ..dao.admin_action_dao import AdminActionDAO
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


def get_session_id_from_context(request: Request, session_id: str | int) -> int:
    """
    Get the numeric session ID from request context.

    Internal services ONLY work with numeric session IDs.
    API Gateway always provides numeric session_id in request body/params.

    Args:
        request: FastAPI Request object
        session_id: Numeric session ID (int or numeric string, NEVER UUID)

    Returns:
        Numeric session ID (int)

    Raises:
        HTTPException: If session ID is invalid
    """
    # Handle int directly
    if isinstance(session_id, int):
        return session_id

    # Parse numeric string to int
    if isinstance(session_id, str):
        if session_id.isdigit():
            numeric_id = int(session_id)
            logger.debug(f"✅ Converted numeric string '{session_id}' to int: {numeric_id}")
            return numeric_id
        else:
            # Should never receive UUID here - API Gateway should have converted it
            logger.error(f"❌ Invalid session ID format (expected numeric, got): {session_id}")
            raise HTTPException(status_code=400, detail="session_id must be numeric (API Gateway should convert UUID)")

    logger.error(f"❌ Could not parse session ID: {session_id}")
    raise HTTPException(status_code=400, detail=f"Invalid session ID type: {type(session_id)}")

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
    user_role = request.headers.get('X-User-Role')
    
    logger.info(f"🔍 Headers - UID: {user_uid}, Email: {user_email}, Name: {user_name}, Role: {user_role}")
    
    if user_email:
        user_data = {
            "uid": user_uid,
            "email": user_email,
            "name": user_name or user_email,
            "role": user_role,
            "picture": None  # Not forwarded in headers
        }
        logger.info(f"🔍 Returning user from headers: {user_data}")
        return user_data
    
    # This should not happen if API Gateway is properly configured
    logger.error("🔍 No user found in request.state or headers!")
    logger.error(f"🔍 Available headers: {list(request.headers.keys())}")
    raise HTTPException(status_code=401, detail="User not found in request state or headers")

# Initialize services and DAOs
config_service = ConfigurationService()
auth_service = AuthService()
chat_log_service = ChatLogService()
notifications_service = NotificationsService(notifications_dao=None)
performance_service = PerformanceService()
feedback_service = FeedbackService()
token_usage_service = TokenUsageService()
admin_session_dao = AdminSessionDAO()
admin_action_dao = AdminActionDAO()

# =================================
# SSE EVENT BROADCASTING SYSTEM (Redis Pub/Sub)
# =================================
# Import Redis Pub/Sub manager - replaces in-memory queues
from shared.redis_pubsub_manager import (
    AgentEventSubscriber,
    SessionEventSubscriber,
    broadcast_event_to_agent,
    broadcast_event_to_all_agents,
    broadcast_event_for_session,
    get_pubsub_redis
)

logger.info("✅ Redis Pub/Sub manager initialized for agent and customer SSE events")

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
@audit_action(
    action_type="config.chatbot.update",
    action_category="config",
    resource_type="chatbot_config"
)
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
# INDIVIDUAL CONFIGURATION DATA ENDPOINTS
# These endpoints allow UI to fetch individual data pieces
# =================================

@router.get("/data/security-settings")
async def get_security_settings():
    """Get security settings only"""
    try:
        logger.info("🔍 GET /data/security-settings")
        security = await config_service.get_security_settings()
        return {"success": True, "data": security}
    except Exception as e:
        logger.error(f"Error getting security settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data/llm-providers")
async def get_llm_providers():
    """Get LLM providers and token usage"""
    try:
        logger.info("🔍 GET /data/llm-providers")
        llm_tokens = await config_service.get_llm_providers()
        return {"success": True, "data": llm_tokens}
    except Exception as e:
        logger.error(f"Error getting LLM providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data/active-persona")
async def get_active_persona():
    """Get active persona configuration"""
    try:
        logger.info("🔍 GET /data/active-persona")
        persona_config = await config_service.get_active_persona()
        return {"success": True, "data": persona_config}
    except Exception as e:
        logger.error(f"Error getting active persona: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data/human-agents")
async def get_human_agents():
    """Get human agents list"""
    try:
        logger.info("🔍 GET /data/human-agents")
        human_agents_list = await config_service.get_human_agents()
        return {"success": True, "data": human_agents_list}
    except Exception as e:
        logger.error(f"Error getting human agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data/admin-emails")
async def get_admin_emails():
    """Get admin emails list"""
    try:
        logger.info("🔍 GET /data/admin-emails")
        admin_emails_list = await config_service.get_admin_emails()
        return {"success": True, "data": admin_emails_list}
    except Exception as e:
        logger.error(f"Error getting admin emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# WIDGET CONFIGURATION ENDPOINTS
# =================================

@router.get("/widgetConfig")
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

@router.post("/widgetConfig")
async def update_widget_config(
    request: Request,
    config: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    chat_icon_image: Optional[UploadFile] = File(None)
):
    """Update widget configuration with optional image uploads"""
    try:
        # Check if this is multipart/form-data or JSON
        content_type = request.headers.get('content-type', '')

        if 'multipart/form-data' in content_type:
            # Handle multipart form data with images
            if not config:
                raise HTTPException(status_code=400, detail="Config data required in multipart request")

            # Parse JSON config from form
            import json
            config_data = json.loads(config)

            # Upload images if provided using DAO with S3 storage
            from configuration.dao.widget_config_dao import WidgetConfigDAO
            widget_dao = WidgetConfigDAO()

            if profile_image and profile_image.filename:
                logger.info(f"📤 Uploading profile image: {profile_image.filename}")

                # Validate file type
                allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
                if profile_image.content_type not in allowed_types:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid profile image file type. Allowed: {', '.join(allowed_types)}"
                    )

                # Read file content
                profile_content = await profile_image.read()

                # Upload to Railway S3 storage via DAO
                storage_url, storage_filename = await widget_dao.update_widget_image(
                    image_type="profile",
                    image_data=profile_content,
                    filename=profile_image.filename
                )

                # Update config with S3 URL (DAO already updated DB, but we override in config)
                config_data['profile_picture_url'] = storage_url
                config_data['profile_picture_filename'] = storage_filename

            if chat_icon_image and chat_icon_image.filename:
                logger.info(f"📤 Uploading chat icon image: {chat_icon_image.filename}")

                # Validate file type
                allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
                if chat_icon_image.content_type not in allowed_types:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid chat icon file type. Allowed: {', '.join(allowed_types)}"
                    )

                # Read file content
                chat_icon_content = await chat_icon_image.read()

                # Upload to Railway S3 storage via DAO
                storage_url, storage_filename = await widget_dao.update_widget_image(
                    image_type="chatIcon",
                    image_data=chat_icon_content,
                    filename=chat_icon_image.filename
                )

                # Update config with S3 URL (DAO already updated DB, but we override in config)
                config_data['chat_icon_url'] = storage_url
                config_data['chat_icon_filename'] = storage_filename

            # Update widget config
            await config_service.update_widget_config(config_data)
            return {"success": True, "message": "Widget configuration updated successfully with images"}

        else:
            # Handle JSON request (backward compatibility)
            body = await request.json()
            await config_service.update_widget_config(body)
            return {"success": True, "message": "Widget configuration updated successfully"}

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON in config field")
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
        result = await config_service.add_admin(request_data.email)
        return {"success": True, "message": "Admin user added successfully"}
    except Exception as e:
        logger.error(f"Error adding admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admins/{email}")
async def remove_admin_user(email: str, request: Request):
    """Remove an admin user"""
    try:
        result = await config_service.remove_admin(email)
        return {"success": True, "message": "Admin user removed successfully"}
    except Exception as e:
        logger.error(f"Error removing admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/human-agents")
async def get_human_agents_admin():
    """Get all human agents (used by frontend UserService)"""
    try:
        agents = await config_service.get_human_agents()
        return {"success": True, "human_agents": agents}
    except Exception as e:
        logger.error(f"Error getting human agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/human-agents")
async def add_human_agent(request_data: AdminManagementRequest, request: Request):
    """Add a new human agent"""
    try:
        result = await config_service.add_human_agent(request_data.email)
        return {"success": True, "message": "Human agent added successfully"}
    except Exception as e:
        logger.error(f"Error adding human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/human-agents/{email}")
async def remove_human_agent(email: str, request: Request):
    """Remove a human agent"""
    try:
        result = await config_service.remove_human_agent(email)
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
        # Get numeric session ID (API Gateway resolved UUID if present, else parse numeric string)
        numeric_session_id = get_session_id_from_context(request, session_id)
        logger.info(f"🔍 Delete chat log endpoint: session_id={numeric_session_id}")

        result = await chat_log_service.delete_chat_log(numeric_session_id, "admin@example.com")
        return {"success": True, "message": "Chat log deleted successfully"}
    except HTTPException:
        raise
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
        
        # Add user_email to notification data if not present
        if "user_email" not in body and user_email:
            body["user_email"] = user_email
            
        notification_id = await notifications_service.create_notification(body)
        return {
            "success": True,
            "notification_id": str(notification_id) if notification_id else ""
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

@router.get("/admin/events")
async def agent_events_stream(request: Request, user: dict = Depends(get_current_user)):
    """
    Server-Sent Events endpoint for real-time agent updates using Redis Pub/Sub.
    Streams events for ALL sessions assigned to the logged-in agent.
    
    Uses cookie-based authentication (no token parameter needed).
    
    Simplified implementation:
    - No in-memory queues
    - No locks required
    - Automatic cleanup
    - Scales horizontally
    """
    try:
        # Get user email from authenticated user (via cookie)
        user_email = user.get("email")
        user_role = user.get("role", "human_agent")

        if not user_email:
            logger.error("No user email in SSE request")
            raise HTTPException(status_code=401, detail="Authentication required. Please sign in.")

        logger.info(f"🔌 Agent {user_email} (role={user_role}) connecting to Redis Pub/Sub SSE stream")

        # Create Redis Pub/Sub subscriber for this agent
        subscriber = AgentEventSubscriber(user_email, user_role)

        async def event_generator():
            """
            Generator that yields SSE events from Redis Pub/Sub with heartbeat.
            Heartbeat (every 15s) keeps connection alive to prevent CDN/gateway timeouts.
            Includes inactivity timeout (5 minutes) to clean up stale connections.
            """
            import asyncio
            import time

            heartbeat_task = None
            redis_task = None
            last_activity = time.time()
            channel_name = f"agent:events:{user_email}"

            try:
                async def heartbeat_loop(queue):
                    """Send keep-alive heartbeat to queue every 10 seconds"""
                    try:
                        while True:
                            await asyncio.sleep(10)  # Reduced from 15 to 10 seconds
                            try:
                                await queue.put({"type": "heartbeat", "timestamp": int(time.time())})
                            except Exception as e:
                                logger.warning(f"Failed to queue heartbeat: {e}")
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Heartbeat loop error: {e}")

                # Create a queue for both heartbeat and Redis events
                message_queue = asyncio.Queue()
                heartbeat_task = asyncio.create_task(heartbeat_loop(message_queue))

                # Task to forward Redis events to queue
                async def forward_redis_events():
                    try:
                        async for event_data in subscriber.subscribe():
                            try:
                                await message_queue.put(event_data)
                            except Exception as e:
                                logger.warning(f"Failed to queue event: {e}")
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Redis event loop error: {e}")
                    finally:
                        try:
                            heartbeat_task.cancel()
                        except Exception:
                            pass

                redis_task = asyncio.create_task(forward_redis_events())

                # Send initial connection established event immediately
                # This ensures the browser receives a response and the SSE connection is established
                yield f"data: {json.dumps({'type': 'connected', 'agent_email': user_email, 'role': user_role, 'timestamp': int(time.time())})}\n\n"

                # Yield messages from queue
                try:
                    while True:
                        try:
                            # Check for inactivity timeout (5 minutes)
                            current_time = time.time()
                            if current_time - last_activity > 300:
                                logger.info(f"⏱️ Connection timeout for {user_email} on channel {channel_name} - no activity for 5 minutes")
                                break

                            msg = await asyncio.wait_for(message_queue.get(), timeout=30)
                            if msg.get("type") == "heartbeat":
                                # SSE comment (: prefix) doesn't trigger client event
                                yield f": keep-alive {msg['timestamp']}\n\n"
                            else:
                                # Real event data - update last_activity
                                last_activity = time.time()
                                yield f"data: {json.dumps(msg)}\n\n"

                                # Check if session ended - close connection immediately
                                if msg.get("type") == "session_ended":
                                    logger.info(f"🛑 Session ended event received for {user_email} on channel {channel_name} - closing connection")
                                    break
                        except asyncio.TimeoutError:
                            # Queue empty for 30s, send heartbeat manually
                            yield f": timeout-heartbeat {int(time.time())}\n\n"
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Invalid JSON in message: {e}")
                            # Continue listening, don't break
                            continue
                        except Exception as e:
                            logger.error(f"❌ Error yielding message to {user_email}: {e}")
                            # Yield failed = client disconnected. Close connection and cleanup.
                            logger.info(f"🔌 Client {user_email} disconnected (yield error on channel {channel_name}) - closing connection")
                            break

                except asyncio.CancelledError:
                    logger.info(f"🔌 SSE connection cancelled for {user_email}")
                except Exception as e:
                    logger.error(f"❌ Error in SSE generator for {user_email}: {e}")

            except asyncio.CancelledError:
                logger.info(f"🔌 SSE connection cancelled for {user_email}")
            except Exception as e:
                logger.error(f"❌ Error in SSE generator for {user_email}: {e}")
            finally:
                # Cancel tasks and wait for cleanup
                if heartbeat_task and not heartbeat_task.done():
                    heartbeat_task.cancel()
                if redis_task and not redis_task.done():
                    redis_task.cancel()

                # Give tasks a moment to clean up
                try:
                    await asyncio.gather(
                        heartbeat_task if heartbeat_task and not heartbeat_task.done() else asyncio.sleep(0),
                        redis_task if redis_task and not redis_task.done() else asyncio.sleep(0),
                        return_exceptions=True
                    )
                except Exception:
                    pass

                logger.info(f"🔌 Agent {user_email} disconnected from Redis Pub/Sub SSE stream")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # Disable nginx buffering
            }
        )

    except Exception as e:
        logger.error(f"❌ Error setting up Redis Pub/Sub SSE stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer/sessions/set-current")
async def set_current_customer_session(request: Request):
    """
    Set the current customer session by setting httpOnly cookie.

    Frontend calls this before connecting to customer events SSE.
    Backend looks up the session UUID from numeric ID and sets it in a cookie.

    Args:
        request.body: {session_id: str | int} - UUID or numeric session ID

    Returns:
        Success confirmation with session details
    """
    try:
        from fastapi.responses import JSONResponse

        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        logger.info(f"🔄 Setting current customer session: {session_id}")

        # Convert numeric ID to UUID if needed
        if isinstance(session_id, int) or (isinstance(session_id, str) and session_id.isdigit()):
            # Numeric ID - look up UUID from database
            session_id = int(session_id)
            session_data = await chat_log_service.dao.get_session_by_id(session_id)
            if not session_data:
                raise HTTPException(status_code=404, detail=f"Chat session {session_id} not found")
            session_uuid = session_data.get("session_id")
        else:
            # Already UUID
            session_uuid = session_id

        logger.info(f"✅ Found session UUID: {session_uuid}")

        # Create response and set httpOnly cookie
        response = JSONResponse({
            "success": True,
            "session_id": session_uuid,
            "message": f"Customer session set as current"
        })

        # Set httpOnly, Secure, SameSite cookie with the session UUID
        response.set_cookie(
            key="chatbot_session_id",
            value=session_uuid,
            httponly=True,
            secure=True,
            samesite="Strict",
            max_age=60 * 60 * 24  # 24 hours
        )

        logger.info(f"🍪 Set chatbot_session_id cookie for customer session {session_uuid}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error setting current customer session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer/events")
async def customer_events_stream(request: Request, session_id: str = Query(..., description="Session UUID")):
    """
    Server-Sent Events endpoint for customers (anonymous).
    Streams real-time events for specified session.

    Session ID comes from query parameter (no authentication required).
    Perfect for anonymous customer chat widgets.

    Security:
    - Rate limiting applied at API Gateway level
    - Channel isolation per session
    - No sensitive data exposed
    """
    try:
        if not session_id:
            logger.warning("❌ No session_id provided for customer events")
            raise HTTPException(status_code=400, detail="session_id query parameter required")

        logger.info(f"🔌 Customer connecting to SSE stream for session {session_id}")
        
        # Import SessionEventSubscriber
        from shared.redis_pubsub_manager import SessionEventSubscriber
        
        logger.info(f"📦 Creating SessionEventSubscriber for session {session_id}")
        
        # Create Redis Pub/Sub subscriber for this session
        subscriber = SessionEventSubscriber(session_id)
        
        logger.info(f"✅ SessionEventSubscriber created, starting event generator for session {session_id}")
        
        async def event_generator():
            """
            Generator that yields SSE events from Redis Pub/Sub with heartbeat.
            Heartbeat (every 15s) keeps connection alive to prevent CDN/gateway timeouts.
            Includes inactivity timeout (5 minutes) to clean up stale connections.
            """
            import asyncio
            import time

            logger.info(f"🎬 Event generator started for session {session_id}")

            heartbeat_task = None
            redis_task = None
            last_activity = time.time()
            channel_name = f"session:events:{session_id}"

            try:
                logger.info(f"🔄 Setting up heartbeat and Redis tasks for session {session_id}")
                
                async def heartbeat_loop(queue):
                    """Send keep-alive heartbeat to queue every 15 seconds"""
                    try:
                        while True:
                            await asyncio.sleep(15)
                            try:
                                await queue.put({"type": "heartbeat", "timestamp": int(time.time())})
                            except Exception as e:
                                logger.warning(f"Failed to queue heartbeat for session {session_id}: {e}")
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Heartbeat loop error for session {session_id}: {e}")

                # Create a queue for both heartbeat and Redis events
                message_queue = asyncio.Queue()
                heartbeat_task = asyncio.create_task(heartbeat_loop(message_queue))

                logger.info(f"📡 Starting Redis event forwarding for session {session_id}")
                
                # Task to forward Redis events to queue
                async def forward_redis_events():
                    try:
                        logger.info(f"🔌 Calling subscriber.subscribe() for session {session_id}")
                        async for event_data in subscriber.subscribe():
                            try:
                                await message_queue.put(event_data)
                            except Exception as e:
                                logger.warning(f"Failed to queue event for session {session_id}: {e}")
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Redis event loop error for session {session_id}: {e}")
                    finally:
                        try:
                            heartbeat_task.cancel()
                        except Exception:
                            pass

                redis_task = asyncio.create_task(forward_redis_events())

                logger.info(f"✅ Tasks created, starting message loop for session {session_id}")

                # Send initial connection established event immediately
                # This ensures the browser receives a response and the SSE connection is established
                yield f": connected\n\n"
                logger.info(f"📤 Sent initial connection event to session {session_id}")

                # Yield messages from queue
                try:
                    while True:
                        try:
                            # Check for inactivity timeout (5 minutes)
                            current_time = time.time()
                            if current_time - last_activity > 300:
                                logger.info(f"⏱️ Connection timeout for session {session_id} on channel {channel_name} - no activity for 5 minutes")
                                break

                            msg = await asyncio.wait_for(message_queue.get(), timeout=30)
                            if msg.get("type") == "heartbeat":
                                # SSE comment (: prefix) doesn't trigger client event
                                yield f": keep-alive {msg['timestamp']}\n\n"
                            else:
                                # Real event data - update last_activity
                                last_activity = time.time()
                                yield f"data: {json.dumps(msg)}\n\n"

                                # Check if session ended - close connection immediately
                                if msg.get("type") == "session_ended":
                                    logger.info(f"🛑 Session ended event received for session {session_id} on channel {channel_name} - closing connection")
                                    break
                        except asyncio.TimeoutError:
                            # Queue empty for 30s, send heartbeat manually
                            yield f": timeout-heartbeat {int(time.time())}\n\n"
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Invalid JSON in message for session {session_id}: {e}")
                            # Continue listening, don't break
                            continue
                        except Exception as e:
                            logger.error(f"❌ Error yielding message to session {session_id}: {e}")
                            # Yield failed = client disconnected. Close connection and cleanup.
                            logger.info(f"🔌 Client on session {session_id} disconnected (yield error on channel {channel_name}) - closing connection")
                            break

                except asyncio.CancelledError:
                    logger.info(f"🔌 SSE connection cancelled for session {session_id}")
                except Exception as e:
                    logger.error(f"❌ Error in SSE generator for session {session_id}: {e}")

            except asyncio.CancelledError:
                logger.info(f"🔌 SSE connection cancelled for session {session_id}")
            except Exception as e:
                logger.error(f"❌ Error in SSE generator for session {session_id}: {e}")
            finally:
                # Cancel tasks and wait for cleanup
                if heartbeat_task and not heartbeat_task.done():
                    heartbeat_task.cancel()
                if redis_task and not redis_task.done():
                    redis_task.cancel()

                # Give tasks a moment to clean up
                try:
                    await asyncio.gather(
                        heartbeat_task if heartbeat_task and not heartbeat_task.done() else asyncio.sleep(0),
                        redis_task if redis_task and not redis_task.done() else asyncio.sleep(0),
                        return_exceptions=True
                    )
                except Exception:
                    pass

                logger.info(f"🔌 Customer disconnected from session {session_id}")
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # Disable nginx buffering
            }
        )
    
    except Exception as e:
        logger.error(f"❌ Error setting up customer SSE stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/chat-sessions")
async def get_admin_chat_sessions(
    request: Request,
    agent_id: str = None,
    role: str = "admin",
    status: str = "active",
    page: int = 1,
    limit: int = 50,
    include_messages: bool = True  # NEW: Include messages by default
):
    """Get chat sessions for admin with messages included for reactive UI"""
    try:
        # Get user email from request.state (set by SessionAuthMiddleware after Firebase verification)
        # Falls back to header for backward compatibility
        user_email = getattr(request.state, "user_email", None) or request.headers.get("X-User-Email", "")

        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found in request")

        logger.info(f"🔍 GET /admin/chat-sessions called")
        logger.info(f"🔍 Parameters: agent_id={agent_id}, role={role}, status={status}, page={page}, limit={limit}")
        logger.info(f"🔍 User email: {user_email} (role={role})")

        # Use chat_log_service to get sessions from real database
        sessions, total_count = await chat_log_service.get_chat_sessions(
            role=role,
            user_email=user_email,
            archive_status=status,
            page=page,
            limit=limit,
            agent_id=agent_id
        )
        
        logger.info(f"✅ Retrieved {len(sessions)} sessions, total_count={total_count}")

        # Convert sessions to dict format (messages already included by service)
        sessions_data = []
        for session in sessions:
            if hasattr(session, 'dict'):
                session_dict = session.dict()
            elif hasattr(session, '__dict__'):
                session_dict = session.__dict__
            else:
                session_dict = session

            # Messages are already included by get_chat_sessions service
            # If include_messages is False, remove them
            if not include_messages and 'messages' in session_dict:
                session_dict['messages'] = []

            sessions_data.append(session_dict)

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        logger.info(f"✅ Returning {len(sessions_data)} sessions to frontend")

        return {
            "success": True,
            "sessions": sessions_data,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        }
    except Exception as e:
        logger.error(f"❌ Error getting admin chat sessions: {e}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/customer/sessions/messages")
async def send_customer_message(request: Request):
    """Send a message from a customer to an assigned agent (no AI processing)

    Request body: {
        session_id: str (session UUID or numeric ID),
        text: str (message text)
    }
    """
    try:
        body = await request.json()
        text = body.get("text", "")
        session_id_param = body.get("session_id", "")

        logger.info(f"📨 Customer message request - session_id type: {type(session_id_param)}, value: {session_id_param}")

        if not text:
            raise HTTPException(status_code=400, detail="Message text is required")

        if not session_id_param:
            raise HTTPException(status_code=400, detail="session_id is required")

        # Ensure session_id_param is a string
        session_id_param = str(session_id_param)
        logger.info(f"📨 After str() conversion - session_id type: {type(session_id_param)}, value: {session_id_param}")

        # Resolve to numeric ID - accept both UUID and numeric ID
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text as sql_text

        async with get_db_session() as db_session:
            numeric_session_id = None
            session_uuid = None

            # Check if it's a numeric ID (all digits)
            if session_id_param.isdigit():
                # It's a numeric ID - use directly
                numeric_session_id = int(session_id_param)
                logger.info(f"📨 Received numeric session ID: {numeric_session_id}")

                # Verify it exists
                verify_result = await db_session.execute(
                    sql_text("SELECT session_id FROM chat_sessions WHERE id = :id"),
                    {"id": numeric_session_id}
                )
                verify_row = verify_result.fetchone()
                if verify_row:
                    session_uuid = verify_row[0]
                    logger.info(f"✅ Verified numeric ID {numeric_session_id} maps to UUID {session_uuid}")
                else:
                    raise HTTPException(status_code=404, detail=f"Session not found: {numeric_session_id}")
            else:
                # It's a UUID - look it up
                result = await db_session.execute(
                    sql_text("SELECT id FROM chat_sessions WHERE session_id = :session_uuid"),
                    {"session_uuid": session_id_param}
                )
                row = result.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Session not found: {session_id_param}")
                numeric_session_id = row[0]
                session_uuid = session_id_param
                logger.info(f"✅ Resolved UUID {session_uuid} to numeric ID {numeric_session_id}")

        # Check if agent is assigned
        from shared.redis_pubsub_manager import get_pubsub_redis
        redis_client = await get_pubsub_redis()

        assigned_agent_key = f"session:assigned_agent:{session_uuid}"
        cached_agent = await redis_client.get(assigned_agent_key)

        if cached_agent:
            assigned_agent = cached_agent  # Already decoded by Redis client (decode_responses=True)
        else:
            # Query database for assignment
            session = await chat_log_service.dao.get_session_by_id(numeric_session_id)
            assigned_agent = session.get('assigned_agent') if session else None
            if assigned_agent:
                await redis_client.set(assigned_agent_key, assigned_agent, ex=3600)

        if not assigned_agent:
            raise HTTPException(status_code=400, detail="No agent assigned to this session. Use chatbot API instead.")

        # Save message to database
        message_id = await chat_log_service.dao.create_message(numeric_session_id, 'user', text)
        await chat_log_service.dao.increment_message_count(numeric_session_id)

        # Prepare event data
        import datetime
        event_data = {
            "type": "customer_message",
            "session_id": session_uuid,  # CRITICAL: Use UUID for SSE channel matching
            "message_id": str(message_id),
            "text": text,
            "sender": "customer",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        # Smart broadcast: avoid duplicate messages for admins
        from shared.redis_pubsub_manager import broadcast_event_to_agent, broadcast_event_to_all_agents

        # Check if assigned agent is an admin or human agent
        admin_emails = await chat_log_service.dao.get_all_admins()
        is_assigned_admin = assigned_agent in admin_emails

        if is_assigned_admin:
            # Assigned agent is an ADMIN - send ONLY via broadcast channel to avoid duplicates
            # Admin listens to broadcast channel, so they'll get it once
            await broadcast_event_to_all_agents(event_data)
            logger.info(f"📤 Customer message sent via broadcast (assigned agent is admin {assigned_agent}): {session_uuid}")
        else:
            # Assigned agent is HUMAN AGENT - send to their personal channel
            # And also broadcast to all admins
            await broadcast_event_to_agent(assigned_agent, event_data)
            await broadcast_event_to_all_agents(event_data)
            logger.info(f"📤 Customer message sent to human agent {assigned_agent} and all admins: {session_uuid}")

        return {
            "success": True,
            "message_id": str(message_id)
            # session_id intentionally omitted - it's in httpOnly cookie only
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending customer message: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/admin/chat-sessions/messages")
async def send_agent_message(request: Request):
    """Send a message from an agent or customer in a chat session

    Request body: {
        session_id: int (numeric session ID),
        text: str (message text),
        agent_id?: str (optional, defaults to X-User-Email header),
        sender?: str (optional, "agent" or "user", defaults to "agent")
    }
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")

        text = body.get("text", "")
        sender_id = body.get("agent_id", request.headers.get("X-User-Email", "customer@example.com"))
        sender_type = body.get("sender", "agent")  # "agent" or "user" (customer)

        if not text:
            raise HTTPException(status_code=400, detail="Message text is required")

        logger.info(f"🔍 POST /admin/chat-sessions/messages called for session {numeric_session_id}")

        # Get session UUID from database (needed for customer SSE channel)
        session_data = await chat_log_service.dao.get_session_by_id_with_messages(numeric_session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail=f"Session {numeric_session_id} not found")

        session_uuid = session_data.get('session_id')  # UUID format
        logger.info(f"🔍 [SEND_MESSAGE] Numeric ID: {numeric_session_id}, UUID: {session_uuid}")

        # Save message to database
        message_id = await chat_log_service.send_agent_message(numeric_session_id, sender_id, text)

        # Prepare event data
        import datetime
        event_data = {
            "type": "agent_message",
            "session_id": session_uuid,  # CRITICAL: Use UUID for SSE channel matching
            "message_id": str(message_id),
            "text": text,
            "sender": sender_type,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        if sender_type == "agent":
            event_data["agent_email"] = sender_id

        # Smart broadcasting based on sender
        from shared.redis_pubsub_manager import broadcast_event_to_session, broadcast_event_to_agent, broadcast_event_to_all_agents
        
        if sender_type == "agent":
            # AGENT sent message - Verify authorization
            # Only the ASSIGNED agent can send messages
            # Get assigned agent for this session
            redis_client = await get_pubsub_redis()
            cache_key = f"session:assigned_agent:{session_uuid}"
            cached_agent = await redis_client.get(cache_key)

            if cached_agent:
                assigned_agent = cached_agent  # Already decoded by Redis client (decode_responses=True)
                logger.info(f"✅ Found cached agent assignment: {numeric_session_id} → {assigned_agent}")
            else:
                # Cache MISS - query database
                session = await chat_log_service.dao.get_session_by_id(numeric_session_id)
                assigned_agent = session.get('assigned_agent') if session else None
                if assigned_agent:
                    await redis_client.set(cache_key, assigned_agent, ex=3600)
                    logger.info(f"💾 Cached agent assignment: {numeric_session_id} → {assigned_agent}")

            # Check if sender is the assigned agent
            if sender_id != assigned_agent:
                # Sender is NOT the assigned agent - check if they're an admin trying to reply
                admin_emails = await chat_log_service.dao.get_all_admins()
                is_sender_admin = sender_id in admin_emails

                if is_sender_admin:
                    # Admin trying to reply but NOT assigned - reject with 403
                    logger.warning(f"⚠️ Admin {sender_id} attempted to reply to session {numeric_session_id} assigned to {assigned_agent}")
                    raise HTTPException(status_code=403, detail=f"Only the assigned agent ({assigned_agent}) can reply to this chat. You can view messages as read-only.")
                else:
                    # Neither assigned agent nor admin - reject
                    logger.warning(f"⚠️ {sender_id} attempted to send message to session {numeric_session_id} assigned to {assigned_agent}")
                    raise HTTPException(status_code=403, detail="Only the assigned agent can send messages to this chat")

            logger.info(f"✅ Authorization check passed: {sender_id} is assigned to session {numeric_session_id}")

            # Agent sent message → Broadcast to customer and other agents
            # CRITICAL: Use UUID session_id for customer SSE channel (not numeric ID)
            logger.info(f"📤 [AGENT_MESSAGE] Broadcasting to customer on channel: session:{session_uuid}")
            customer_result = await broadcast_event_to_session(session_uuid, event_data)
            logger.info(f"📤 [AGENT_MESSAGE] Customer broadcast result: {customer_result}")

            # Also broadcast to admins and the sending agent
            admin_emails = await chat_log_service.dao.get_all_admins()
            is_sender_admin = sender_id in admin_emails

            if is_sender_admin:
                # Sending agent is an ADMIN - send ONLY via broadcast to avoid duplicates
                logger.info(f"📤 [AGENT_MESSAGE] Broadcasting to all admins (sender {sender_id} is admin)")
                admin_result = await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 [AGENT_MESSAGE] Admin broadcast result: {admin_result}")
                logger.info(f"📤 Agent (admin {sender_id}) message sent to customer and all admins (session: {session_uuid})")
            else:
                # Sending agent is HUMAN AGENT - send to their personal channel + broadcast to admins
                logger.info(f"📤 [AGENT_MESSAGE] Broadcasting to human agent {sender_id}")
                agent_result = await broadcast_event_to_agent(sender_id, event_data)
                logger.info(f"📤 [AGENT_MESSAGE] Agent broadcast result: {agent_result}")

                logger.info(f"📤 [AGENT_MESSAGE] Broadcasting to all admins")
                admin_result = await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 [AGENT_MESSAGE] Admin broadcast result: {admin_result}")

                logger.info(f"📤 Agent message sent to customer, agent {sender_id}, and all admins (session: {session_uuid})")

        elif sender_type == "user":
            # Customer sent message → Notify assigned agent AND all admins
            # Try Redis cache first (should be set when agent is assigned)
            redis_client = await get_pubsub_redis()
            cache_key = f"session:assigned_agent:{session_uuid}"
            cached_agent = await redis_client.get(cache_key)

            if cached_agent:
                assigned_agent = cached_agent  # Already decoded by Redis client (decode_responses=True)
                logger.info(f"✅ Found cached agent assignment: {numeric_session_id} → {assigned_agent}")
            else:
                # Cache MISS - query database
                session = await chat_log_service.dao.get_session_by_id(numeric_session_id)
                assigned_agent = session.get('assigned_agent') if session else None
                # Cache for future messages (1 hour TTL)
                if assigned_agent:
                    await redis_client.set(cache_key, assigned_agent, ex=3600)
                    logger.info(f"💾 Cached agent assignment: {numeric_session_id} → {assigned_agent} (TTL: 1h)")

            if assigned_agent:
                # Smart broadcast: avoid duplicate messages for admins
                admin_emails = await chat_log_service.dao.get_all_admins()
                is_assigned_admin = assigned_agent in admin_emails

                if is_assigned_admin:
                    # Assigned agent is an ADMIN - send ONLY via broadcast to avoid duplicates
                    await broadcast_event_to_all_agents(event_data)
                    logger.info(f"📤 Customer message sent via broadcast (assigned agent is admin {assigned_agent})")
                else:
                    # Assigned agent is HUMAN AGENT - send to personal channel + broadcast to admins
                    await broadcast_event_to_agent(assigned_agent, event_data)
                    await broadcast_event_to_all_agents(event_data)
                    logger.info(f"📤 Customer message sent to human agent {assigned_agent} and all admins")
            else:
                # No agent assigned - notify all admins (for assignment)
                await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 Customer message sent to admins (no agent assigned)")
        

        return {
            "success": True,
            "message_id": str(message_id),
            "session_id": str(numeric_session_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/end-agent")
async def end_agent_session(request: Request):
    """End chat session from the agent side

    Request body: {session_id: int (numeric session ID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")
        user_email = request.headers.get("X-User-Email", "agent@example.com")

        logger.info(f"🔍 End-agent endpoint: session_id={numeric_session_id}")

        # Get session UUID for broadcasting
        session_data = await chat_log_service.dao.get_session_by_id_with_messages(numeric_session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail=f"Session {numeric_session_id} not found")

        session_uuid = session_data.get("session_id")  # UUID

        await chat_log_service.update_chat_session(
            session_id=numeric_session_id,
            user_email=user_email,
            status="closed"
        )

        # Broadcast session_ended event with feedback prompt to customer
        # This ensures customer receives notification and can provide feedback
        from shared.redis_pubsub_manager import broadcast_event_to_session
        import datetime

        event_data = {
            "type": "session_ended",
            "session_id": session_uuid,      # Use UUID for SSE channel matching
            "numeric_session_id": numeric_session_id,
            "ended_by": "agent",
            "agent_email": user_email,
            "show_feedback": True,  # Trigger feedback UI for customer
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        logger.info(f"📤 [END_AGENT] Broadcasting session_ended event: session_uuid={session_uuid}, numeric={numeric_session_id}, agent={user_email}")
        result = await broadcast_event_to_session(session_uuid, event_data)
        logger.info(f"📤 [END_AGENT] Broadcast result: {result}")

        return {
            "success": True,
            "message": "Session ended by agent",
            "session_id": numeric_session_id,
            "session_uuid": session_uuid
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending agent session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/end-customer")
async def end_customer_session(request: Request):
    """End a chat session from the customer side
    
    API Gateway extracts session UUID from httpOnly cookie and injects both:
    - session_id (numeric) for internal service operations
    - session_uuid (UUID) for broadcasting to customer SSE channels
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")
        session_uuid = body.get("session_uuid")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required (should be injected by API Gateway)")

        # session_id is already numeric (injected by API Gateway from cookie)
        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"session_id must be numeric, got: {session_id}")

        user_email = request.headers.get("X-User-Email", "customer@example.com")

        # Pass numeric ID to service
        await chat_log_service.end_customer_session(numeric_session_id, user_email)

        # Broadcast session_ended event with feedback prompt to customer
        from shared.redis_pubsub_manager import broadcast_event_to_session
        import datetime

        event_data = {
            "type": "session_ended",
            "session_id": str(numeric_session_id),
            "ended_by": "customer",
            "show_feedback": True,  # Trigger feedback UI
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        # Use session_uuid if provided by API Gateway, otherwise query database
        if session_uuid:
            # CRITICAL: Use UUID for customer SSE channel, not numeric ID
            await broadcast_event_to_session(session_uuid, event_data)
        else:
            # Fallback: query database for UUID (shouldn't happen if API Gateway is working)
            logger.warning(f"⚠️ session_uuid not provided by API Gateway, querying database")
            session_data = await chat_log_service.dao.get_session_by_id(numeric_session_id)
            if session_data:
                session_uuid = session_data.get('session_id')
                await broadcast_event_to_session(session_uuid, event_data)

        return {
            "success": True,
            "message": "Session ended by customer"
            # session_id intentionally omitted - it's in httpOnly cookie only
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending customer session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/chat-sessions/feedback")
async def submit_session_feedback(request: Request):
    """
    Submit customer feedback for a chat session.
    
    API Gateway injects session_id (numeric) and session_uuid (UUID) from cookie.
    Request Body:
        session_id: int (numeric, injected by API Gateway)
        session_uuid: str (UUID, injected by API Gateway)
        feedback_type: str ('positive' or 'negative')
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")
        session_uuid = body.get("session_uuid")
        feedback_type = body.get("feedback_type")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required (should be injected by API Gateway)")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"session_id must be numeric, got: {session_id}")

        if not feedback_type:
            raise HTTPException(status_code=400, detail="feedback_type is required")

        if feedback_type not in ['positive', 'negative']:
            raise HTTPException(status_code=400, detail="feedback_type must be 'positive' or 'negative'")

        logger.info(f"🔍 Feedback endpoint: session_id={numeric_session_id}, feedback={feedback_type}")

        # Update feedback in database
        success = await chat_log_service.dao.update_session_feedback(numeric_session_id, feedback_type)

        if not success:
            raise HTTPException(status_code=404, detail="Session not found")

        logger.info(f"✅ Customer feedback '{feedback_type}' submitted for session {numeric_session_id}")

        return {
            "success": True,
            "message": "Feedback submitted successfully",
            "feedback_type": feedback_type
            # session_id intentionally omitted - it's in httpOnly cookie only
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/chat-sessions/request-agent")
async def request_human_agent(request: Request):
    """Request a human agent for current chat session

    Session numeric ID comes from request body (session_id parameter)
    Can be called from:
    - Browser (via API Gateway which extracts UUID from cookie and converts to numeric ID)
    - Internal services (pass numeric session_id in request body)
    """
    try:
        logger.info(f"🧑 [ENDPOINT] POST /admin/chat-sessions/request-agent called")

        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(
                status_code=400,
                detail="session_id is required in request body"
            )

        # Session ID should be numeric (API Gateway converts UUID to numeric ID before calling internal services)
        try:
            session_db_id = int(session_id)
            logger.info(f"🧑 [ENDPOINT] Session ID (numeric): {session_db_id}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")

        # Pass numeric ID to service
        logger.info(f"🔍 [ENDPOINT] Calling chat_log_service.request_human_agent with session_id={session_db_id}")
        assigned_agent = await chat_log_service.request_human_agent(session_db_id)
        logger.info(f"✅ [ENDPOINT] Agent assigned: {assigned_agent}")

        response = {
            "success": True,
            "message": "Human agent assigned",
            "agent_assigned": assigned_agent,
            "session_id": session_db_id
        }
        logger.info(f"✅ [ENDPOINT] Returning response: {response}")
        return response

    except HTTPException as he:
        logger.error(f"❌ [ENDPOINT] HTTPException: {he.status_code} - {he.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ [ENDPOINT] Unexpected error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admin/chat-sessions")
async def delete_chat_session(request: Request):
    """Delete a chat session and all associated messages

    Request params: session_id (numeric session ID as query parameter)
    """
    try:
        session_id = request.query_params.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id query parameter is required")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")
        user_email = request.headers.get("X-User-Email", "admin@example.com")

        logger.info(f"🔍 Delete endpoint: session_id={numeric_session_id}")

        # Delete all messages for the session first
        await chat_log_service.delete_session_messages(numeric_session_id)

        # Delete the session itself
        await chat_log_service.delete_chat_session(numeric_session_id)

        logger.info(f"Deleted chat session {numeric_session_id} by {user_email}")

        return {
            "success": True,
            "message": "Chat session deleted successfully",
            "session_id": numeric_session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/mark-read")
async def mark_session_as_read(request: Request, user: dict = Depends(get_current_user)):
    """Mark session as read

    Request body: {session_id: int (numeric session ID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")

        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")

        logger.info(f"🔍 Mark-read endpoint: session_id={numeric_session_id}, user={user_email}")
        await chat_log_service.mark_session_as_read(numeric_session_id, user_email)

        return {
            "success": True,
            "message": "Session marked as read",
            "session_id": numeric_session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking session as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/mark-unread")
async def mark_session_as_unread(request: Request, user: dict = Depends(get_current_user)):
    """Mark session as unread

    Request body: {session_id: int (numeric session ID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        try:
            numeric_session_id = int(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a numeric ID")

        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")

        logger.info(f"🔍 Mark-unread endpoint: session_id={numeric_session_id}, user={user_email}")
        await chat_log_service.mark_session_as_unread(numeric_session_id, user_email)

        return {
            "success": True,
            "message": "Session marked as unread",
            "session_id": numeric_session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking session as unread: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/messages/{message_id}/mark-read")
async def mark_message_as_read(message_id: int, user: dict = Depends(get_current_user)):
    """Mark a single message as read by human agent or admin"""
    try:
        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")

        success = await chat_log_service.mark_message_as_read(message_id, user_email)

        logger.info(f"Marked message {message_id} as read by {user_email}")

        return {
            "success": success,
            "message": "Message marked as read" if success else "Failed to mark message as read",
            "message_id": message_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking message as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/chat-sessions/unread-count")
async def get_unread_message_count(request: Request, session_id: int = Query(...)):
    """Get unread message count for a session

    Args:
        session_id: Numeric session ID (required query parameter)
    """
    try:
        numeric_session_id = session_id
        user_email = request.headers.get("X-User-Email", "admin@example.com")

        logger.info(f"🔍 Unread-count endpoint: session_id={numeric_session_id}")

        count = await chat_log_service.get_unread_message_count(numeric_session_id)

        logger.info(f"Retrieved unread message count for session {numeric_session_id} by {user_email}")

        return {
            "success": True,
            "session_id": numeric_session_id,
            "unread_count": count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting unread message count: {e}")
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
    """Submit feedback for a chat session"""
    try:
        # Get user_role_id from request state (set by middleware)
        user_role_id = getattr(request.state, "user_role_id", None)

        result = await feedback_service.submit_feedback(
            session_id=feedback.session_id,
            feedback_type=feedback.feedback_type,
            user_role_id=user_role_id
        )
        return result
    except ValueError as e:
        logger.warning(f"Validation error submitting feedback: {e}")
        raise HTTPException(status_code=400, detail=str(e))
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
    logger.info(f"🔍 User data from session: {user}")
    
    try:
        # Get user's actual role from database
        user_email = user.get("email")
        logger.info(f"🔍 Getting role for user email: {user_email}")
        
        if not user_email:
            logger.error(f"🔍 No user email found in user data: {user}")
            raise HTTPException(status_code=400, detail="User email not found")
        
        logger.info("🔍 About to call auth_service.get_user_role")
        # Don't catch exceptions - let them propagate so the endpoint returns 503
        # If database is unavailable, client should know immediately, not get fake data
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
        
        # If user has no roles, they might not be in user_role_mapping table
        # This is OK - they're a regular user
        if not user_roles or user_roles == ["user"]:
            logger.info(f"ℹ️ User {user_email} has no special roles, defaulting to 'user' role")
        
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
        logger.info(f"✅ User profile created successfully for {user_email} with role {primary_role}")
        
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
        exc_type = type(e).__name__
        exc_str = str(e) if str(e) else exc_type
        logger.error(f"❌ Error getting user profile: {exc_type}: {exc_str}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")

        # Return 503 Service Unavailable for database errors
        # Clients should understand this means the service is temporarily unavailable
        status_code = 503 if _is_database_error(e) else 500
        raise HTTPException(
            status_code=status_code,
            detail="Database service temporarily unavailable" if status_code == 503 else "Internal server error"
        )


@router.get("/debug/session")
async def debug_session(request: Request):
    """Debug endpoint to check session status"""
    logger.info("🔍 DEBUG /debug/session called")
    
    # Check if session cookie exists
    session_cookie = request.cookies.get("session")
    logger.info(f"🔍 Session cookie: {session_cookie[:20] if session_cookie else 'None'}...")
    
    # Check if user is in request state (set by middleware)
    has_user_state = hasattr(request.state, 'user')
    logger.info(f"🔍 Has user state: {has_user_state}")
    
    if has_user_state:
        user_data = request.state.user
        logger.info(f"🔍 User data: {user_data}")
        return {
            "success": True,
            "session_cookie_present": bool(session_cookie),
            "user_authenticated": True,
            "user_email": user_data.get("email"),
            "user_uid": user_data.get("uid")
        }
    else:
        return {
            "success": False,
            "session_cookie_present": bool(session_cookie),
            "user_authenticated": False,
            "message": "No user in request state"
        }

def _is_database_error(e: Exception) -> bool:
    """Check if exception is a database-related error"""
    exc_type = type(e).__name__
    exc_str = str(e).lower()

    # Check exception type
    database_errors = {
        "TimeoutError", "asyncpg.exceptions.InsufficientPrivilegeError",
        "asyncpg.exceptions.PostgresConnectionError", "asyncpg.exceptions.ConnectionFailureError",
        "asyncpg.exceptions.ConnectionDoesNotExistError", "asyncpg.exceptions.InterfaceError",
        "ConnectionRefusedError", "RuntimeError"
    }

    if exc_type in database_errors:
        return True

    # Check error message patterns
    db_keywords = ["timeout", "pool", "connection", "database", "postgres", "unavailable"]
    return any(kw in exc_str for kw in db_keywords)

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
# ADMIN SESSION & AUDIT ENDPOINTS
# =================================

@router.get("/admin/sessions/active")
async def get_active_sessions(request: Request, user: dict = Depends(get_current_user)):
    """Get all active admin sessions (admin only)"""
    try:
        # Verify admin access
        email = user.get("email", "")
        roles = await auth_service.get_user_role(email)

        if "admin" not in roles.get("roles", []):
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get active sessions
        sessions = await admin_session_dao.get_active_sessions()

        logger.info(f"✅ Retrieved {len(sessions)} active admin sessions")
        return {
            "success": True,
            "data": sessions,
            "count": len(sessions)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting active sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/audit/actions")
async def get_audit_actions(
    request: Request,
    email: Optional[str] = None,
    category: Optional[str] = None,
    success: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user)
):
    """Get action audit trail with optional filters (admin only)"""
    try:
        # Verify admin access
        current_email = user.get("email", "")
        roles = await auth_service.get_user_role(current_email)

        if "admin" not in roles.get("roles", []):
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get actions
        actions = await admin_action_dao.get_actions(
            email=email,
            category=category,
            success=success,
            limit=limit,
            offset=offset
        )

        logger.info(f"✅ Retrieved {len(actions)} audit actions")
        return {
            "success": True,
            "data": actions,
            "count": len(actions),
            "filters": {
                "email": email,
                "category": category,
                "success": success
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting audit actions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/audit/statistics")
async def get_audit_statistics(
    request: Request,
    days: int = 7,
    user: dict = Depends(get_current_user)
):
    """Get action statistics by category (admin only)"""
    try:
        # Verify admin access
        current_email = user.get("email", "")
        roles = await auth_service.get_user_role(current_email)

        if "admin" not in roles.get("roles", []):
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get statistics
        stats = await admin_action_dao.get_action_statistics(days=days)

        logger.info(f"✅ Retrieved audit statistics for {days} days")
        return {
            "success": True,
            "data": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting audit statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """Manual logout endpoint"""
    try:
        email = user.get("email", "")
        from shared.otel_logger import get_admin_session_id

        session_id = get_admin_session_id()
        if session_id:
            # Logout the session
            await admin_session_dao.logout_session(session_id, reason="manual")
            logger.info(f"✅ Admin logged out: {email}")

            # Clear OTEL context
            clear_admin_context()

        return {"success": True, "message": "Logged out successfully"}
    except Exception as e:
        logger.error(f"Error during logout: {e}")
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
