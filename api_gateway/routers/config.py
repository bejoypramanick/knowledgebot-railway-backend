import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from api_gateway.core.config import CONFIGURATION_SERVICE_URL
from api_gateway.core.auth_middleware import get_current_user
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

router = APIRouter()

# Personas API endpoints - proxy to configuration service
@router.api_route("/personas/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_personas_routes(request: Request, path: str):
    """Proxy personas API requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/personas/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying personas route to configuration service: {e}")
        raise HTTPException(status_code=503, detail="Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in personas proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# Configuration API endpoints - proxy to configuration service
@router.get("/configuration/chatbot")
@router.post("/configuration/chatbot")
async def proxy_chatbot_config(request: Request):
    """Proxy chatbot configuration requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/configuration/chatbot"
            
            body = None
            if method == "POST":
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in configuration proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

    except httpx.RequestError as e:
        logger.error(f"Error proxying to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in configuration proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Chat API endpoints - proxy to configuration service (for human agent requests)
@router.api_route("/chat/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_chat_routes(request: Request, path: str):
    """Proxy chat API requests to configuration service (request-human-agent, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/chat/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json() if "application/json" in response.headers.get("content-type", "") else response.text,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying chat routes to configuration service: {e}")
        raise HTTPException(status_code=503, detail="Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in chat proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Admin API endpoints - proxy to configuration service
@router.api_route("/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_admin_routes(request: Request, path: str):
    """Proxy admin API requests to configuration service (token-usage, human-agents, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/admin/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying admin route to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in admin proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Auth API endpoints - proxy to configuration service
@router.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_auth_routes(request: Request, path: str):
    """Proxy auth API requests to configuration service (verify-token, sync-user, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/auth/{path}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying auth route to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in auth proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Human Agents API endpoints - proxy to configuration service
@router.api_route("/human-agents/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_human_agents_routes(request: Request, path: str):
    """Proxy human agents API requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/human-agents/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=dict(request.headers)
            )
            
            return JSONResponse(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying human agents route to configuration service: {e}")
        raise HTTPException(status_code=503, detail="Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in human agents proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Users API endpoints - proxy to configuration service
@router.api_route("/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_users_routes(request: Request, path: str, user: dict = Depends(get_current_user)):
    """Proxy users API requests to configuration service (unique-id, etc.)"""
    try:
        # Set user data in request state for header forwarding
        request.state.user = user
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/users/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying users route to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in users proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


def add_user_headers_to_request(request: Request, headers: dict) -> dict:
    """Add user information headers to downstream service requests"""
    try:
        # Check if user is authenticated (user data set by auth middleware)
        if hasattr(request.state, 'user') and request.state.user:
            user_data = request.state.user
            headers.update({
                'X-User-UID': user_data.get('uid', ''),
                'X-User-Email': user_data.get('email', ''),
                'X-User-Display-Name': user_data.get('displayName', ''),
                'X-User-Photo-URL': user_data.get('photoURL', ''),
                'X-User-Roles': ','.join(user_data.get('roles', [])),
                'X-User-Role': user_data.get('roles', ['user'])[0]  # Primary role
            })
    except Exception as e:
        logger.error(f"Error adding user headers: {e}")
    
    return headers

# Widget API endpoints - proxy to configuration service
@router.api_route("/widget/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_widget_routes(request: Request, path: str):
    """Proxy widget API requests to configuration service (embed-script, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/widget/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying widget route to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in widget proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Feedback API endpoints - proxy to configuration service
@router.post("/feedback/submit")
async def proxy_feedback_submit(request: Request):
    """Proxy feedback submission to configuration service - frontend endpoint"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Route to the backend endpoint
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/feedback"
            
            body = await request.body()
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.post(
                url=url,
                content=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json() if "application/json" in response.headers.get("content-type", "") else response.text,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying feedback to configuration service: {e}")
        raise HTTPException(status_code=503, detail="Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in feedback proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# Notifications API endpoints - proxy to configuration service
@router.api_route("/notifications/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_notifications_routes(request: Request, path: str):
    """Proxy notifications API requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/notifications/{path}"
            
            query_string = str(request.url.query)
            if query_string:
                url += f"?{query_string}"
            
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            # Add user headers if user is authenticated
            headers = add_user_headers_to_request(request, headers)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            if "application/json" in response.headers.get("content-type", ""):
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            else:
                return JSONResponse(
                    content=response.text,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying notifications route to configuration service: {e}")
        raise HTTPException(status_code=503, detail="Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in notifications proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
