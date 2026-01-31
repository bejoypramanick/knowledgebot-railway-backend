"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from typing import Dict, List, Any, Optional
import logging
import json
import time
import httpx

from ..core.firebase_auth import verify_firebase_token, get_user_from_firestore
from ..core.config import get_settings
from ..core.sse import sse_generator, sse_manager
from ..core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)
router = APIRouter()

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
        
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
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
        # Get token from request body
        body = await request.json()
        token = body.get("token")
        
        if not token:
            raise HTTPException(status_code=400, detail="Missing token")
        
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
# GENERIC SERVICE PROXY HANDLER (catches ALL requests)
# =================================

@router.api_route("/{path:path}")
async def generic_proxy_handler(request: Request, path: str):
    """Generic proxy handler that routes ALL requests to appropriate services"""
    try:
        import httpx
        from ..core.config import get_settings
        
        # Skip auth endpoints - handle them specifically
        if path.startswith("auth/"):
            return await handle_auth_endpoints(request, path)
        
        # Determine service based on URL path
        service_url = None
        
        logger.info(f"🔍 Processing path: '{path}'")
        
        if path.startswith("configuration/"):
            service_url = get_settings().configuration_service_url
            logger.info(f"✅ Routing to configuration service: {service_url}")
        elif path.startswith("chatbot/"):
            service_url = get_settings().chatbot_orchestration_url
            logger.info(f"✅ Routing to chatbot service: {service_url}")
        elif path.startswith("knowledgebase/"):
            service_url = get_settings().knowledgebase_ingestion_url
            logger.info(f"✅ Routing to knowledgebase service: {service_url}")
        elif path.startswith("webcrawl/"):
            service_url = get_settings().website_crawling_url
            logger.info(f"✅ Routing to webcrawl service: {service_url}")
        else:
            logger.error(f"❌ Unknown service path: '{path}'")
            raise HTTPException(status_code=404, detail=f"Unknown service path: {path}")
        
        # Construct full URL
        full_url = f"{service_url}/api/v1/{path}"
        logger.info(f"🌐 Making {request.method} request to: {full_url}")
        
        # Prepare headers
        headers = dict(request.headers)
        headers.pop("host", None)
        
        # Forward user data from request state
        if hasattr(request.state, 'user'):
            headers['X-User-UID'] = request.state.user.get('uid', '')
            headers['X-User-Email'] = request.state.user.get('email', '')
            headers['X-User-Name'] = request.state.user.get('name', '')
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Make the request to the appropriate service
            logger.info(f"🌐 Making {request.method} request to: {full_url}")
            
            if request.method == "GET":
                logger.info(f"📥 Processing GET request")
                response = await client.get(full_url, headers=headers, params=request.query_params)
            elif request.method == "POST":
                logger.info(f"📤 Processing POST request")
                try:
                    body = await request.json()
                    logger.info(f"📤 POST body: {body}")
                    response = await client.post(full_url, json=body, headers=headers)
                except Exception as json_error:
                    logger.error(f"❌ Error parsing POST body: {json_error}")
                    raise HTTPException(status_code=400, detail="Invalid JSON in request body")
            elif request.method == "PUT":
                logger.info(f"📝 Processing PUT request")
                body = await request.json()
                response = await client.put(full_url, json=body, headers=headers)
            elif request.method == "DELETE":
                logger.info(f"🗑️ Processing DELETE request")
                response = await client.delete(full_url, headers=headers)
            else:
                logger.error(f"❌ Unsupported method: {request.method}")
                raise HTTPException(status_code=405, detail="Method not allowed")
            
            logger.info(f"✅ Response status: {response.status_code}")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Generic proxy error for path '{path}': {e}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

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
# SSE ENDPOINTS
# =================================

@router.get("/ws/events")
async def websocket_sse_endpoint():
    """SSE endpoint to replace WebSocket functionality."""
    queue = await sse_manager.connect()
    
    try:
        return StreamingResponse(
            sse_generator(queue),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
    except Exception as e:
        logger.error(f"SSE endpoint error: {e}")
        await sse_manager.disconnect(queue)
        raise HTTPException(status_code=500, detail="SSE connection failed")

@router.post("/ws/messages")
async def websocket_message_endpoint(request: Request):
    """HTTP endpoint to receive messages and broadcast via SSE."""
    try:
        data = await request.json()
        
        message = {
            "type": "response",
            "message": data.get("message", ""),
            "conversation_id": data.get("conversation_id", ""),
            "timestamp": time.time(),
            "metadata": data.get("metadata", {})
        }
        
        await sse_manager.broadcast(message)
        
        return {"success": True, "message": "Message broadcasted"}
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail="Failed to process message")

