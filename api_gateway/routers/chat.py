import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_gateway.core.config import CHATBOT_ORCHESTRATION_URL
from api_gateway.routers.config import add_user_headers_to_request
from api_gateway.schemas.models import (DeleteSessionResponse,
                                        ListSessionsResponse,
                                        SuggestedMessagesRequest,
                                        SuggestedMessagesResponse)
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream_endpoint(request: Request):
    """Route streaming chat requests to chatbot orchestration service."""
    try:
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
                    headers = add_user_headers_to_request(request, headers)
                    
                    response = await client.post(
                        f"{CHATBOT_ORCHESTRATION_URL}/chat/stream",
                        content=body,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
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



@router.post("/api/v1/suggested-messages", response_model=SuggestedMessagesResponse)
async def suggested_messages_endpoint(suggested_request: SuggestedMessagesRequest, request: Request):
    """Route suggested messages requests to chatbot orchestration service."""
    try:
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers}
        headers.pop('host', None)
        headers.pop('Host', None)
        headers.pop('content-length', None)
        headers.pop('Content-Length', None)

        target_url = f"{CHATBOT_ORCHESTRATION_URL}/suggested-messages"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target_url,
                json=suggested_request.model_dump(),
                headers=headers,
                timeout=30.0
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing suggested messages request: {e}")
        raise HTTPException(status_code=500, detail=f"Suggested messages service error: {str(e)}")


@router.get("/api/v1/sessions", response_model=ListSessionsResponse)
async def list_sessions_endpoint(request: Request):
    """Route list sessions requests to chatbot orchestration service."""
    try:
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}
        
        target_url = f"{CHATBOT_ORCHESTRATION_URL}/sessions"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, headers=headers, timeout=10.0)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Error routing list sessions request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")


@router.delete("/api/v1/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session_endpoint(session_id: str, request: Request):
    """Route delete session requests to chatbot orchestration service."""
    try:
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}
        
        target_url = f"{CHATBOT_ORCHESTRATION_URL}/sessions/{session_id}"
        
        async with httpx.AsyncClient() as client:
            resp = await client.delete(target_url, headers=headers, timeout=10.0)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Error routing delete session request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")
