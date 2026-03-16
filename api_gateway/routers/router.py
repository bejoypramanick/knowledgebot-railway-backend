"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import StreamingResponse, Response, JSONResponse
from typing import Dict, Any
from httpx import AsyncClient
import httpx
import asyncio

from ..core.firebase_auth import verify_firebase_token, get_user_by_uid as get_user_from_firebase
from ..core.config import get_settings
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("api_gateway.routers.router", "api-gateway")
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

# =================================
# SSE (Server-Sent Events) ENDPOINTS
# =================================

def _prepare_sse_proxy_headers(request: Request) -> dict:
    """Prepare headers for SSE proxy requests to internal services.

    Strips hop-by-hop headers and encoding headers that break SSE proxying:
    - Accept-Encoding: prevents compressed responses that proxy can't decompress
    - Connection/Keep-Alive: hop-by-hop headers not meant for proxy-to-backend
    - Host/Cookie: internal routing headers
    """
    headers = dict(request.headers)
    # Strip headers that break SSE proxying
    for h in ["host", "cookie", "accept-encoding", "connection", "keep-alive",
              "transfer-encoding", "upgrade", "sec-websocket-key",
              "sec-websocket-version", "sec-websocket-extensions"]:
        headers.pop(h, None)
    # Force identity encoding (no compression) for SSE
    headers["accept-encoding"] = "identity"

    # Forward auth context if available
    if hasattr(request.state, 'user'):
        headers['X-User-UID'] = request.state.user.get('uid', '')
        headers['X-User-Email'] = request.state.user.get('email', '')
        headers['X-User-Name'] = request.state.user.get('name', '')
        headers['X-User-Role'] = request.state.user.get('role', '')

    return headers


