"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, Response, JSONResponse
import logging
from typing import Dict, Any
from httpx import AsyncClient

from ..core.firebase_auth import verify_firebase_token, get_user_from_firestore
from ..core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# =================================
# DOMAIN VALIDATION HELPER FUNCTIONS
# =================================

async def is_authorized_domain(referer: str = None, origin: str = None) -> bool:
    """Check if the request is from an authorized domain"""
    try:
        # For now, allow all domains (authorized domains logic not implemented yet)
        # TODO: Implement proper domain validation when authorized domains feature is ready
        return True
        
    except Exception as e:
        logger.error(f"Error in domain validation: {e}")
        return True  # Fail open for now

# =================================
# FIREBASE AUTHENTICATION ENDPOINTS
# =================================

@router.post("/auth/verify")
async def verify_auth_token(request: Request):
    """Verify Firebase authentication token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(status_code=500, detail=f"Error verifying token: {str(e)}")

@router.get("/auth/user/{uid}")
async def get_user_by_uid(uid: str):
    """Get user information by Firebase UID."""
    try:
        user_data = get_user_from_firestore(uid)
        return {
            "success": True,
            "user": user_data
        }
    except Exception as e:
        logger.error(f"Error getting user by UID {uid}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")

@router.post("/auth/login")
async def login_user(request: Request):
    """Login user with Firebase token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data,
            "message": "Login successful"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")

# =================================
# PUBLIC CHAT ENDPOINTS (No Authentication Required)
# =================================

@router.post("/chatbot/chat/stream")
async def public_chat_stream(request: Request):
    """Public chat streaming endpoint - no authentication required for website visitors"""
    try:
        import httpx
        from ..core.config import get_settings
        
        # Get session ID from request to check if this is the first message in the session
        body = await request.json()
        session_id = body.get("session_id")
        
        # Only check chat enabled status on first message of each session
        if session_id and not hasattr(request.state, 'chat_status_checked'):
            config_service_url = "http://configuration.railway.internal:8080"  # Internal service URL
            
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{config_service_url}/api/v1/configuration/widgetConfig",
                        timeout=5.0
                    )
                    
                    if response.status_code == 200:
                        config = response.json()
                        chat_enabled = config.get("display_chatbot", True)
                        
                        # Store the result in request state for subsequent requests
                        request.state.chat_status_checked = True
                        request.state.chat_enabled = chat_enabled
                        
                        if not chat_enabled:
                            logger.info("Chat is disabled - blocking request")
                            raise HTTPException(status_code=403, detail="Chat is currently disabled")
                        else:
                            logger.info(f"Chat is enabled for session {session_id}")
                            
            except Exception as e:
                logger.error(f"Error checking chat enabled status: {e}")
                # If we can't check the status, allow the request (fail open)
                request.state.chat_status_checked = True
                request.state.chat_enabled = True
        
        # If we haven't checked the status yet (no session_id or first request), check now
        elif not hasattr(request.state, 'chat_status_checked'):
            config_service_url = "http://configuration.railway.internal:8080"  # Internal service URL
            
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{config_service_url}/api/v1/configuration/widgetConfig",
                        timeout=5.0
                    )
                    
                    if response.status_code == 200:
                        config = response.json()
                        chat_enabled = config.get("display_chatbot", True)
                        request.state.chat_status_checked = True
                        request.state.chat_enabled = chat_enabled
                        
                        if not chat_enabled:
                            logger.info("Chat is disabled - blocking request")
                            raise HTTPException(status_code=403, detail="Chat is currently disabled")
                            
            except Exception as e:
                logger.error(f"Error checking chat enabled status: {e}")
                # If we can't check the status, allow the request (fail open)
                request.state.chat_status_checked = True
                request.state.chat_enabled = True
        
        # Check cached status if available
        elif hasattr(request.state, 'chat_enabled') and not request.state.chat_enabled:
            logger.info("Chat is disabled (cached) - blocking request")
            raise HTTPException(status_code=403, detail="Chat is currently disabled")
        
        # Validate referer domain for security
        referer = request.headers.get("referer")
        origin = request.headers.get("origin")
        
        # Check if the request is from an authorized domain
        if not await is_authorized_domain(referer, origin):
            logger.warning(f"Unauthorized widget access attempt - Referer: {referer}, Origin: {origin}")
            raise HTTPException(status_code=403, detail="Widget embedding not authorized for this domain")
        
        settings = get_settings()
        chatbot_service_url = settings.chatbot_orchestration_url
        
        # Log the request
        correlation_id = request.headers.get("X-Correlation-ID", "no-correlation-id")
        logger.info(f"🔍 [{correlation_id}] Public chat stream request received from authorized domain")
        
        # Prepare headers - remove auth-related headers for public endpoint
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("authorization", None)
        
        # Make request to chatbot service
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=f"{chatbot_service_url}/api/v1/chatbot/chat/stream",
                headers=headers,
                content=await request.body(),
                params=request.query_params
            )
            
            logger.info(f"✅ [{correlation_id}] Chat stream response: {response.status_code}")
            
            # Return streaming response
            from fastapi.responses import StreamingResponse
            
            async def stream_response():
                async for chunk in response.aiter_bytes():
                    yield chunk
            
            return StreamingResponse(
                stream_response(),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public chat stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# PUBLIC WIDGET ENDPOINT (No Authentication Required)
# =================================

@router.get("/widget")
async def public_widget(request: Request):
    """Public widget endpoint - serves HTML page with chat widget for iframe embedding"""
    try:
        # Get query parameters
        widget_mode = request.query_params.get("widgetMode", "true")
        theme = request.query_params.get("theme", "light")
        primary_color = request.query_params.get("primaryColor", "#3b82f6")
        display_name = request.query_params.get("displayName", "AI Assistant")
        
        # Generate HTML page with embedded chat widget
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat Widget</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 100vh;
            overflow: hidden;
        }}
        .widget-container {{
            height: 100vh;
            width: 100vw;
        }}
    </style>
