from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import logging

from api_gateway.core.config import WEBSITE_CRAWLING_URL
from api_gateway.schemas.models import ScrapeRequest

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/scrape")
async def scrape_endpoint(scrape_request: ScrapeRequest, request: Request):
    """Route scraping requests to website scraping service."""
    try:
        headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{WEBSITE_CRAWLING_URL}/scrape",
                json=scrape_request.model_dump(),
                headers=headers,
                timeout=60.0
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing scrape request: {e}")
        raise HTTPException(status_code=500, detail=f"Scraping service error: {str(e)}")