@router.get("/configuration/admin/events")
async def proxy_admin_events_sse(request: Request):
    """
    Proxy SSE endpoint for admin/agent events.
    SSE requires special handling - no timeout, streaming response.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/admin/events"

        logger.info(f"🔄 Proxying SSE stream to: {full_url}")

        headers = _prepare_sse_proxy_headers(request)
        if hasattr(request.state, 'user'):
            logger.info(f"✅ Forwarding user headers for SSE: {request.state.user.get('email')}")
        else:
            logger.warning("⚠️ No user found in request.state - authentication may fail")

        # Connection timeout 10s, but no read timeout (SSE streams indefinitely)
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

        async def event_stream():
            try:
                logger.info(f"📡 Starting httpx stream for admin SSE")
                async with httpx.AsyncClient(timeout=sse_timeout) as client:
                    async with client.stream("GET", full_url, headers=headers) as response:
                        logger.info(f"📡 httpx stream connected, status: {response.status_code}")
                        async for chunk in response.aiter_bytes():
                            yield chunk
                        logger.info(f"📡 httpx stream ended for admin SSE")
            except httpx.ConnectError as e:
                logger.error(f"❌ Cannot connect to config service for admin SSE: {e}")
                yield f"event: error\ndata: Connection to backend failed\n\n".encode()
            except httpx.ConnectTimeout as e:
                logger.error(f"❌ Connection timeout for admin SSE: {e}")
                yield f"event: error\ndata: Backend connection timeout\n\n".encode()
            except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                # Client disconnected - this is expected and normal, log at debug level
                logger.debug(f"🔌 Client disconnected from admin SSE stream: {type(e).__name__}")
            except Exception as e:
                # Only log unexpected errors
                error_msg = str(e)
                if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                    logger.error(f"❌ Error in SSE stream: {e}")
                else:
                    logger.debug(f"🔌 Client disconnection during SSE stream: {e}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error setting up SSE proxy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/configuration/customer/events")
async def proxy_customer_events_sse(request: Request, session_id: str = Query(..., description="Session UUID")):
    """
    Proxy SSE endpoint for customer events.
    SSE requires special handling - no timeout, streaming response.
    Session ID comes from query parameter.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/customer/events?session_id={session_id}"

        logger.info(f"🔄 Proxying customer SSE stream to: {full_url} (session: {session_id})")

        headers = _prepare_sse_proxy_headers(request)

        # Connection timeout 10s, but no read timeout (SSE streams indefinitely)
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

        async def event_stream():
            try:
                logger.info(f"📡 Starting httpx stream for session {session_id}")
                async with httpx.AsyncClient(timeout=sse_timeout) as client:
                    async with client.stream("GET", full_url, headers=headers) as response:
                        logger.info(f"📡 httpx stream connected, status: {response.status_code}")
                        async for chunk in response.aiter_bytes():
                            yield chunk
                        logger.info(f"📡 httpx stream ended for session {session_id}")
            except httpx.ConnectError as e:
                logger.error(f"❌ Cannot connect to config service for customer SSE ({session_id}): {e}")
                yield f"event: error\ndata: Connection to backend failed\n\n".encode()
            except httpx.ConnectTimeout as e:
                logger.error(f"❌ Connection timeout for customer SSE ({session_id}): {e}")
                yield f"event: error\ndata: Backend connection timeout\n\n".encode()
            except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                # Client disconnected - this is expected and normal, log at debug level
                logger.debug(f"🔌 Client disconnected from customer SSE stream (session {session_id}): {type(e).__name__}")
            except Exception as e:
                # Only log unexpected errors
                error_msg = str(e)
                if "peer closed connection" not in error_msg.lower() and "incomplete chunked read" not in error_msg.lower():
                    logger.error(f"❌ Error in customer SSE stream: {e}")
                else:
                    logger.debug(f"🔌 Client disconnection during customer SSE stream (session {session_id}): {e}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error setting up customer SSE proxy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# AGENT MESSAGE PROXY
# =================================

@router.post("/configuration/admin/chat-sessions/messages")
async def proxy_agent_message(request: Request):
    """Proxy agent messages - converts session UUID to numeric ID before forwarding"""
    try:
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Proxy endpoint called")
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Request headers: {dict(request.headers)}")
        
        settings = get_settings()
        config_service_url = settings.configuration_service_url  # Lowercase!
        
        # Get request body
        body = await request.json()
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Request body: {body}")
        
        session_uuid = body.get("session_id")  # UUID from frontend
        
        if not session_uuid:
            logger.error(f"❌ [AGENT_MESSAGE_PROXY] session_id missing in request body")
            raise HTTPException(status_code=400, detail="session_id is required")
        
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Received agent message for session UUID: {session_uuid}")
        
        # Convert UUID to numeric ID
        from sqlalchemy import text
        from shared.sqlalchemy_db import get_db_session
        
        async with get_db_session() as db_session:
            query = text("SELECT id FROM chat_sessions WHERE session_id = :session_uuid")
            result = await db_session.execute(query, {"session_uuid": session_uuid})
            row = result.mappings().first()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Session not found: {session_uuid}")
            
            numeric_session_id = row['id']
            logger.info(f"✅ [AGENT_MESSAGE_PROXY] Converted UUID {session_uuid} to numeric ID {numeric_session_id}")
        
        # Update body with numeric ID
        body["session_id"] = numeric_session_id

        # CRITICAL: Set agent_id from authenticated user (NOT from body)
        # Read from request.state (set by SessionAuthMiddleware after Firebase verification)
        # This ensures the actual sender's email is used for authorization
        user_email = getattr(request.state, "user_email", "")
        if user_email:
            body["agent_id"] = user_email
            logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Set agent_id from authenticated user: {user_email}")
        else:
            logger.warning(f"⚠️ [AGENT_MESSAGE_PROXY] No authenticated user email found in request state")

        # Forward to configuration service with authenticated user info
        async with AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config_service_url}/api/v1/configuration/admin/chat-sessions/messages",
                json=body,
                headers={
                    "X-User-Email": user_email,
                    "X-User-Role": getattr(request.state, "user_role", ""),
                    "Content-Type": "application/json"
                }
            )
            
            logger.info(f"✅ [AGENT_MESSAGE_PROXY] Forwarded message to configuration service, status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"❌ [AGENT_MESSAGE_PROXY] Configuration service returned error: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return response.json()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGENT_MESSAGE_PROXY] Error proxying agent message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/user/{uid}")