@router.get("/configuration/chat/{session_id}/events")
async def proxy_customer_sse(session_id: str, request: Request):
    """Proxy customer SSE connections to configuration service"""
    try:
        sse_url = f"{get_settings().configuration_service_url}/api/v1/configuration/chat/{session_id}/events"
        async with httpx.AsyncClient(timeout=300.0) as client:
            headers = dict(request.headers)
            headers.pop("host", None)

            response = await client.get(
                sse_url,
                headers=headers,
                params=request.query_params
            )
            
            return StreamingResponse(
                response.aiter_bytes(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": response.headers.get("Cache-Control", "no-cache"),
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                }
            )

    except Exception as e:
        logger.error(f"❌ SSE proxy error: {e}")
        raise HTTPException(status_code=500, detail="SSE proxy error")

@router.get("/configuration/admin/chat-sessions/{session_id}/events")
async def proxy_agent_sse(session_id: str, request: Request):
    """Proxy agent SSE connections to configuration service"""
    try:
        sse_url = f"{get_settings().configuration_service_url}/api/v1/configuration/admin/chat-sessions/{session_id}/events"
        async with httpx.AsyncClient(timeout=300.0) as client:
            headers = dict(request.headers)
            headers.pop("host", None)

            response = await client.get(
                sse_url,
                headers=headers,
                params=request.query_params
            )

            return StreamingResponse(
                response.aiter_bytes(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": response.headers.get("Cache-Control", "no-cache"),
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                }
            )

    except Exception as e:
        logger.error(f"SSE proxy error: {e}")
        raise HTTPException(status_code=500, detail="SSE proxy error")

# =================================
# CHAT PROXY ENDPOINTS
# =================================

@router.post("/chatbot/chat/stream")
async def chat_stream_proxy(request: Request):
    """Proxy chat stream requests to chatbot orchestration service"""
    try:
        import asyncio
        import httpx
        from ..core.config import get_settings
        
        # Set user data in request state for header forwarding
        request.state.user = {
            'uid': request.headers.get('X-User-UID', ''),
            'email': request.headers.get('X-User-Email', ''),
            'displayName': request.headers.get('X-User-Display-Name', ''),
            'photoURL': request.headers.get('X-User-Photo-URL', ''),
            'role': 'user'
        }
        
        # Get request body
        body = await request.body()
        
        # Retry logic for handling intermittent 502 errors
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # Prepare headers with user information
                    headers = {
                        "Content-Type": request.headers.get("content-type", "application/json"),
                        "Accept": request.headers.get("accept", "text/plain"),
                    }
                    
                    # Add user headers if user is authenticated
                    if request.state.user.get('uid'):
                        headers.update({
                            "X-User-UID": request.state.user['uid'],
                            "X-User-Email": request.state.user['email'],
                            "X-User-Display-Name": request.state.user['displayName'],
                            "X-User-Photo-URL": request.state.user['photoURL']
                        })
                    
                    response = await client.post(
                        f"{get_settings().chatbot_orchestration_url}/api/v1/chatbot/chat/stream",
                        content=body,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        from fastapi.responses import StreamingResponse
                        return StreamingResponse(
                            response.aiter_bytes(),
                            media_type=response.headers.get("content-type", "text/plain"),
                            headers={
                                "Cache-Control": "no-cache",
                                "Connection": "keep-alive",
                                "Access-Control-Allow-Origin": "*",
                                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                            }
                        )
                    elif response.status_code in [502, 503, 504] and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise HTTPException(status_code=response.status_code, detail=f"Chat service error: {response.text}")
                        
            except httpx.RequestError as req_err:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise
            except Exception:
                raise
                
    except Exception as e:
        logger.error(f"Chat stream endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat stream service error: {str(e)}")

@router.post("/chatbot/suggested-messages")
async def suggested_messages_endpoint(request: Request):
    """Route suggested messages requests to chatbot orchestration service."""
    try:
        import httpx
        from ..core.config import get_settings
        
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers}
        headers.pop('host', None)
        headers.pop('content-length', None)
        headers.pop('Content-Length', None)

        target_url = f"{get_settings().chatbot_orchestration_url}/api/v1/chatbot/suggested-messages"
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target_url,
                json=await request.json(),
                headers=headers,
                timeout=30.0
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get("content-type", "").startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing suggested messages request: {e}")
        raise HTTPException(status_code=500, detail=f"Suggested messages service error: {str(e)}")

@router.get("/chatbot/sessions")
async def list_sessions_endpoint(request: Request):
    """Route list sessions requests to chatbot orchestration service."""
    try:
        import httpx
        from ..core.config import get_settings
        
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}
        
        target_url = f"{get_settings().chatbot_orchestration_url}/api/v1/chatbot/sessions"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, headers=headers, timeout=10.0)
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Error routing list sessions request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")

@router.delete("/chatbot/sessions/{session_id}")
async def delete_session_endpoint(session_id: str, request: Request):
    """Route delete session requests to chatbot orchestration service."""
    try:
        import httpx
        from ..core.config import get_settings
        
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}
        
        target_url = f"{get_settings().chatbot_orchestration_url}/api/v1/chatbot/sessions/{session_id}"
        
        async with httpx.AsyncClient() as client:
            resp = await client.delete(target_url, headers=headers, timeout=10.0)
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Error routing delete session request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")
