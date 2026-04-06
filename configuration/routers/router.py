"""
Consolidated Configuration Router
All configuration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Optional
import json
import asyncio

from shared.otel_logger import get_otel_logger, clear_admin_context
from shared.admin_audit import audit_action
from shared.widget_access import issue_widget_access_token, normalize_widget_allowed_origins
from configuration.core.railway_storage import railway_storage
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

def get_session_id_from_context(request: Request, session_id: str) -> str:
    """
    Get the session database ID from request context.

    Internal services work with session database IDs (UUIDs after PG18 migration).
    API Gateway provides session_id in request body/params.

    Args:
        request: FastAPI Request object
        session_id: Session database ID (string)

    Returns:
        Session database ID (str)

    Raises:
        HTTPException: If session ID is invalid
    """
    if isinstance(session_id, str) and session_id:
        return session_id

    logger.error(f"❌ Could not parse session ID: {session_id}")
    raise HTTPException(status_code=400, detail=f"Invalid session ID: {session_id}")

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
    
    # First try request.state (direct API Gateway access)
    if hasattr(request.state, 'user'):
        logger.info(f"🔍 Found user in request.state: {request.state.user}")
        return request.state.user
    
    # Then try headers (proxied from API Gateway)
    if not getattr(request.state, "internal_request_verified", False):
        logger.error("🔍 Rejecting unsigned header-based identity")
        raise HTTPException(status_code=401, detail="Trusted internal identity is required")

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
    """Get complete chatbot configuration — Redis DB7 cache first, PG fallback"""
    import time
    start_time = time.time()

    try:
        from shared.redis_ui_cache import cache_get, cache_set, CHAT_AGENT_CONFIG_KEY, TTL_LONG

        if cache:
            cached = await cache_get(CHAT_AGENT_CONFIG_KEY)
            if cached:
                logger.info(f"[CACHE HIT] GET /chatAgentConfig ({time.time() - start_time:.3f}s)")
                return {"success": True, "data": cached}

        config = await config_service.get_chatAgent_config()

        # Always re-cache (cache=false means skip read, not skip write)
        await cache_set(CHAT_AGENT_CONFIG_KEY, config, TTL_LONG)

        logger.info(f"[DB] GET /chatAgentConfig ({time.time() - start_time:.3f}s)")
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"[ERROR] GET /chatAgentConfig: {e}")
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
        
        # Clear agent cache in chatbot-orchestration service
        # This ensures the next message will use the updated configuration
        try:
            logger.info("🔄 Clearing agent cache in chatbot-orchestration service...")
            import httpx
            import os
            
            chatbot_service_url = os.getenv('CHATBOT_ORCHESTRATION_URL', 'http://localhost:8001')
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{chatbot_service_url}/internal/clear-agent-cache",
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    logger.info("✅ Agent cache cleared successfully")
                else:
                    logger.warning(f"⚠️ Failed to clear agent cache: {response.status_code}")
        except Exception as cache_error:
            logger.warning(f"⚠️ Could not clear agent cache: {cache_error}")
            # Don't fail the request if cache clearing fails
        
        # Invalidate UI cache
        try:
            from shared.redis_ui_cache import cache_invalidate, CHAT_AGENT_CONFIG_KEY
            await cache_invalidate(CHAT_AGENT_CONFIG_KEY)
        except Exception:
            pass

        return {"success": True, "message": "Chatbot configuration saved successfully"}
    except Exception as e:
        logger.error(f"❌ Error saving chatbot config: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving chatbot config: {str(e)}")


# =================================
# WIDGET CONFIGURATION ENDPOINTS
# =================================

@router.get("/widgetConfig")
async def get_widget_config():
    """Get widget configuration — Redis DB7 cache first, PG fallback"""
    try:
        from shared.redis_ui_cache import cache_get, cache_set, WIDGET_CONFIG_KEY, TTL_LONG
        cached = await cache_get(WIDGET_CONFIG_KEY)
        if cached:
            logger.info("[CACHE HIT] GET /widgetConfig")
            return {"success": True, "data": cached}

        config = await config_service.get_widget_config()
        if not config:
            raise HTTPException(status_code=404, detail="Widget configuration not found")

        await cache_set(WIDGET_CONFIG_KEY, config, TTL_LONG)
        logger.info("[DB] GET /widgetConfig")
        return {"success": True, "data": config}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting widget config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch widget configuration: {str(e)}")

@router.post("/widgetConfig")
async def update_widget_config(
    request: Request,
    config: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    chat_icon_image: Optional[UploadFile] = File(None)
):
    """Update widget configuration with optional image uploads"""
    import json
    try:
        # Check if this is multipart/form-data or JSON
        content_type = request.headers.get('content-type', '')

        if 'multipart/form-data' in content_type:
            # Handle multipart form data with images
            if not config:
                raise HTTPException(status_code=400, detail="Config data required in multipart request")

            # Parse JSON config from form
            config_data = json.loads(config)
            logger.info(f"📋 [Router] Parsed config_data keys: {list(config_data.keys())}")
            logger.info(f"📋 [Router] suggested_messages in config: {'suggested_messages' in config_data}, value: {config_data.get('suggested_messages', 'NOT_PRESENT')}")

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

            # Handle image deletion: if URL is null/empty and no new image uploaded, delete from S3
            if not (profile_image and profile_image.filename) and config_data.get('profile_picture_url') in (None, ''):
                old_filenames = await widget_dao.get_image_filenames()
                old_profile = old_filenames.get("profile_picture_filename")
                if old_profile:
                    logger.info(f"🗑️ Deleting old profile image from S3: {old_profile}")
                    await railway_storage.delete_image(old_profile)
                config_data['profile_picture_url'] = None
                config_data['profile_picture_filename'] = None

            if not (chat_icon_image and chat_icon_image.filename) and config_data.get('chat_icon_url') in (None, ''):
                old_filenames = await widget_dao.get_image_filenames()
                old_icon = old_filenames.get("chat_icon_filename")
                if old_icon:
                    logger.info(f"🗑️ Deleting old chat icon from S3: {old_icon}")
                    await railway_storage.delete_image(old_icon)
                config_data['chat_icon_url'] = None
                config_data['chat_icon_filename'] = None

            # Update widget config
            logger.info("📞 [Router] About to call config_service.update_widget_config(config_data) for multipart")
            logger.info(f"📞 [Router] config_data contains suggested_messages: {'suggested_messages' in config_data}")
            await config_service.update_widget_config(config_data)
            # Invalidate widget cache
            try:
                from shared.redis_ui_cache import cache_invalidate, WIDGET_CONFIG_KEY
                await cache_invalidate(WIDGET_CONFIG_KEY)
            except Exception:
                pass
            return {"success": True, "message": "Widget configuration updated successfully with images"}

        else:
            # Handle JSON request (backward compatibility)
            body = await request.json()
            logger.info("=" * 100)
            logger.info("📥 RECEIVED JSON REQUEST FOR WIDGET CONFIG UPDATE")
            logger.info("=" * 100)
            logger.info(f"📋 [Router/JSON] Body keys: {list(body.keys())}")
            logger.info(f"📋 [Router/JSON] suggested_messages in body: {'suggested_messages' in body}")
            if 'suggested_messages' in body:
                logger.info(f"📋 [Router/JSON] suggested_messages value: {body.get('suggested_messages')}")
                logger.info(f"📋 [Router/JSON] suggested_messages type: {type(body.get('suggested_messages')).__name__}")
            logger.info("=" * 100)

            # Handle image deletion for JSON requests too
            from configuration.dao.widget_config_dao import WidgetConfigDAO
            widget_dao = WidgetConfigDAO()

            if body.get('profile_picture_url') in (None, ''):
                old_filenames = await widget_dao.get_image_filenames()
                old_profile = old_filenames.get("profile_picture_filename")
                if old_profile:
                    logger.info(f"🗑️ Deleting old profile image from S3: {old_profile}")
                    await railway_storage.delete_image(old_profile)
                body['profile_picture_url'] = None
                body['profile_picture_filename'] = None

            if body.get('chat_icon_url') in (None, ''):
                old_filenames = await widget_dao.get_image_filenames()
                old_icon = old_filenames.get("chat_icon_filename")
                if old_icon:
                    logger.info(f"🗑️ Deleting old chat icon from S3: {old_icon}")
                    await railway_storage.delete_image(old_icon)
                body['chat_icon_url'] = None
                body['chat_icon_filename'] = None

            logger.info("📞 [Router] About to call config_service.update_widget_config(body)")
            logger.info(f"📞 [Router] Body contains suggested_messages: {'suggested_messages' in body}")
            await config_service.update_widget_config(body)
            # Invalidate widget cache
            try:
                from shared.redis_ui_cache import cache_invalidate, WIDGET_CONFIG_KEY
                await cache_invalidate(WIDGET_CONFIG_KEY)
            except Exception:
                pass
            return {"success": True, "message": "Widget configuration updated successfully"}

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON in config field")
    except ValueError as e:
        logger.error(f"Widget configuration validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating widget config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/widget/embed-script")
async def generate_widget_embed_script(request: Request):
    """Generate widget embed script that dynamically fetches configuration"""
    try:
        body = await request.json()
        embed_type = body.get("embedType", "bubble")
        base_url = body.get("baseUrl", "https://your-widget-url.com").rstrip("/")
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant_slug = getattr(request.state, "tenant_slug", None)

        if not tenant_id:
            raise HTTPException(status_code=400, detail="Active tenant context is required to generate embed code")

        widget_config = await config_service.get_widget_config()
        allowed_origins = normalize_widget_allowed_origins((widget_config or {}).get("allowed_origins"))
        if not allowed_origins:
            raise HTTPException(
                status_code=400,
                detail="Add at least one approved embed origin before generating widget code",
            )

        widget_token = issue_widget_access_token(tenant_id=tenant_id, tenant_slug=tenant_slug)
        iframe_src = f"{base_url}/widget?widgetMode=true&widgetToken={widget_token}"

        if embed_type == "iframe":
            # For iframe, generate a simple embed
            script = f'''<!-- Knowledgebot Widget - Iframe Embed -->
<iframe
    src="{iframe_src}"
    style="width: 100%; height: 600px; border: none; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);"
    title="Chat Widget"
    allow="microphone"
    referrerpolicy="origin"
    allowfullscreen
></iframe>'''
        else:
            script = f'''<!-- Knowledgebot Widget - Secure Bubble Embed -->
<script>
(function() {{
  var iframeUrl = {iframe_src!r};
  var buttonColor = {body.get("primaryColor", "#3b82f6")!r};
  var buttonText = {body.get("displayName", "Chat")!r};
  var iframeId = 'knowledgebot-widget-frame';
  var buttonId = 'knowledgebot-widget-toggle';

  if (document.getElementById(buttonId)) {{
    return;
  }}

  var iframe = document.createElement('iframe');
  iframe.id = iframeId;
  iframe.src = iframeUrl;
  iframe.title = 'Knowledgebot Chat Widget';
  iframe.allow = 'microphone';
  iframe.referrerPolicy = 'origin';
  iframe.style.position = 'fixed';
  iframe.style.right = '24px';
  iframe.style.bottom = '88px';
  iframe.style.width = 'min(420px, calc(100vw - 32px))';
  iframe.style.height = 'min(680px, calc(100vh - 120px))';
  iframe.style.border = '0';
  iframe.style.borderRadius = '18px';
  iframe.style.boxShadow = '0 18px 45px rgba(15, 23, 42, 0.28)';
  iframe.style.background = '#ffffff';
  iframe.style.overflow = 'hidden';
  iframe.style.zIndex = '2147483646';
  iframe.style.display = 'none';

  var button = document.createElement('button');
  button.id = buttonId;
  button.type = 'button';
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', iframeId);
  button.textContent = buttonText;
  button.style.position = 'fixed';
  button.style.right = '24px';
  button.style.bottom = '24px';
  button.style.border = '0';
  button.style.borderRadius = '999px';
  button.style.padding = '14px 18px';
  button.style.font = '600 14px/1.2 -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
  button.style.color = '#ffffff';
  button.style.background = buttonColor;
  button.style.boxShadow = '0 16px 32px rgba(15, 23, 42, 0.24)';
  button.style.cursor = 'pointer';
  button.style.zIndex = '2147483647';

  button.addEventListener('click', function() {{
    var isOpen = iframe.style.display === 'block';
    iframe.style.display = isOpen ? 'none' : 'block';
    button.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
  }});

  document.body.appendChild(iframe);
  document.body.appendChild(button);
}})();
</script>'''

        return {
            "success": True,
            "script": script,
            "embedType": embed_type,
            "widgetToken": widget_token,
            "allowedOrigins": allowed_origins,
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

        # Invalidate widget cache
        try:
            from shared.redis_ui_cache import cache_invalidate, WIDGET_CONFIG_KEY
            await cache_invalidate(WIDGET_CONFIG_KEY)
        except Exception:
            pass

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
        try:
            from shared.redis_ui_cache import cache_invalidate, CHAT_AGENT_CONFIG_KEY
            await cache_invalidate(CHAT_AGENT_CONFIG_KEY)
        except Exception:
            pass
        return {"success": True, "message": "Admin user added successfully"}
    except Exception as e:
        logger.error(f"Error adding admin user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/admins/{user_id}")
async def remove_admin_user(user_id: str, request: Request):
    """Remove an admin user by user ID"""
    try:
        result = await config_service.remove_admin(user_id)
        try:
            from shared.redis_ui_cache import cache_invalidate, CHAT_AGENT_CONFIG_KEY
            await cache_invalidate(CHAT_AGENT_CONFIG_KEY)
        except Exception:
            pass
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
        try:
            from shared.redis_ui_cache import cache_invalidate, CHAT_AGENT_CONFIG_KEY
            await cache_invalidate(CHAT_AGENT_CONFIG_KEY)
        except Exception:
            pass
        return {"success": True, "message": "Human agent added successfully"}
    except Exception as e:
        logger.error(f"Error adding human agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/human-agents/{user_id}")
async def remove_human_agent(user_id: str, request: Request):
    """Remove a human agent by user ID"""
    try:
        result = await config_service.remove_human_agent(user_id)
        try:
            from shared.redis_ui_cache import cache_invalidate, CHAT_AGENT_CONFIG_KEY
            await cache_invalidate(CHAT_AGENT_CONFIG_KEY)
        except Exception:
            pass
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
        # Get session database ID
        session_db_id = get_session_id_from_context(request, session_id)
        logger.info(f"🔍 Delete chat log endpoint: session_id={session_db_id}")

        result = await chat_log_service.delete_chat_log(session_db_id, "admin@example.com")
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
    Uses user IDs instead of emails for Redis channel subscriptions.
    
    Simplified implementation:
    - No in-memory queues
    - No locks required
    - Automatic cleanup
    - Scales horizontally
    """
    try:
        # Get user email and ID from authenticated user (via cookie)
        user_email = user.get("email")
        user_uid = user.get("uid")
        user_role = user.get("role", "human_agent")

        if not user_email or not user_uid:
            logger.error(f"No user email or UID in SSE request. User dict: {user}")
            raise HTTPException(status_code=401, detail="Authentication required. Please sign in.")

        # Fetch user ID from database using email
        from ..dao.chat_log_dao import ChatLogDAO
        dao = ChatLogDAO()
        user_id = await dao.get_user_id_by_email(user_email)
        
        if not user_id:
            logger.error(f"Could not find user ID for email {user_email}")
            raise HTTPException(status_code=401, detail="User not found in database")

        logger.info(f"🔌 Agent {user_email} (ID: {user_id}, role={user_role}) connecting to Redis Pub/Sub SSE stream")

        # Create Redis Pub/Sub subscriber for this agent (using user ID)
        subscriber = AgentEventSubscriber(user_id, user_email, user_role)

        async def event_generator():
            """
            Generator that yields SSE events from Redis Pub/Sub with heartbeat.
            Heartbeat (every 15s) keeps connection alive to prevent CDN/gateway timeouts.
            Includes inactivity timeout (5 minutes) to clean up stale connections.
            Also maintains agent online presence in Redis.
            """
            import asyncio
            import time

            heartbeat_task = None
            redis_task = None
            presence_task = None
            last_activity = time.time()
            channel_name = f"agent:events:{user_id}"

            try:
                # Set initial presence key in Redis
                from shared.redis_pubsub_manager import get_pubsub_redis
                redis_client = await get_pubsub_redis()
                presence_key = f"agent:online:{user_id}"
                await redis_client.set(presence_key, "1", ex=60)  # 60 second TTL
                logger.info(f"✅ Set online presence for agent {user_email} (ID: {user_id})")

                async def presence_loop():
                    """Refresh agent presence key every 30 seconds"""
                    try:
                        while True:
                            await asyncio.sleep(30)
                            try:
                                await redis_client.set(presence_key, "1", ex=60)
                                logger.debug(f"🔄 Refreshed online presence for agent {user_email} (ID: {user_id})")
                            except Exception as e:
                                logger.warning(f"Failed to refresh presence: {e}")
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Presence loop error: {e}")

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
                presence_task = asyncio.create_task(presence_loop())

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
                yield f"data: {json.dumps({'type': 'connected', 'agent_email': user_email, 'agent_id': user_id, 'role': user_role, 'timestamp': int(time.time())})}\n\n"

                # Yield messages from queue
                try:
                    while True:
                        try:
                            # Check for inactivity timeout (5 minutes)
                            current_time = time.time()
                            if current_time - last_activity > 300:
                                logger.info(f"⏱️ Connection timeout for {user_email} (ID: {user_id}) on channel {channel_name} - no activity for 5 minutes")
                                break

                            msg = await asyncio.wait_for(message_queue.get(), timeout=30)
                            if msg.get("type") == "heartbeat":
                                # SSE comment (: prefix) doesn't trigger client event
                                yield f": keep-alive {msg['timestamp']}\n\n"
                            else:
                                # Real event data - update last_activity
                                last_activity = time.time()
                                logger.info(f"🔌 [SSE] Yielding message to {user_email} (ID: {user_id}): {msg.get('type')} for session {msg.get('session_id', 'N/A')}")
                                yield f"data: {json.dumps(msg)}\n\n"

                                # Check if session ended - close connection immediately
                                if msg.get("type") == "session_ended":
                                    logger.info(f"🛑 Session ended event received for {user_email} (ID: {user_id}) on channel {channel_name} - closing connection")
                                    break
                        except asyncio.TimeoutError:
                            # Queue empty for 30s, send heartbeat manually
                            yield f": timeout-heartbeat {int(time.time())}\n\n"
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Invalid JSON in message: {e}")
                            # Continue listening, don't break
                            continue
                        except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                            # Client disconnected - expected and normal
                            logger.debug(f"🔌 Client {user_email} (ID: {user_id}) disconnected (yield error on channel {channel_name}): {type(e).__name__}")
                            break
                        except Exception as e:
                            # Check if it's a client disconnection error
                            error_msg = str(e)
                            if "peer closed connection" in error_msg.lower() or "incomplete chunked read" in error_msg.lower():
                                logger.debug(f"🔌 Client {user_email} (ID: {user_id}) disconnected (yield error on channel {channel_name}): {e}")
                            else:
                                logger.error(f"❌ Error yielding message to {user_email} (ID: {user_id}): {e}")
                            break

                except asyncio.CancelledError:
                    logger.debug(f"🔌 SSE connection cancelled for {user_email} (ID: {user_id})")
                except Exception as e:
                    error_msg = str(e)
                    if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                        logger.error(f"❌ Error in SSE generator for {user_email} (ID: {user_id}): {e}")
                    else:
                        logger.debug(f"🔌 Client disconnection in SSE generator for {user_email} (ID: {user_id}): {e}")

            except asyncio.CancelledError:
                logger.debug(f"🔌 SSE connection cancelled for {user_email}")
            except Exception as e:
                error_msg = str(e)
                if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                    logger.error(f"❌ Error in SSE generator for {user_email}: {e}")
                else:
                    logger.debug(f"🔌 Client disconnection in SSE generator for {user_email}: {e}")
            finally:
                # Cancel tasks and wait for cleanup
                if heartbeat_task and not heartbeat_task.done():
                    heartbeat_task.cancel()
                if redis_task and not redis_task.done():
                    redis_task.cancel()
                if presence_task and not presence_task.done():
                    presence_task.cancel()

                # Give tasks a moment to clean up
                try:
                    await asyncio.gather(
                        heartbeat_task if heartbeat_task and not heartbeat_task.done() else asyncio.sleep(0),
                        redis_task if redis_task and not redis_task.done() else asyncio.sleep(0),
                        presence_task if presence_task and not presence_task.done() else asyncio.sleep(0),
                        return_exceptions=True
                    )
                except Exception:
                    pass

                # Remove presence key when disconnecting
                try:
                    await redis_client.delete(presence_key)
                    logger.info(f"🗑️ Removed online presence for agent {user_email}")
                except Exception as e:
                    logger.warning(f"Failed to remove presence key: {e}")

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

        # Session IDs are always UUIDs now
        session_id = str(session_id)

        logger.info(f"✅ Found session ID: {session_id}")

        # Create response and set httpOnly cookie
        response = JSONResponse({
            "success": True,
            "session_id": session_id,
            "message": f"Customer session set as current"
        })

        # Set httpOnly, Secure, SameSite cookie with the session ID
        response.set_cookie(
            key="chatbot_session_id",
            value=session_id,
            httponly=True,
            secure=True,
            samesite="Strict",
            max_age=60 * 60 * 24  # 24 hours
        )

        logger.info(f"🍪 Set chatbot_session_id cookie for customer session {session_id}")
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
                        except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                            # Client disconnected - expected and normal
                            logger.debug(f"🔌 Client on session {session_id} disconnected (yield error on channel {channel_name}): {type(e).__name__}")
                            break
                        except Exception as e:
                            # Check if it's a client disconnection error
                            error_msg = str(e)
                            if "peer closed connection" in error_msg.lower() or "incomplete chunked read" in error_msg.lower():
                                logger.debug(f"🔌 Client on session {session_id} disconnected (yield error on channel {channel_name}): {e}")
                            else:
                                logger.error(f"❌ Error yielding message to session {session_id}: {e}")
                            break

                except asyncio.CancelledError:
                    logger.debug(f"🔌 SSE connection cancelled for session {session_id}")
                except Exception as e:
                    error_msg = str(e)
                    if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                        logger.error(f"❌ Error in SSE generator for session {session_id}: {e}")
                    else:
                        logger.debug(f"🔌 Client disconnection in SSE generator for session {session_id}: {e}")

            except asyncio.CancelledError:
                logger.debug(f"🔌 SSE connection cancelled for session {session_id}")
            except Exception as e:
                error_msg = str(e)
                if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                    logger.error(f"❌ Error in SSE generator for session {session_id}: {e}")
                else:
                    logger.debug(f"🔌 Client disconnection in SSE generator for session {session_id}: {e}")
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

