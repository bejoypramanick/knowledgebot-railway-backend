import logging
import asyncio
import json
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..schemas.models import ScrapeRequest, ScrapeResponse
from ..core.sessions import active_scraping_sessions
from ..servcie.service_factory import ServiceFactory
from ..servcie.crawler import crawl_website
from ..servcie.ingestion import upload_scraped_content, record_scraped_metadata
from shared.utils import log_endpoint_request

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    log_endpoint_request("website_scraping", "health", request)
    return {"status": "healthy", "service": "website_scraping"}

@router.get("/scrape-progress/{session_id}")
async def scrape_progress(session_id: str):
    """SSE endpoint for real-time scraping progress updates"""

    async def event_generator():
        queue = active_scraping_sessions.get(session_id)
        if not queue:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get('type') in ['completed', 'error']:
                        if session_id in active_scraping_sessions:
                            del active_scraping_sessions[session_id]
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except Exception as e:
            logger.error(f"SSE error for session {session_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        }
    )

@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website_endpoint(request: ScrapeRequest):
    """Scrape a website and upload to Gemini FileSearch."""
    
    # Init SSE
    sse_queue = None
    if request.session_id:
        sse_queue = asyncio.Queue()
        active_scraping_sessions[request.session_id] = sse_queue
        await sse_queue.put({
            "type": "started",
            "message": f"Started scraping {request.url}",
            "url": request.url,
            "timestamp": asyncio.get_event_loop().time()
        })
        
    try:
        domain = urlparse(request.url).netloc.replace('www.', '')
        
        # Check existing
        from ..servcie.scraping_service import ScrapingService
        scraping_service = ScrapingService()
        existing = await scraping_service.get_existing_website(request.url, domain)
        version = 1
        
        if existing:
            if not request.replace_existing:
                raise HTTPException(409, detail={
                    "message": f"Website already scraped (Version {existing['version']})",
                    "existing_url": existing['original_url'],
                    "version": existing['version'],
                    "suggestion": "Set replace_existing=true to re-scrape"
                })
            else:
                version = existing['version'] + 1
                if existing['gemini_file_name']:
                    await scraping_service.delete_gemini_file(existing['gemini_file_name'])
                await scraping_service.delete_website_record(existing['id'])
                
        # Crawl
        content, scraped_urls = await crawl_website(request, sse_queue)
        
        # Upload
        result = await upload_scraped_content(content, request, sse_queue)
        uploaded_file = result['file']
        file_info = result['file_info']
        
        # Record
        await record_scraped_metadata(
            request, len(content), len(scraped_urls), 
            uploaded_file, file_info, scraped_urls, version
        )
        
        # Completion event
        if sse_queue:
            await sse_queue.put({
                "type": "completed",
                "message": "Scraping completed",
                "url": request.url, 
                "file_name": uploaded_file.name
            })
            
        return ScrapeResponse(
            success=True,
            message="Website scraped and uploaded successfully",
            file_name=uploaded_file.name,
            file_info=file_info,
            scraped_urls=scraped_urls
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scraping error: {e}")
        if sse_queue:
            await sse_queue.put({
                "type": "error",
                "message": str(e),
                "url": request.url
            })
        raise HTTPException(500, detail=str(e))
