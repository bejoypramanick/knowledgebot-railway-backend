from typing import Optional

import httpx
from fastapi import (APIRouter, File, Form, Header, HTTPException, Request,
                     UploadFile)
from fastapi.responses import JSONResponse

from api_gateway.core.config import KNOWLEDGEBASE_INGESTION_URL
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

router = APIRouter()

@router.options("/upload")
async def knowledgebase_upload_options():
    """Handle CORS preflight requests for file uploads."""
    return JSONResponse(
        status_code=200,
        content={"message": "CORS preflight OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-User-Email",
            "Access-Control-Allow-Credentials": "true"
        }
    )

@router.post("/upload")
async def knowledgebase_upload_endpoint(
    request: Request,
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
    replace_existing: bool = Form(False),
    user_email: Optional[str] = Header(None, alias="X-User-Email")
):
    """Route knowledgebase upload requests to knowledgebase ingestion service."""
    file_content = None
    try:
        logger.info(f"📁 Received file upload request: {file.filename}, size: {file.size if hasattr(file, 'size') else 'unknown'}")

        # Read the file content asynchronously
        file_content = await file.read()

        files = {
            'file': (
                file.filename or 'uploaded_file',
                file_content,
                file.content_type or 'application/octet-stream'
            )
        }

        data = {}
        if display_name:
            data['display_name'] = display_name
        
        data['replace_existing'] = str(replace_existing).lower()

        headers = {}
        if user_email:
            headers['X-User-Email'] = user_email

        request_headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers.update({k: v for k, v in request_headers.items()
                       if k.lower() not in hop_by_hop_headers and k.lower() not in ['content-type', 'content-length', 'host']})

        target_url = f"{KNOWLEDGEBASE_INGESTION_URL}/upload"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(
                target_url,
                files=files,
                data=data,
                headers=headers
            )

            # Parse response content
            try:
                response_content = resp.json()
            except Exception:
                response_content = {"detail": resp.text}

            return JSONResponse(
                status_code=resp.status_code,
                content=response_content
            )

    except httpx.TimeoutException as te:
        logger.error(f"⏰ Upload request timed out: {te}")
        raise HTTPException(
            status_code=504,
            detail=f"Upload request timed out: {str(te)}"
        )
    except Exception as e:
        logger.error(f"❌ Error routing knowledgebase upload request: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Knowledgebase service error: {str(e)}"
        )
    finally:
        if file_content:
            del file_content

@router.get("/upload/constraints")
async def knowledgebase_upload_constraints_endpoint(request: Request):
    """Route upload constraints requests to knowledgebase ingestion service."""
    try:
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/upload/constraints"

        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Knowledgebase service unavailable for constraints: {e}")
        raise HTTPException(status_code=503, detail="Knowledgebase service temporarily unavailable")


@router.get("/files")
async def knowledgebase_files_endpoint(request: Request):
    """Route knowledgebase files list requests to knowledgebase ingestion service."""
    try:
        query_params = str(request.url.query)
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files"
        if query_params:
            url += f"?{query_params}"

        logger.info(f"📁 Routing to knowledgebase service: {url}")

        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30.0)
            
            logger.info(f"📁 Knowledgebase service response: {resp.status_code}")
            
            if resp.status_code == 404:
                logger.error(f"❌ Knowledgebase service not found at: {KNOWLEDGEBASE_INGESTION_URL}")
                return JSONResponse(
                    status_code=503,
                    content={"error": "Knowledgebase service unavailable", "service_url": KNOWLEDGEBASE_INGESTION_URL}
                )
            
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing knowledgebase files request: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")


@router.get("/files/metadata")
async def knowledgebase_files_metadata_endpoint(
    request: Request,
    include_signed_urls: bool = False,
    signed_url_expiration: int = 3600
):
    """Route knowledgebase files metadata requests to knowledgebase ingestion service."""
    try:
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files/metadata"
        query_params = []
        if include_signed_urls:
            query_params.append(f"include_signed_urls=true")
        if signed_url_expiration != 3600:
            query_params.append(f"signed_url_expiration={signed_url_expiration}")

        if query_params:
            url += "?" + "&".join(query_params)

        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30.0)
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing knowledgebase files metadata request: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")


@router.delete("/files/{file_name:path}")
async def knowledgebase_file_delete_endpoint(
    file_name: str,
    request: Request
):
    """Route file deletion requests to knowledgebase ingestion service."""
    try:
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files/{file_name}"

        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30.0)
            
            response_content = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {"detail": resp.text}
            
            return JSONResponse(
                status_code=resp.status_code,
                content=response_content
            )
    except Exception as e:
        logger.error(f"Error routing delete request for file {file_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")
