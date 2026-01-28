from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import logging

from api_gateway.core.config import CONFIGURATION_SERVICE_URL

logger = logging.getLogger(__name__)

router = APIRouter()

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

@router.get("/configuration/widget")
@router.post("/configuration/widget")
async def proxy_widget_config(request: Request):
    """Proxy widget configuration requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/configuration/widget"
            
            body = None
            if method == "POST":
                body = await request.body()
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
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
        logger.error(f"Error proxying chat route to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
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

# Users API endpoints - proxy to configuration service
@router.api_route("/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_users_routes(request: Request, path: str):
    """Proxy users API requests to configuration service (unique-id, etc.)"""
    try:
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
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in notifications proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Feedback API endpoints - proxy to configuration service
@router.post("/feedback")
@router.post("/feedback/submit")
async def proxy_feedback_submit(request: Request):
    """Proxy feedback submission to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Note: Both /feedback and /feedback/submit hit the same backend endpoint /api/v1/feedback
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/feedback"
            
            body = await request.body()
            headers = dict(request.headers)
            headers.pop("host", None)
            
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
    except Exception as e:
        logger.error(f"Error proxying feedback to configuration service: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Public Chat handoff - proxy to configuration service
@router.post("/request-human-agent")
async def proxy_request_human_agent(request: Request):
    """Proxy human agent request from widget to configuration service"""
    try:
        data = await request.json()
        session_id = data.get('session_id')
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
            
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Proxies to public_chat_router: /api/v1/chat/{session_id}/request-human-agent
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/chat/{session_id}/request-human-agent"
            
            headers = dict(request.headers)
            headers.pop("host", None)
            
            response = await client.post(
                url=url,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json() if "application/json" in response.headers.get("content-type", "") else response.text,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except Exception as e:
        logger.error(f"Error proxying human agent request: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
