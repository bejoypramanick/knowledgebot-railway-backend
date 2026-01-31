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
# END OF ROUTER - Only generic proxy and auth handling
# =================================