async def get_user_by_uid(uid: str):
    """Get user information by Firebase UID."""
    try:
        user_data = get_user_from_firebase(uid)
        if not user_data:
            raise HTTPException(status_code=404, detail=f"User not found: {uid}")
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
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

@router.post("/users/switch-role")
async def switch_user_role(request: Request):
    """Switch the user's role by removing old roles and adding new role (users can have only ONE active role)"""
    try:
        # Get uid from query parameter
        uid = request.query_params.get("uid")
        if not uid:
            raise HTTPException(status_code=400, detail="Missing uid parameter")

        # Get role from request body
        body = await request.json()
        new_role = body.get("role")
        if not new_role:
            raise HTTPException(status_code=400, detail="Missing role in request body")

        # Validate role is one of the allowed values
        valid_roles = ["admin", "agent", "customer"]  # Backend API expects these
        if new_role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

        logger.info(f"🔄 Switching user {uid} to role: {new_role}")

        try:
            # Import database session and text
            from sqlalchemy import text
            from shared.sqlalchemy_db import get_db_session

            user_id = int(uid)

            async with get_db_session() as session:
                # Step 1: Get user's current roles
                get_roles_query = text("""
                    SELECT r.role_name, r.id as role_id
                    FROM user_role_mapping urm
                    JOIN roles r ON urm.role_id = r.id
                    WHERE urm.user_id = :user_id AND urm.is_active = true
                """)
                result = await session.execute(get_roles_query, {"user_id": user_id})
                current_roles = result.fetchall()

                if not current_roles:
                    logger.warning(f"⚠️ User {uid} has no current roles")
                    raise HTTPException(status_code=404, detail="User has no current roles")

                logger.info(f"📋 User {uid} current roles: {[r['role_name'] for r in current_roles]}")

                # Step 2: Remove all current roles
                for current_role in current_roles:
                    remove_query = text("""
                        UPDATE user_role_mapping
                        SET is_active = false, updated_at = NOW()
                        WHERE user_id = :user_id AND role_id = :role_id
                    """)
                    await session.execute(remove_query, {
                        "user_id": user_id,
                        "role_id": current_role['role_id']
                    })
                    logger.info(f"✂️ Removed role: {current_role['role_name']}")

                # Step 3: Get the ID of the new role
                get_new_role_id = text("""
                    SELECT id FROM roles WHERE role_name = :role_name
                """)
                result = await session.execute(get_new_role_id, {"role_name": new_role})
                new_role_row = result.fetchone()

                if not new_role_row:
                    logger.error(f"❌ Role '{new_role}' not found in database")
                    raise HTTPException(status_code=400, detail=f"Role '{new_role}' not found")

                new_role_id = new_role_row['id']

                # Step 4: Add new role
                add_query = text("""
                    INSERT INTO user_role_mapping (user_id, role_id, is_active, created_at, updated_at)
                    VALUES (:user_id, :role_id, true, NOW(), NOW())
                    ON CONFLICT (user_id, role_id) DO UPDATE
                    SET is_active = true, updated_at = NOW()
                """)
                await session.execute(add_query, {
                    "user_id": user_id,
                    "role_id": new_role_id
                })
                logger.info(f"➕ Added new role: {new_role}")

                # Commit all changes
                await session.commit()

            logger.info(f"✅ Successfully switched user {uid} to role: {new_role}")

            return {
                "success": True,
                "message": f"Role switched to {new_role}",
                "uid": uid,
                "role": new_role
            }

        except HTTPException:
            raise
        except Exception as db_error:
            logger.error(f"❌ Error updating database: {db_error}")
            raise HTTPException(status_code=500, detail=f"Error switching role: {str(db_error)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching user role: {e}")
        raise HTTPException(status_code=500, detail=f"Error switching role: {str(e)}")

