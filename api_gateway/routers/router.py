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
        elif backend_path.startswith("webcrawl/"):
            service_url = get_settings().website_crawling_url
            logger.info(f"✅ Routing to webcrawl service: {service_url}")
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"🔍 About to make HTTP request to: {full_url}")
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
    except Exception as e:
        logger.error(f"❌ Proxy error for path '{path}': {e}")
        logger.error(f"❌ Full URL: {full_url}")
        logger.error(f"❌ Service URL: {service_url}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

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
