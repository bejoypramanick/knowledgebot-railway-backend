"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, Response, JSONResponse
import logging
import asyncio
from typing import Dict, Any
from httpx import AsyncClient
import httpx

from ..core.firebase_auth import verify_firebase_token, get_user_from_firestore
from ..core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


async def check_config_service_with_retry(config_service_url: str, max_retries: int = 2) -> Dict[str, Any]:
    """
    Check configuration service with retry logic for connection failures.
    Returns config dict or None if all attempts fail.
    """
    retry_delays = [0.5, 1.0]  # Quick retries for better UX
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{config_service_url}/api/v1/configuration/widgetConfig",
                    timeout=3.0
                )
                
                if response.status_code == 200:
                    return response.json()
                    
        except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if attempt < max_retries - 1:
                delay = retry_delays[attempt]
                logger.warning(f"⚠️ Config service connection failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"❌ Config service unavailable after {max_retries} attempts")
                return None
        except Exception as e:
            logger.error(f"❌ Unexpected error checking config service: {e}")
            return None
    
    return None

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
            
            config = await check_config_service_with_retry(config_service_url)
            
            if config:
                chat_enabled = config.get("display_chatbot", True)
                request.state.chat_status_checked = True
                request.state.chat_enabled = chat_enabled
                
                if not chat_enabled:
                    logger.info("Chat is disabled - blocking request")
                    raise HTTPException(status_code=403, detail="Chat is currently disabled")
                else:
                    logger.info(f"Chat is enabled for session {session_id}")
            else:
                # If we can't check the status, allow the request (fail open)
                logger.warning("⚠️ Could not verify chat status, allowing request (fail open)")
                request.state.chat_status_checked = True
                request.state.chat_enabled = True
        
        # If we haven't checked the status yet (no session_id or first request), check now
        elif not hasattr(request.state, 'chat_status_checked'):
            config_service_url = "http://configuration.railway.internal:8080"  # Internal service URL
            
            config = await check_config_service_with_retry(config_service_url)
            
            if config:
                chat_enabled = config.get("display_chatbot", True)
                request.state.chat_status_checked = True
                request.state.chat_enabled = chat_enabled
                
                if not chat_enabled:
                    logger.info("Chat is disabled - blocking request")
                    raise HTTPException(status_code=403, detail="Chat is currently disabled")
            else:
                # If we can't check the status, allow the request (fail open)
                logger.warning("⚠️ Could not verify chat status, allowing request (fail open)")
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
        import uuid
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        logger.info(f"🔍 [{correlation_id}] Public chat stream request received from authorized domain")
        
        # Prepare headers - remove auth-related headers for public endpoint
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("authorization", None)
        
        # Make request to chatbot service
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                method=request.method,
                url=f"{chatbot_service_url}/api/v1/chatbot/chat/stream",
                headers=headers,
                content=await request.body(),
                params=request.query_params
            )

            logger.info(f"✅ [{correlation_id}] Chat stream response: {response.status_code}")

            # Filter response headers to prevent internal URL leakage
            response_headers = {}
            blocked_headers = [
                'content-length',
                'transfer-encoding',
                'location',
                'content-location',
                'host',
                'server',
            ]
            for key, value in response.headers.items():
                if key.lower() not in blocked_headers:
                    response_headers[key] = value

            # Return streaming response
            from fastapi.responses import StreamingResponse

            async def stream_response():
                async for chunk in response.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                stream_response(),
                status_code=response.status_code,
                headers=response_headers
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
    import uuid
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
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

        # Remove /api/v1/ or api/v1/ prefix for routing logic (handle both with/without leading slash)
        if path.startswith("/api/v1/"):
            clean_path = path.replace("/api/v1/", "", 1)
        elif path.startswith("api/v1/"):
            clean_path = path.replace("api/v1/", "", 1)
        else:
            clean_path = path

        # Remove gateway/ prefix for backend service routing
        backend_path = clean_path.replace("gateway/", "", 1) if clean_path.startswith("gateway/") else clean_path

        # Determine service routing
        # Backend services register routers with /{service_name} prefix (internal URLs, no /api/v1)
        service_path = backend_path  # Default: use backend_path as-is

        if backend_path.startswith("configuration/"):
            service_url = get_settings().configuration_service_url
            # Keep the service prefix - configuration service expects /configuration/...
            logger.info(f"✅ Routing to configuration service: {service_url}")
        elif backend_path.startswith("chatbot/"):
            service_url = get_settings().chatbot_orchestration_url
            # Keep the service prefix - chatbot service expects /chatbot/...
            logger.info(f"✅ Routing to chatbot service: {service_url}")
        elif backend_path.startswith("knowledgebase/"):
            service_url = get_settings().knowledgebase_ingestion_url
            # Keep the service prefix - knowledgebase service expects /knowledgebase/...
            logger.info(f"✅ Routing to knowledgebase service: {service_url}")
        elif backend_path.startswith("webcrawl"):
            service_url = get_settings().knowledgebase_ingestion_url
            logger.info(f"✅ Routing webcrawl to knowledgebase_ingestion service: {service_url}")
        elif backend_path.startswith("admin/") or backend_path.startswith("users/") or backend_path.startswith("widget/") or backend_path.startswith("feedback") or backend_path.startswith("messages/"):
            # These are all configuration service endpoints but without the service prefix
            # Need to add "configuration/" prefix for proper routing
            service_url = get_settings().configuration_service_url
            service_path = f"configuration/{backend_path}"
            logger.info(f"✅ Routing to configuration service (non-prefixed endpoint): {service_url}")
        else:
            logger.error(f"❌ Unknown path: {backend_path}")
            return JSONResponse(
                status_code=404,
                content={"error": f"Unknown path: {backend_path}"}
            )

        # Construct full URL for internal service communication
        # Internal services are called directly without /api/v1 prefix (that's only for external/gateway endpoints)
        # The service_path already includes the service prefix (e.g., "configuration/users/profile")
        full_url = f"{service_url}/{service_path}"
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
        # NOTE: webcrawl uses async Celery, returns immediately with task ID (no long timeout needed)
        request_timeout = 30.0
        if "batch" in backend_path or "batchupload" in backend_path or "delete/batch" in backend_path:
            request_timeout = 300.0  # 5 minutes for batch operations
            logger.info(f"⏱️  Using extended timeout {request_timeout}s for batch operation")
        # webcrawl/async returns immediately (task dispatched to Celery), no extended timeout needed
        # if backend_path.startswith("webcrawl"):
        #     request_timeout = 600.0  # Was for sync scraping - NO LONGER NEEDED
        #     logger.info(f"⏱️  Using extended timeout {request_timeout}s for web crawling")

        async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=False) as client:
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
            # CRITICAL: Filter out headers that might contain internal URLs
            response_headers = {}
            blocked_headers = [
                'content-length',
                'transfer-encoding',
                'location',  # Prevent internal redirects from leaking
                'content-location',  # Prevent internal URLs in content location
                'host',  # Don't expose internal host
                'server',  # Don't expose server details
            ]
            for key, value in response.headers.items():
                # Skip headers that might contain internal URLs or cause issues
                if key.lower() not in blocked_headers:
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