# =================================
# PUBLIC CHAT ENDPOINTS (No Authentication Required)
# =================================

@router.post("/chatbot/chat/stream")
async def public_chat_stream(request: Request):
    """Public chat streaming endpoint - no authentication required for website visitors"""
    try:
        import httpx
        import json
        from ..core.config import get_settings

        # Get request body - just pass it through as-is
        # Client should NOT send session_id (comes from cookie) or use_rag (defaults to true)
        body_bytes = await request.body()

        # Only check chat enabled status on first message of each session
        if not hasattr(request.state, 'chat_status_checked'):
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
                    logger.info("Chat is enabled")
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

        # Make request to chatbot service — streaming SSE proxy
        # No read timeout: first chunk can take a while (RAG search + AI inference)
        # Chunks are forwarded to the client as they arrive from the backend
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

        from fastapi.responses import StreamingResponse

        async with httpx.AsyncClient(timeout=sse_timeout, follow_redirects=False) as client:
            async with client.stream(
                method=request.method,
                url=f"{chatbot_service_url}/api/v1/chatbot/chat/stream",
                headers=headers,
                content=body_bytes,
            ) as response:

                logger.info(f"✅ [{correlation_id}] Chat stream connected: {response.status_code}")

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

                # Forward SSE chunks as they arrive from the backend
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
# PUBLIC WIDGET CONFIGURATION ENDPOINT (No Authentication Required)
# =================================

