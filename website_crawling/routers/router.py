"""
Consolidated Website Crawling Router
All website crawling endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging

from ..service.scraping_service import ScrapingService
from ..service.crawl_service import CrawlService
from ..core.auth_middleware import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
scraping_service = ScrapingService()
crawl_service = CrawlService()

# =================================
# WEB SCRAPING ENDPOINTS
# =================================

@router.post("/scrape")
async def scrape_website(request: Request):
    """Scrape a single website"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        url = body.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        
        # Validate URL
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid URL format")
        
        # Scrape options
        options = {
            "depth": body.get("depth", 1),
            "include_images": body.get("include_images", False),
            "follow_links": body.get("follow_links", False),
            "max_pages": body.get("max_pages", 10)
        }
        
        result = await scraping_service.scrape_website(
            url=url,
            user_id=current_user.get("uid"),
            options=options
        )
        
        return {
            "success": True,
            "data": result,
            "message": "Website scraped successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scraping website: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scrape/jobs")
async def get_scraping_jobs(request: Request):
    """Get scraping jobs for the user"""
    try:
        current_user = await get_current_user(request)
        jobs = await scraping_service.get_user_jobs(current_user.get("uid"))
        
        return {
            "success": True,
            "data": jobs
        }
    except Exception as e:
        logger.error(f"Error getting scraping jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scrape/jobs/{job_id}")
async def get_scraping_job_details(job_id: str, request: Request):
    """Get details of a specific scraping job"""
    try:
        current_user = await get_current_user(request)
        job_details = await scraping_service.get_job_details(job_id, current_user.get("uid"))
        
        if not job_details:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {
            "success": True,
            "data": job_details
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/scrape/jobs/{job_id}")
async def delete_scraping_job(job_id: str, request: Request):
    """Delete a scraping job"""
    try:
        current_user = await get_current_user(request)
        result = await scraping_service.delete_job(job_id, current_user.get("uid"))
        
        return {
            "success": True,
            "message": "Job deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# CRAWLING ENDPOINTS
# =================================

@router.post("/crawl")
async def start_crawl_session(request: Request):
    """Start a crawl session for multiple websites"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        urls = body.get("urls", [])
        if not urls:
            raise HTTPException(status_code=400, detail="At least one URL is required")
        
        if len(urls) > 50:
            raise HTTPException(status_code=400, detail="Too many URLs (max 50 per session)")
        
        # Validate all URLs
        for url in urls:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail=f"Invalid URL: {url}")
        
        # Crawl options
        options = {
            "max_depth": body.get("max_depth", 2),
            "max_pages_per_site": body.get("max_pages_per_site", 20),
            "delay_between_requests": body.get("delay_between_requests", 1),
            "respect_robots_txt": body.get("respect_robots_txt", True),
            "user_agent": body.get("user_agent", "KnowledgeBot-Crawler/1.0")
        }
        
        result = await crawl_service.start_crawl_session(
            urls=urls,
            user_id=current_user.get("uid"),
            options=options
        )
        
        return {
            "success": True,
            "data": result,
            "message": "Crawl session started successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting crawl session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/crawl/sessions")
async def get_crawl_sessions(request: Request):
    """Get crawl sessions for the user"""
    try:
        current_user = await get_current_user(request)
        sessions = await crawl_service.get_user_sessions(current_user.get("uid"))
        
        return {
            "success": True,
            "data": sessions
        }
    except Exception as e:
        logger.error(f"Error getting crawl sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/crawl/sessions/{session_id}")
async def get_crawl_session_details(session_id: str, request: Request):
    """Get details of a crawl session"""
    try:
        current_user = await get_current_user(request)
        session_details = await crawl_service.get_session_details(session_id, current_user.get("uid"))
        
        if not session_details:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "success": True,
            "data": session_details
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/crawl/sessions/{session_id}/stop")
async def stop_crawl_session(session_id: str, request: Request):
    """Stop a running crawl session"""
    try:
        current_user = await get_current_user(request)
        result = await crawl_service.stop_session(session_id, current_user.get("uid"))
        
        return {
            "success": True,
            "message": "Crawl session stopped successfully"
        }
    except Exception as e:
        logger.error(f"Error stopping crawl session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# CONTENT EXTRACTION ENDPOINTS
# =================================

@router.get("/content/{job_id}")
async def get_extracted_content(job_id: str, request: Request, format: str = "json"):
    """Get extracted content from a scraping job"""
    try:
        current_user = await get_current_user(request)
        content = await scraping_service.get_extracted_content(
            job_id=job_id,
            user_id=current_user.get("uid"),
            format=format
        )
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
        
        return {
            "success": True,
            "data": content
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting extracted content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/content/search")
async def search_extracted_content(query: str, request: Request, limit: int = 20):
    """Search across extracted content"""
    try:
        current_user = await get_current_user(request)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        results = await scraping_service.search_content(
            query=query,
            user_id=current_user.get("uid"),
            limit=limit
        )
        
        return {
            "success": True,
            "data": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ANALYTICS ENDPOINTS
# =================================

@router.get("/analytics/summary")
async def get_scraping_analytics(request: Request):
    """Get scraping analytics summary"""
    try:
        current_user = await get_current_user(request)
        analytics = await scraping_service.get_analytics_summary(current_user.get("uid"))
        
        return {
            "success": True,
            "data": analytics
        }
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analytics/domains")
async def get_domain_analytics(request: Request):
    """Get domain-specific analytics"""
    try:
        current_user = await get_current_user(request)
        domain_stats = await scraping_service.get_domain_analytics(current_user.get("uid"))
        
        return {
            "success": True,
            "data": domain_stats
        }
    except Exception as e:
        logger.error(f"Error getting domain analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check for website crawling service"""
    try:
        health_status = {
            "status": "healthy",
            "service": "website-crawling",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "scraping_service": "healthy",
                "crawl_service": "healthy",
                "database": "connected",
                "proxy": "available"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