@router.get("/admin/chat-sessions/stream")
async def stream_admin_chat_sessions(
    request: Request,
    status: str = "all",
    limit: int = 50,
    cursor: str = None,
    role: str = "admin",
    agent_id: str = None,
):
    """
    SSE endpoint that streams chat sessions one-by-one from PG18.
    Uses server-side cursor + LATERAL join for progressive rendering.
    Supports cursor-based infinite scroll.

    SSE event format:
      event: count\ndata: {"total_count": 150}\n\n
      event: session\ndata: {session JSON}\n\n
      event: done\ndata: {"loaded": 50, "has_more": true, "next_cursor": "2025-03-20T..."}\n\n

    Query params:
      status: "all"|"active"|"closed"
      limit: sessions per page (default 50)
      cursor: ISO timestamp of last session's last_activity_at (for infinite scroll)
      role: "admin"|"human_agent"
      agent_id: optional agent filter
    """
    try:
        user_email = getattr(request.state, "user_email", None) or request.headers.get("X-User-Email", "")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found in request")

        logger.info(f"🔌 [SSE-STREAM] Chat sessions stream requested: status={status}, limit={limit}, cursor={cursor}")

        async def event_generator():
            try:
                loaded = 0
                last_cursor = None

                async for session_dict in chat_log_service.stream_chat_sessions(
                    role=role,
                    user_email=user_email,
                    archive_status=status,
                    limit=limit,
                    cursor=cursor,
                    agent_id=agent_id
                ):
                    loaded += 1
                    last_cursor = session_dict.get('last_message_at')
                    yield f"event: session\ndata: {json.dumps(session_dict, default=str)}\n\n"

                # has_more: if we got exactly `limit` rows, there are likely more
                has_more = (loaded == limit)
                yield f"event: done\ndata: {json.dumps({'loaded': loaded, 'has_more': has_more, 'next_cursor': last_cursor})}\n\n"

                logger.info(f"✅ [SSE-STREAM] Streamed {loaded} sessions, has_more={has_more}")

            except (BrokenPipeError, ConnectionResetError) as e:
                logger.debug(f"🔌 [SSE-STREAM] Client disconnected: {type(e).__name__}")
            except Exception as e:
                logger.error(f"❌ [SSE-STREAM] Error in event generator: {e}")
                import traceback
                logger.error(f"❌ [SSE-STREAM] Traceback: {traceback.format_exc()}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        logger.error(f"❌ [SSE-STREAM] Error setting up stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer/sessions/messages")
async def send_customer_message(request: Request):
    """Send a message from a customer to an assigned agent (no AI processing)

    Request body: {
        session_id: str (session database ID),
        text: str (message text)
    }

    This endpoint uses the session database ID for all DB operations and looks up
    the UUID only for Redis channel broadcasting.
    """
    try:
        body = await request.json()
        text = body.get("text", "")
        session_id_raw = body.get("session_id", "")

        logger.info(f"📨 Customer message request - session_id: {session_id_raw} (type: {type(session_id_raw).__name__})")

        if not text:
            raise HTTPException(status_code=400, detail="Message text is required")

        if not session_id_raw:
            raise HTTPException(status_code=400, detail="session_id is required")

        session_id = str(session_id_raw)

        # Check if agent is assigned (Redis DB4 cache + DB fallback via service)
        assigned_agent_id = await chat_log_service.get_assigned_agent_id_cached(session_id)

        if not assigned_agent_id:
            raise HTTPException(status_code=400, detail="No agent assigned to this session. Use chatbot API instead.")

        # Save customer message to database
        message_id = await chat_log_service.send_customer_message(session_id, text)

        # Prepare event data - use session_id for Redis channel matching
        import datetime
        event_data = {
            "type": "customer_message",
            "session_id": session_id,
            "message_id": str(message_id),
            "text": text,
            "sender": "customer",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        logger.info(f"📨 Broadcasting customer message for session: {session_id}")

        from shared.redis_pubsub_manager import broadcast_event_to_agent, broadcast_event_to_all_agents, broadcast_event_to_session

        # Check if assigned agent is admin (via service with Redis cache)
        admin_ids = await chat_log_service.get_admin_ids_cached()
        is_assigned_admin = assigned_agent_id in admin_ids

        # Always broadcast to session channel so customer can see their own message
        await broadcast_event_to_session(session_id, event_data)
        logger.info(f"📤 Customer message broadcasted to session channel {session_id}")

        if is_assigned_admin:
            # Always broadcast to all agents - UI will handle deduplication for admin users
            await broadcast_event_to_all_agents(event_data)
        else:
            # Always broadcast to both channels - UI will handle any potential duplicates
            await broadcast_event_to_agent(assigned_agent_id, event_data)
            await broadcast_event_to_all_agents(event_data)
        logger.info(f"📤 Sent customer message notification for session {session_id}")

        return {
            "success": True,
            "message_id": str(message_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending customer message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/chat-sessions/{session_id}/messages")
async def get_session_messages(session_id: str, request: Request):
    """
    Load the full conversation for a session (page load/reload).

    Returns *all* roles present in `chat_messages` (customer/user, bot/assistant, agent/human),
    ordered oldest -> newest.
    """
    try:
        # Ensure caller is authenticated (API gateway injects this header).
        header_email = request.headers.get("X-User-Email", "")
        if not header_email:
            raise HTTPException(status_code=401, detail="User identity not found. X-User-Email header is required.")

        messages = await chat_log_service.get_session_messages(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "messages": messages,
            "total_messages": len(messages),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading session messages for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load chat messages")

@router.post("/admin/chat-sessions/messages")
async def send_agent_message(request: Request):
    """Send a message from an agent or customer in a chat session

    Request body: {
        session_id: str (session database ID),
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

        session_db_id = str(session_id)

        text = body.get("text", "")
        sender_type = body.get("sender", "agent")  # "agent" or "user" (customer)

        if not text:
            raise HTTPException(status_code=400, detail="Message text is required")

        # Resolve sender identity from trusted X-User-Email header (set by API Gateway from JWT)
        # Never trust agent_id from frontend body for authorization
        header_email = request.headers.get("X-User-Email", "")
        if not header_email:
            raise HTTPException(status_code=401, detail="User identity not found. X-User-Email header is required.")
        sender_id_int = await chat_log_service.get_user_id_by_email_cached(header_email)
        sender_email = header_email

        if sender_id_int is None:
            raise HTTPException(status_code=400, detail="Could not resolve user identity from authenticated email.")

        logger.info(f"🔍 POST /admin/chat-sessions/messages called for session {session_id}, sender: {sender_email} (ID: {sender_id_int})")

        # Authorization check BEFORE saving — all lookups are Redis-cached
        if sender_type == "agent":
            # Get assigned agent ID via service (Redis cache + DB fallback)
            assigned_agent_id = await chat_log_service.get_assigned_agent_id_cached(session_id)

            # Compare numeric IDs for authorization
            if sender_id_int != assigned_agent_id:
                # Fetch admin IDs via service (Redis cache + DB fallback)
                admin_ids = await chat_log_service.get_admin_ids_cached()
                is_sender_admin = sender_id_int in admin_ids
                if is_sender_admin:
                    logger.warning(f"⚠️ Admin ID {sender_id_int} attempted to reply to session {session_id} assigned to agent ID {assigned_agent_id}")
                    raise HTTPException(status_code=403, detail="Only the assigned agent can reply to this chat. You can view messages as read-only.")
                else:
                    logger.warning(f"⚠️ User ID {sender_id_int} attempted to send message to session {session_id} assigned to agent ID {assigned_agent_id}")
                    raise HTTPException(status_code=403, detail="Only the assigned agent can send messages to this chat")

            logger.info(f"✅ Authorization check passed: ID {sender_id_int} is assigned to session {session_id}")

        # Save message to database (only after auth passes)
        message_id = await chat_log_service.send_agent_message(session_id, sender_email, text)

        # Prepare event data
        import datetime
        event_data = {
            "type": "agent_message",
            "session_id": session_id,
            "message_id": str(message_id),
            "text": text,
            "sender": sender_type,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        # Smart broadcasting based on sender
        from shared.redis_pubsub_manager import broadcast_event_to_session, broadcast_event_to_agent, broadcast_event_to_all_agents

        if sender_type == "agent":
            event_data["agent_id"] = sender_id_int
            event_data["agent_email"] = sender_email

            # Fetch admin IDs for broadcast logic (reuse if already fetched above)
            admin_ids = await chat_log_service.get_admin_ids_cached()

            # Broadcast to customer
            await broadcast_event_to_session(session_id, event_data)
            logger.info(f"📤 [AGENT_MESSAGE] Broadcasted to customer on session: {session_id}")

            # Smart agent broadcasting
            is_sender_admin = sender_id_int in admin_ids
            if is_sender_admin:
                await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 Agent (admin ID {sender_id_int}) message sent to customer and all admins")
            else:
                await broadcast_event_to_agent(sender_id_int, event_data)
                await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 Agent ID {sender_id_int} message sent to customer, agent, and all admins")

        elif sender_type == "user":
            # Customer sent message → Notify assigned agent AND all admins
            assigned_agent_id = await chat_log_service.get_assigned_agent_id_cached(session_id)

            if assigned_agent_id:
                admin_ids = await chat_log_service.get_admin_ids_cached()
                is_assigned_admin = assigned_agent_id in admin_ids

                if is_assigned_admin:
                    # Always broadcast to all agents - UI will handle deduplication for admin users
                    await broadcast_event_to_all_agents(event_data)
                    logger.info(f"📤 Customer message sent via broadcast (assigned agent ID {assigned_agent_id} is admin - UI will deduplicate)")
                else:
                    # Always broadcast to both channels - UI will handle any potential duplicates
                    await broadcast_event_to_agent(assigned_agent_id, event_data)
                    await broadcast_event_to_all_agents(event_data)
                    logger.info(f"📤 Customer message sent to human agent ID {assigned_agent_id} and all admins")
            else:
                await broadcast_event_to_all_agents(event_data)
                logger.info(f"📤 Customer message sent to admins (no agent assigned)")

        return {
            "success": True,
            "message_id": str(message_id),
            "session_id": str(session_db_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/end-agent")
async def end_agent_session(request: Request):
    """End chat session from the agent side

    Request body: {session_id: str (numeric ID or UUID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        user_email = request.headers.get("X-User-Email", "agent@example.com")

        logger.info(f"🔍 End-agent endpoint: session_id={session_id}")

        # Get user ID for broadcasting (via service with Redis cache)
        user_id = await chat_log_service.get_user_id_by_email_cached(user_email)
        if not user_id:
            logger.error(f"❌ Could not get user ID for agent {user_email}")
            raise HTTPException(status_code=400, detail=f"Invalid agent email: {user_email}")

        await chat_log_service.update_chat_session(
            session_id=session_id,
            user_email=user_email,
            status="closed"
        )

        # Broadcast session_ended event with feedback prompt to customer
        # This ensures customer receives notification and can provide feedback
        from shared.redis_pubsub_manager import broadcast_event_to_session, broadcast_event_to_agent, broadcast_event_to_all_agents
        import datetime

        event_data = {
            "type": "session_ended",
            "session_id": session_id,      # Use UUID for SSE channel matching
            "ended_by": "agent",
            "agent_email": user_email,
            "show_feedback": True,  # Trigger feedback UI for customer
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        logger.info(f"📤 [END_AGENT] Broadcasting session_ended event: session_id={session_id}, agent={user_email}")
        result = await broadcast_event_to_session(session_id, event_data)
        logger.info(f"📤 [END_AGENT] Broadcast result: {result}")

        # Also notify the agent's own SSE stream and all admins
        if user_id:
            await broadcast_event_to_agent(user_id, event_data)
        await broadcast_event_to_all_agents(event_data)

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

@router.post("/admin/chat-sessions/end-customer")
async def end_customer_session(request: Request):
    """End a chat session from the customer side

    API Gateway extracts session UUID from httpOnly cookie and injects both:
    - session_id (numeric) for internal service operations
    - session_uuid (UUID) for broadcasting to customer SSE channels

    Accepts session_id from multiple sources (in priority order):
    1. Request body (explicit passing)
    2. request.state.session_id (injected by API Gateway middleware)
    3. request.state.session_uuid (resolve to numeric if needed)
    """
    try:
        body = await request.json()
        session_id = body.get("session_id") or getattr(request.state, 'session_id', None)

        if not session_id:
            # No session to end — return success silently (bubble close without active session)
            return {"success": True, "message": "No active session"}

        user_email = request.headers.get("X-User-Email", "customer@example.com")
        await chat_log_service.end_customer_session(session_id, user_email)

        # Broadcast session_ended event with feedback prompt to customer
        from shared.redis_pubsub_manager import broadcast_event_to_session, broadcast_event_to_agent, broadcast_event_to_all_agents
        import datetime

        event_data = {
            "type": "session_ended",
            "session_id": session_id,
            "ended_by": "customer",
            "show_feedback": True,  # Trigger feedback UI
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        # Broadcast to customer SSE channel using session_id
        await broadcast_event_to_session(session_id, event_data)

        # Notify the assigned agent and all admins (via service with Redis cache)
        assigned_agent_id = await chat_log_service.get_assigned_agent_id_cached(session_id)
        if assigned_agent_id:
            await broadcast_event_to_agent(assigned_agent_id, event_data)
        await broadcast_event_to_all_agents(event_data)

        return {
            "success": True,
            "message": "Session ended by customer"
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
        session_id: str (session database ID, injected by API Gateway)
        session_uuid: str (UUID, injected by API Gateway)
        feedback_type: str ('positive' or 'negative')
    """
    try:
        body = await request.json()
        session_id = body.get("session_id") or getattr(request.state, 'session_id', None)
        feedback_type = body.get("feedback_type")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        if not feedback_type:
            raise HTTPException(status_code=400, detail="feedback_type is required")

        if feedback_type not in ['positive', 'negative']:
            raise HTTPException(status_code=400, detail="feedback_type must be 'positive' or 'negative'")

        logger.info(f"🔍 Feedback endpoint: session_id={session_id}, feedback={feedback_type}")

        # Update feedback in database
        success = await chat_log_service.update_session_feedback(session_id, feedback_type)

        if not success:
            raise HTTPException(status_code=404, detail="Session not found")

        logger.info(f"✅ Customer feedback '{feedback_type}' submitted for session {session_id}")

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

    Session numeric ID comes from multiple sources:
    1. Request body (session_id parameter)
    2. request.state.session_id (injected by API Gateway from cookie)

    Can be called from:
    - Browser (via API Gateway which extracts UUID from cookie and converts to numeric ID)
    - Internal services (pass numeric session_id in request body)

    Returns:
    - agent_assigned: Agent email (for display)
    - agent_id: Agent user ID (for Redis channel subscription)
    """
    try:
        logger.info(f"🧑 [ENDPOINT] POST /admin/chat-sessions/request-agent called")

        body = await request.json()
        session_id = body.get("session_id") or getattr(request.state, 'session_id', None)

        if not session_id:
            raise HTTPException(
                status_code=400,
                detail="session_id is required"
            )

        logger.info(f"🧑 [ENDPOINT] Session ID: {session_id}")

        # Pass session ID to service
        logger.info(f"🔍 [ENDPOINT] Calling chat_log_service.request_human_agent with session_id={session_id}")
        assignment_result = await chat_log_service.request_human_agent(session_id)
        logger.info(f"✅ [ENDPOINT] Agent assigned: {assignment_result}")

        response = {
            "success": True,
            "message": "Human agent assigned",
            "agent_assigned": assignment_result['email'],
            "agent_id": assignment_result['id'],
            "session_id": session_id
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

    Request params: session_id (session database ID as query parameter)
    """
    try:
        session_id = request.query_params.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id query parameter is required")

        user_email = request.headers.get("X-User-Email", "admin@example.com")

        logger.info(f"🔍 Delete endpoint: session_id={session_id}")

        # Delete all messages for the session first
        await chat_log_service.delete_session_messages(session_id)

        # Delete the session itself
        await chat_log_service.delete_chat_session(session_id)

        logger.info(f"Deleted chat session {session_id} by {user_email}")

        return {
            "success": True,
            "message": "Chat session deleted successfully",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/mark-read")
async def mark_session_as_read(request: Request, user: dict = Depends(get_current_user)):
    """Mark session as read

    Request body: {session_id: str (session database ID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")

        logger.info(f"🔍 Mark-read endpoint: session_id={session_id}, user={user_email}")
        await chat_log_service.mark_session_as_read(session_id, user_email)

        return {
            "success": True,
            "message": "Session marked as read",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking session as read: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/chat-sessions/mark-unread")
async def mark_session_as_unread(request: Request, user: dict = Depends(get_current_user)):
    """Mark session as unread

    Request body: {session_id: str (session database ID)}
    """
    try:
        body = await request.json()
        session_id = body.get("session_id")

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required in request body")

        user_email = user.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")

        logger.info(f"🔍 Mark-unread endpoint: session_id={session_id}, user={user_email}")
        await chat_log_service.mark_session_as_unread(session_id, user_email)

        return {
            "success": True,
            "message": "Session marked as unread",
            "session_id": session_id
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
async def get_unread_message_count(request: Request, session_id: str = Query(...)):
    """Get unread message count for a session

    Args:
        session_id: Session database ID (required query parameter)
    """
    try:
        user_email = request.headers.get("X-User-Email", "admin@example.com")

        logger.info(f"🔍 Unread-count endpoint: session_id={session_id}")

        count = await chat_log_service.get_unread_message_count(session_id)

        logger.info(f"Retrieved unread message count for session {session_id} by {user_email}")

        return {
            "success": True,
            "session_id": session_id,
            "unread_count": count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting unread message count: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/unique-id")
async def create_or_get_unique_id(request: Request):
    """Create or get unique user ID by role. Email from X-User-Email header (set by API Gateway)."""
    try:
        body = await request.json()
        role = body.get("role", "customer")
        email = request.headers.get("X-User-Email")

        if not email:
            raise HTTPException(status_code=401, detail="User email not provided. Authentication required.")

        result = await auth_service.get_or_create_unique_id(email, role)
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating/getting unique ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/unique-id")
async def get_user_unique_id(request: Request, role: str = "customer"):
    """Get unique ID for a user by role. Email from X-User-Email header (set by API Gateway)."""
    try:
        email = request.headers.get("X-User-Email")

        if not email:
            raise HTTPException(status_code=401, detail="User email not provided. Authentication required.")

        result = await auth_service.get_or_create_unique_id(email, role)
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user unique ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PERFORMANCE ENDPOINTS
# =================================

@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get performance metrics — Redis DB7 cache first (5min TTL), PG fallback"""
    try:
        from shared.redis_ui_cache import cache_get, cache_set, PERFORMANCE_METRICS_KEY, TTL_SHORT
        cached = await cache_get(PERFORMANCE_METRICS_KEY)
        if cached:
            logger.info("[CACHE HIT] GET /performance/metrics")
            return {"success": True, "data": cached}

        metrics = await performance_service.get_performance_metrics()
        await cache_set(PERFORMANCE_METRICS_KEY, metrics, TTL_SHORT)
        return {"success": True, "data": metrics}
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/token-usage/detailed")
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None):
    """Get detailed token usage — Redis DB7 cache first (5min TTL), PG fallback"""
    try:
        from shared.redis_ui_cache import cache_get, cache_set, TOKEN_USAGE_KEY_PREFIX, TTL_SHORT
        cache_key = f"{TOKEN_USAGE_KEY_PREFIX}{limit}:{provider}:{api_call_type}"
        cached = await cache_get(cache_key)
        if cached:
            return {"success": True, "data": cached}

        usage = await token_usage_service.get_detailed_token_usage(limit, provider, api_call_type)
        await cache_set(cache_key, usage, TTL_SHORT)
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
async def get_user_profile(request: Request, user: dict = Depends(get_current_user)):
    """Get user profile information"""
    import time
    start_time = time.time()
    logger.info("[ENTRY] GET /users/profile endpoint")
    logger.info(f"[PARAM] user_email={user.get('email')}")
    
    try:
        # Get user's actual role from database
        user_email = user.get("email")
        logger.info(f"[FLOW] Extracting user email: {user_email}")
        
        if not user_email:
            logger.error(f"[ERROR] No user email found in user data: {user}")
            raise HTTPException(status_code=400, detail="User email not found")
        
        logger.info("[FLOW] Calling auth_service.get_user_role()")
        # Don't catch exceptions - let them propagate so the endpoint returns 503
        # If database is unavailable, client should know immediately, not get fake data
        requested_tenant_id = getattr(request.state, "tenant_id", None)
        requested_tenant_slug = getattr(request.state, "tenant_slug", None)
        role_result = await auth_service.get_user_role(
            user_email,
            tenant_id=requested_tenant_id,
            tenant_slug=requested_tenant_slug,
        )
        logger.info(f"[RESULT] Role result retrieved: {role_result}")

        user_roles = role_result.get("roles", ["user"])
        logger.info(f"[RESULT] User roles: {user_roles}")
        active_tenant = role_result.get("active_tenant")
        tenant_memberships = role_result.get("tenant_memberships", [])
        active_user_role_id = role_result.get("active_user_role_id")
        
        # If user has no roles, they might not be in user_role_mapping table
        # This is OK - they're a regular user
        if not user_roles or user_roles == ["user"]:
            logger.info(f"[INFO] User {user_email} has no special roles, defaulting to 'user' role")
        
        # Determine primary role (admin > human_agent > user)
        logger.info("[TRANSFORM] Determining primary role")
        primary_role = role_result.get("primary_role") or (
            "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        )
        logger.info(f"[RESULT] Primary role determined: {primary_role}")
        
        # Get numeric user ID from database (used for authorization, not display)
        user_numeric_id = await chat_log_service.get_user_id_by_email_cached(user_email)

        # Return authenticated user profile with actual role
        logger.info("[TRANSFORM] Building user profile object")
        profile = {
            "id": user_numeric_id,  # Numeric DB ID for authorization comparisons
            "email": user.get("email"),
            "uid": user.get("uid"),
            "display_name": user.get("name") or user.get("email"),  # Frontend expects display_name
            "photo_url": user.get("picture"),  # Frontend expects photo_url
            "role": primary_role,
            "roles": user_roles,  # Include all roles for frontend
            "active_user_role_id": active_user_role_id,
            "tenant_id": active_tenant.get("tenant_id") if active_tenant else None,
            "tenant_slug": active_tenant.get("tenant_slug") if active_tenant else None,
            "tenant_name": active_tenant.get("tenant_name") if active_tenant else None,
            "tenant_memberships": tenant_memberships,
            "preferences": {
                "theme": "light",
                "notifications": True
            }
        }
        logger.info(f"[RESULT] User profile created successfully for {user_email} with role {primary_role}")
        
        elapsed_time = time.time() - start_time
        logger.info(f"[EXIT] GET /users/profile - Success (elapsed: {elapsed_time:.3f}s)")
        logger.info(f"[RETURN] Profile: email={profile['email']}, role={profile['role']}")
        
        return {"success": True, "data": profile}
    except HTTPException:
        elapsed_time = time.time() - start_time
        logger.error(f"[EXIT] GET /users/profile - HTTPException (elapsed: {elapsed_time:.3f}s)")
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[EXIT] GET /users/profile - Error (elapsed: {elapsed_time:.3f}s)")
        logger.error(f"[ERROR] Exception type: {type(e).__name__}, Message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
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
# PERFORMANCE METRICS ENDPOINTS
# =================================

@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get performance metrics for dashboard"""
    try:
        performance_service = PerformanceService()
        metrics = await performance_service.get_performance_metrics()
        logger.info("✅ Successfully retrieved performance metrics")
        return {
            "success": True,
            "data": metrics
        }
    except Exception as e:
        logger.error(f"❌ Error fetching performance metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch performance metrics: {str(e)}")


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