@router.get("/configuration/widgetConfig")
async def get_widget_config(request: Request):
    """
    Proxy endpoint for widget configuration.
    Used by embedded bubble widget to load chat settings (colors, display name, etc).
    No authentication required - public endpoint - allows all origins.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        logger.info(f"🔄 Proxying widget config request to: {full_url}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url)

            if response.status_code == 200:
                config_data = response.json()
                logger.info(f"✓ Widget config loaded: display_name={config_data.get('display_name')}, has_icon={bool(config_data.get('chat_icon_url'))}")
                # Explicitly set CORS headers for public endpoint
                return JSONResponse(
                    content=config_data,
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                    }
                )
            else:
                logger.error(f"❌ Config service returned {response.status_code}: {response.text[:200]}")
                raise HTTPException(status_code=response.status_code, detail="Failed to load widget configuration")

    except Exception as e:
        logger.error(f"❌ Error proxying widget config: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading widget configuration: {str(e)}")


# =================================
# ADMIN WIDGET CONFIGURATION ENDPOINT (Authentication Required)
# =================================

@router.get("/configuration/admin/widgetConfig")
async def get_admin_widget_config(request: Request):
    """
    Admin endpoint for widget configuration.
    Used by admin dashboard to manage chat settings.
    Requires authentication - allows credentials.
    """
    try:
        # User is already authenticated by SessionAuthMiddleware
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        logger.info(f"🔄 Proxying admin widget config request to: {full_url}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url)

            if response.status_code == 200:
                config_data = response.json()
                logger.info(f"✓ Admin widget config loaded: display_name={config_data.get('display_name')}")
                # Return with specific origin and credentials allowed
                origin = request.headers.get('origin', '*')
                return JSONResponse(
                    content=config_data,
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            else:
                logger.error(f"❌ Config service returned {response.status_code}: {response.text[:200]}")
                raise HTTPException(status_code=response.status_code, detail="Failed to load widget configuration")

    except Exception as e:
        logger.error(f"❌ Error proxying admin widget config: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading widget configuration: {str(e)}")


@router.post("/configuration/admin/widgetConfig")
async def save_admin_widget_config(request: Request):
    """
    Admin endpoint for saving widget configuration.
    Requires authentication - allows credentials.
    """
    try:
        # User is already authenticated by SessionAuthMiddleware
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        # Get request body and forward original content-type (may be multipart/form-data with images)
        body = await request.body()
        content_type = request.headers.get("content-type", "application/json")

        logger.info(f"🔄 Proxying admin widget config save request to: {full_url} (content-type: {content_type[:50]})")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                full_url,
                content=body,
                headers={"Content-Type": content_type}
            )

            if response.status_code in [200, 201]:
                config_data = response.json()
                logger.info(f"✓ Admin widget config saved")
                # Return with specific origin and credentials allowed
                origin = request.headers.get('origin', '*')
                return JSONResponse(
                    content=config_data,
                    status_code=response.status_code,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            else:
                logger.error(f"❌ Config service returned {response.status_code}: {response.text[:200]}")
                raise HTTPException(status_code=response.status_code, detail="Failed to save widget configuration")

    except Exception as e:
        logger.error(f"❌ Error proxying admin widget config save: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving widget configuration: {str(e)}")


# =================================
# PUBLIC SECURITY SETTINGS ENDPOINT (No Authentication Required)
# =================================

@router.get("/configuration/data/security-settings")
async def get_security_settings(request: Request):
    """
    Proxy endpoint for security settings (public, no auth required).
    Used by chat widget to get response policies and settings.
    Allows all origins for embedded widgets.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/data/security-settings"

        logger.info(f"🔄 Proxying security settings request to: {full_url}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url)

            if response.status_code == 200:
                settings_data = response.json()
                logger.info(f"✓ Security settings loaded: {settings_data}")
                # Explicitly set CORS headers for public endpoint
                return JSONResponse(
                    content=settings_data,
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                    }
                )
            else:
                logger.error(f"❌ Config service returned {response.status_code}: {response.text[:200]}")
                raise HTTPException(status_code=response.status_code, detail="Failed to load security settings")

    except Exception as e:
        logger.error(f"❌ Error proxying security settings: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading security settings: {str(e)}")


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
        # Backend services register routers with /api/v1/{service_name} prefix
        service_path = backend_path  # Default: use backend_path as-is

        if backend_path.startswith("configuration/"):
            service_url = get_settings().configuration_service_url
            # Keep the service prefix - configuration service expects /api/v1/configuration/...
            logger.info(f"✅ Routing to configuration service: {service_url}")
        elif backend_path.startswith("chatbot/"):
            service_url = get_settings().chatbot_orchestration_url
            # Keep the service prefix - chatbot service expects /api/v1/chatbot/...
            logger.info(f"✅ Routing to chatbot service: {service_url}")
        elif backend_path.startswith("knowledgebase/"):
            service_url = get_settings().knowledgebase_ingestion_url
            # Keep the service prefix - knowledgebase service expects /api/v1/knowledgebase/...
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
        # Internal services expect /api/v1/{service_name}/{endpoint}
        # The service_path already includes the service prefix (e.g., "configuration/users/profile")
        full_url = f"{service_url}/api/v1/{service_path}"
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
            headers['X-User-Role'] = request.state.user.get('role', '')
            logger.info(f"🔍 User data forwarded: {request.state.user}")
        
        # Make HTTP request to service
        # Use longer timeout for batch operations (file uploads/deletes) and complex queries
        # NOTE: webcrawl uses async Celery, returns immediately with task ID (no long timeout needed)
        request_timeout = 30.0
        if "chatAgentConfig" in backend_path or "configuration/chatAgentConfig" in backend_path:
            request_timeout = 60.0  # Configuration aggregates multiple DB queries
            logger.info(f"⏱️  Using extended timeout {request_timeout}s for chatAgentConfig (multiple parallel queries)")
        elif "configuration/data/" in backend_path:
            request_timeout = 60.0  # Data endpoints may do complex queries
            logger.info(f"⏱️  Using extended timeout {request_timeout}s for data endpoint")
        elif "batch" in backend_path or "batchupload" in backend_path or "delete/batch" in backend_path:
            request_timeout = 300.0  # 5 minutes for batch operations
            logger.info(f"⏱️  Using extended timeout {request_timeout}s for batch operation")
        # webcrawl/async returns immediately (task dispatched to Celery), no extended timeout needed
        # if backend_path.startswith("webcrawl"):
        #     request_timeout = 600.0  # Was for sync scraping - NO LONGER NEEDED
        #     logger.info(f"⏱️  Using extended timeout {request_timeout}s for web crawling")

        async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=False) as client:
            logger.info(f"🔍 About to make HTTP request to: {full_url} (timeout={request_timeout}s)")

            # For SSE and other streaming responses, we need special handling
            # Check content-type to decide how to handle the response
            request_body = await request.body()

            # CRITICAL: Ensure numeric session_id in request body for internal services
            # API Gateway extracts UUID from cookie and converts to numeric ID
            # Internal services ONLY accept numeric session_id (never UUID)
            # EXCEPTION: set-current endpoints intentionally accept UUIDs
            should_ensure_session_id = (
                request_body and
                request.method in ["POST", "PUT", "PATCH"] and
                "set-current" not in full_url
            )

            if should_ensure_session_id:
                try:
                    import json
                    body_data = json.loads(request_body)

                    # Check if request has session_id
                    if "session_id" in body_data:
                        client_session_id = body_data["session_id"]

                        # VALIDATION: Reject UUIDs for configuration service endpoints
                        # Configuration service endpoints MUST receive numeric session_id only
                        if isinstance(client_session_id, str) and client_session_id.startswith("session_"):
                            # Client sent UUID - must convert to numeric
                            # Two scenarios:
                            # 1. Customer endpoints: UUID from cookie, middleware already resolved it
                            # 2. Admin endpoints: UUID from request body, need to resolve it here
                            numeric_id = None
                            
                            # First check if middleware already resolved it (customer endpoints)
                            if hasattr(request.state, "session_numeric_id") and request.state.session_numeric_id:
                                numeric_id = request.state.session_numeric_id
                                logger.info(f"🔄 Using middleware-resolved numeric ID: {client_session_id} → {numeric_id}")
                            else:
                                # Middleware didn't resolve it (admin endpoints) - do it here
                                logger.info(f"🔍 Resolving UUID from request body: {client_session_id}")
                                from sqlalchemy import text
                                from shared.sqlalchemy_db import get_db_session
                                
                                try:
                                    async with get_db_session() as db_session:
                                        query = text("SELECT id FROM chat_sessions WHERE session_id = :session_uuid")
                                        logger.debug(f"🔍 Executing query: {query} with session_uuid={client_session_id}")
                                        result = await db_session.execute(query, {"session_uuid": client_session_id})
                                        row = result.mappings().first()
                                        
                                        if row:
                                            numeric_id = row['id']
                                            logger.info(f"✅ Resolved UUID to numeric ID: {client_session_id} → {numeric_id}")
                                        else:
                                            logger.warning(f"⚠️ Session UUID not found in database: {client_session_id}")
                                            logger.warning(f"⚠️ Query returned no results for session_id = '{client_session_id}'")
                                except Exception as e:
                                    logger.error(f"❌ Error resolving UUID: {e}", exc_info=True)
                            
                            if numeric_id:
                                # Conversion successful - use numeric ID
                                body_data["session_id"] = numeric_id
                                logger.info(f"🔄 Converted UUID to numeric in body: {client_session_id} → {numeric_id}")
                            else:
                                # Conversion failed - check if this is a session creation endpoint
                                # For chatbot stream, allow UUID to pass through so backend can create session
                                # This handles race conditions where backend generated UUID but session not yet in DB
                                if "chatbot/chat/stream" in full_url:
                                    logger.info(f"✅ Allowing UUID to pass through for chatbot stream: {client_session_id}")
                                    # Keep the UUID in body - backend will create the session
                                else:
                                    # For other endpoints, reject if UUID not found
                                    logger.error(f"❌ Failed to resolve session UUID {client_session_id} for {backend_path}")
                                    raise HTTPException(
                                        status_code=400,
                                        detail=f"Invalid session: UUID could not be resolved. Session may not exist or may have expired."
                                    )
                        # else: already numeric or other format - assume it's valid
                    else:
                        # No session_id in body - try to inject from cookie if available
                        if hasattr(request.state, "session_numeric_id") and request.state.session_numeric_id:
                            body_data["session_id"] = request.state.session_numeric_id
                            logger.info(f"✅ Injected numeric session_id into body: {request.state.session_numeric_id}")

                    # ALSO inject session_uuid for broadcasting (customer SSE channels use UUID)
                    if hasattr(request.state, "session_uuid") and request.state.session_uuid:
                        body_data["session_uuid"] = request.state.session_uuid
                        logger.debug(f"✅ Injected session_uuid into body: {request.state.session_uuid}")

                    request_body = json.dumps(body_data).encode()

                    # IMPORTANT: Update Content-Length header after modifying request body
                    # Remove old header first to avoid conflicting Content-Length headers
                    headers.pop("content-length", None)
                    headers["Content-Length"] = str(len(request_body))
                except HTTPException:
                    raise
                except (json.JSONDecodeError, ValueError) as e:
                    # Not JSON or other error - forward as-is
                    logger.debug(f"⚠️  Could not parse request body as JSON: {e}")
                    pass

            # Make request without streaming first to check headers
            response = await client.request(
                method=request.method,
                url=full_url,
                headers=headers,
                content=request_body,
                params=request.query_params
            )
            logger.info(f"✅ Received response from {full_url} (Status: {response.status_code})")

            # Create proper FastAPI Response from httpx response
            from fastapi.responses import StreamingResponse, Response

            # Check if response contains a session UUID that needs to be set in httpOnly cookie
            session_uuid_from_response = response.headers.get("X-Session-UUID") or response.headers.get("x-session-uuid")

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
                'x-session-uuid',  # Remove internal header from response
            ]
            for key, value in response.headers.items():
                # Skip headers that might contain internal URLs or cause issues
                if key.lower() not in blocked_headers:
                    response_headers[key] = value

            # Create response
            response_obj = Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers
            )

            # CRITICAL: Handle Set-Cookie headers separately (can have multiple)
            # httpx response.headers.get_list() returns all values for a header
            set_cookie_headers = response.headers.get_list('set-cookie')
            for cookie_header in set_cookie_headers:
                logger.info(f"🍪 Forwarding Set-Cookie header from backend: {cookie_header[:50]}...")
                response_obj.headers.append('set-cookie', cookie_header)

            # If response contains session UUID, set httpOnly cookie
            if session_uuid_from_response:
                logger.info(f"🍪 Setting httpOnly cookie for session UUID: {session_uuid_from_response}")
                response_obj.set_cookie(
                    key="chatbot_session_id",
                    value=session_uuid_from_response,
                    httponly=True,
                    secure=True,
                    samesite="Strict",
                    max_age=60 * 60 * 24  # 24 hours
                )

            return response_obj
    except httpx.ConnectError as e:
        logger.error(f"❌ Connection failed to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ This might mean the service is down or not accessible")
        logger.warning(f"⚠️  Attempting retry for service wake-up (Railway sleep/wake cycle)...")
        
        # Retry logic for Railway services that might be sleeping
        retry_delays = [1.0, 2.0, 3.0]  # Exponential backoff for service wake-up
        for attempt, delay in enumerate(retry_delays, 1):
            try:
                logger.info(f"🔄 Retry attempt {attempt}/{len(retry_delays)} after {delay}s delay...")
                await asyncio.sleep(delay)
                
                async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=False) as retry_client:
                    retry_response = await retry_client.request(
                        method=request.method,
                        url=full_url,
                        headers=headers,
                        content=body if request.method in ["POST", "PUT", "PATCH"] else None,
                        params=dict(request.query_params) if request.query_params else None,
                    )
                    logger.info(f"✅ Retry successful! Status: {retry_response.status_code}")
                    
                    # Handle streaming responses
                    if "text/event-stream" in retry_response.headers.get("content-type", ""):
                        async def retry_stream():
                            async with retry_response:
                                async for chunk in retry_response.aiter_bytes():
                                    yield chunk
                        return StreamingResponse(retry_stream(), media_type="text/event-stream")
                    
                    return Response(
                        content=retry_response.content,
                        status_code=retry_response.status_code,
                        headers=dict(retry_response.headers),
                    )
            except (httpx.ConnectError, httpx.TimeoutException) as retry_error:
                if attempt < len(retry_delays):
                    logger.warning(f"⚠️  Retry {attempt} failed: {retry_error}, will retry again...")
                    continue
                else:
                    logger.error(f"❌ All retry attempts failed. Service is not responding.")
                    raise HTTPException(status_code=503, detail=f"Service unavailable after retries: {service_url}")
        
        raise HTTPException(status_code=503, detail=f"Service unavailable: {service_url}")
    except httpx.TimeoutException as e:
        logger.error(f"❌ Request timeout to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ This could mean: service is slow, processing large files, or service is overloaded")
        logger.warning(f"⚠️  Attempting retry for slow service wake-up...")
        
        # Retry logic for slow services (might be waking up)
        retry_delays = [2.0, 4.0, 6.0]  # Longer delays for timeout scenarios
        for attempt, delay in enumerate(retry_delays, 1):
            try:
                logger.info(f"🔄 Timeout retry attempt {attempt}/{len(retry_delays)} after {delay}s delay...")
                await asyncio.sleep(delay)
                
                async with httpx.AsyncClient(timeout=request_timeout * 1.5, follow_redirects=False) as retry_client:
                    retry_response = await retry_client.request(
                        method=request.method,
                        url=full_url,
                        headers=headers,
                        content=body if request.method in ["POST", "PUT", "PATCH"] else None,
                        params=dict(request.query_params) if request.query_params else None,
                    )
                    logger.info(f"✅ Timeout retry successful! Status: {retry_response.status_code}")
                    
                    # Handle streaming responses
                    if "text/event-stream" in retry_response.headers.get("content-type", ""):
                        async def retry_stream():
                            async with retry_response:
                                async for chunk in retry_response.aiter_bytes():
                                    yield chunk
                        return StreamingResponse(retry_stream(), media_type="text/event-stream")
                    
                    return Response(
                        content=retry_response.content,
                        status_code=retry_response.status_code,
                        headers=dict(retry_response.headers),
                    )
            except (httpx.ConnectError, httpx.TimeoutException) as retry_error:
                if attempt < len(retry_delays):
                    logger.warning(f"⚠️  Timeout retry {attempt} failed: {retry_error}, will retry again...")
                    continue
                else:
                    logger.error(f"❌ All timeout retry attempts failed. Service is not responding.")
                    raise HTTPException(status_code=504, detail=f"Service timeout after retries: {service_url}")
        
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
            user_data = get_user_from_firebase(uid)
            if not user_data:
                raise HTTPException(status_code=404, detail=f"User not found: {uid}")
            return {
                "success": True,
                "user": user_data
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user by UID {uid}: {e}")
            raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail=f"Auth endpoint not found: {path}")

# =================================
# DEBUG ENDPOINTS
# =================================

@router.get("/debug/auth-headers")
async def debug_auth_headers(request: Request):
    """Debug endpoint to check what auth headers are being received"""
    return {
        "authorization_header": request.headers.get("authorization", "NOT PRESENT"),
        "x_user_uid": request.headers.get("x-user-uid", "NOT PRESENT"),
        "x_user_email": request.headers.get("x-user-email", "NOT PRESENT"),
        "x_user_name": request.headers.get("x-user-name", "NOT PRESENT"),
        "has_request_state_user": hasattr(request.state, 'user'),
        "request_state_user": str(getattr(request.state, 'user', 'NOT PRESENT')),
        "all_headers": dict(request.headers)
    }

# =================================
# END OF ROUTER - Only generic proxy and auth handling
# =================================