</head>
<body>
    <div id="widget-root" class="widget-container"></div>
    <script>
        // Widget configuration
        window.WIDGET_CONFIG = {{
            widgetMode: {widget_mode},
            theme: "{theme}",
            primaryColor: "{primary_color}",
            displayName: "{display_name}"
        }};
        
        // Load the chat widget
        (function() {{
            const script = document.createElement('script');
            script.src = '{request.base_url}/widget-script.js';
            script.async = true;
            script.onload = function() {{
                // Initialize widget if script provides initialization
                if (window.KnowledgeBot) {{
                    window.KnowledgeBot.init(window.WIDGET_CONFIG);
                }}
            }};
            document.head.appendChild(script);
        }})();
    </script>
</body>
</html>
        """
        
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"Error in public widget: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# GENERIC SERVICE PROXY HANDLER (catches ALL requests)
# =================================

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def generic_proxy_handler(request: Request, path: str):
    """Generic proxy handler that routes ALL requests to appropriate services"""
    # Log every incoming request for debugging
    correlation_id = request.headers.get("X-Correlation-ID", "no-correlation-id")
    logger.info(f"🔍 [{correlation_id}] API Gateway received {request.method} {request.url.path}")
    
    try:
        import httpx
        from ..core.config import get_settings
        
        # Skip auth endpoints - handle them specifically
        if path.startswith("auth/"):
            return await handle_auth_endpoints(request, path)
        
        # Determine service based on URL path
        service_url = None
        
        logger.info(f"🔍 Processing path: '{path}'")
        
        # Remove /api/v1/ prefix for routing logic
        clean_path = path.replace("/api/v1/", "") if path.startswith("/api/v1/") else path
        
        # Remove gateway/ prefix for backend service routing
        backend_path = clean_path.replace("gateway/", "") if clean_path.startswith("gateway/") else clean_path
        
        # Handle admin endpoints that are actually in configuration service
        if backend_path.startswith("admin/agents/online") or backend_path.startswith("admin/performance/metrics") or backend_path.startswith("admin/chat-sessions"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing admin endpoint to configuration service: {service_url}")
        elif backend_path.startswith("admin/"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing admin endpoint to configuration service: {service_url}")
        elif backend_path.startswith("users/unique-id"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing users endpoint to configuration service: {service_url}")
        elif backend_path.startswith("configuration/"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing to configuration service: {service_url}")
        elif backend_path.startswith("chatbot/"):
            service_url = get_settings().chatbot_orchestration_url
            logger.info(f"✅ Routing to chatbot service: {service_url}")
        elif backend_path.startswith("knowledgebase/"):
            service_url = get_settings().knowledgebase_ingestion_url
            logger.info(f"✅ Routing to knowledgebase service: {service_url}")
        elif backend_path.startswith("webcrawl") or backend_path == "webcrawl":
            service_url = get_settings().website_crawling_url
            logger.info(f"✅ Routing to webcrawl service: {service_url}")
        elif backend_path.startswith("widget/"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing widget endpoint to configuration service: {service_url}")
        else:
            logger.error(f"❌ Unknown path: {backend_path}")
            return JSONResponse(
                status_code=404,
                content={"error": f"Unknown path: {backend_path}"}
            )
        
        # Construct full URL using backend_path (without gateway/ prefix)
        full_url = f"{service_url}/api/v1/{backend_path}"
        logger.info(f"🌐 Making {request.method} request to: {full_url}")
        logger.info(f"🔍 Service URL: {service_url}")
        logger.info(f"🔍 Original path: {path}")
        logger.info(f"🔍 Clean path: {clean_path}")
        logger.info(f"🔍 Backend path: {backend_path}")
        
        # Prepare headers
        headers = dict(request.headers)
        headers.pop("host", None)
        
        logger.info(f"🔍 Headers being sent: {dict(headers)}")
        
        # Forward user data from request state
        if hasattr(request.state, 'user'):
            headers['X-User-UID'] = request.state.user.get('uid', '')
            headers['X-User-Email'] = request.state.user.get('email', '')
            headers['X-User-Name'] = request.state.user.get('name', '')
            logger.info(f"🔍 User data forwarded: {request.state.user}")
        
        # Make HTTP request to service
        # Use longer timeout for batch operations (file uploads/deletes)
        request_timeout = 30.0
        if "batch" in backend_path or "batchupload" in backend_path or "delete/batch" in backend_path:
            request_timeout = 300.0  # 5 minutes for batch operations
            logger.info(f"⏱️  Using extended timeout {request_timeout}s for batch operation")

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            logger.info(f"🔍 About to make HTTP request to: {full_url} (timeout={request_timeout}s)")
            response = await client.request(
                method=request.method,
                url=full_url,
                headers=headers,
                content=await request.body(),
                params=request.query_params
            )
            logger.info(f"✅ Received response from {full_url} (Status: {response.status_code})")
            
            # Create proper FastAPI Response from httpx response
            from fastapi.responses import Response
            
            # Copy headers from httpx response to FastAPI response
            response_headers = {}
            for key, value in response.headers.items():
                # Skip problematic headers that might cause issues
                if key.lower() not in ['content-length', 'transfer-encoding']:
                    response_headers[key] = value
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers
            )
    except httpx.ConnectError as e:
        logger.error(f"❌ Connection failed to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ This might mean the service is down or not accessible")
        raise HTTPException(status_code=503, detail=f"Service unavailable: {service_url}")
    except httpx.TimeoutException as e:
        logger.error(f"❌ Request timeout to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ This could mean: service is slow, processing large files, or service is overloaded")
        error_detail = f"Service timeout: {service_url}"
        if "batch" in backend_path:
            error_detail += " (batch operation took too long - check service logs)"
        raise HTTPException(status_code=504, detail=error_detail)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Proxy error for path '{path}': {error_msg}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        logger.error(f"❌ Full URL: {full_url}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ Full traceback: {type(e).__name__}: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {error_msg}")

# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "api_gateway"}

# =================================
# AUTH ENDPOINTS (only these are specific)
# =================================

async def handle_auth_endpoints(request: Request, path: str):
    """Handle authentication endpoints specifically"""
    if path == "auth/verify" and request.method == "POST":
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data
        }
    elif path.startswith("auth/user/") and request.method == "GET":
        uid = path.split("/")[-1]
        try:
            user_data = get_user_from_firestore(uid)
            return {
                "success": True,
                "user": user_data
            }
        except Exception as e:
            logger.error(f"Error getting user by UID {uid}: {e}")
            raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail=f"Auth endpoint not found: {path}")

# =================================
# END OF ROUTER - Only generic proxy and auth handling
# =================================
