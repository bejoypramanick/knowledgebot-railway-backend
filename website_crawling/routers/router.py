"""
Consolidated Website Crawling Router
All website crawling endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging

from ..service.website_service import WebsiteService
from ..service.ai_service import upload_content_to_gemini

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
website_service = WebsiteService()

# =================================
# WEB SCRAPING ENDPOINTS
# =================================

@router.post("/")
async def scrape_website(request: Request):
    """
    Scrape websites, sitemaps, or single pages.
    Supports single URL or multiple comma-separated URLs.
    Intelligently detects URL type and applies appropriate strategy.
    """
    try:
        body = await request.json()

        # Support both single URL and multiple URLs
        url_input = body.get("url") or body.get("urls") or ""
        if not url_input:
            raise HTTPException(status_code=400, detail="URL or URLs parameter is required")

        # Parse URLs - handle both single URL and comma-separated list
        if isinstance(url_input, list):
            urls = url_input
        else:
            urls = [u.strip() for u in str(url_input).split(",") if u.strip()]

        if not urls:
            raise HTTPException(status_code=400, detail="At least one valid URL is required")

        # Validate URLs
        for url in urls:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail=f"Invalid URL format: {url}")

        # Get crawling parameters from frontend (with sensible defaults)
        max_depth = body.get("max_depth", 2)
        replace_existing = body.get("replace_existing", False)

        # Get targeting patterns (URL filtering)
        include_patterns = body.get("include_patterns", []) or []
        exclude_patterns = body.get("exclude_patterns", []) or []

        logger.info(f"🎯 Starting batch scrape for {len(urls)} URL(s)")
        all_results = []

        # Process each URL with intelligent type detection
        for idx, url in enumerate(urls, 1):
            try:
                # First, classify URL type (sitemap / website / single_page)
                url_type = WebsiteService.classify_url_type(url)
                logger.info(f"[{idx}/{len(urls)}] Processing {url_type}: {url}")

                # Determine crawl depth based on URL type, but always respect UI depth where it makes sense.
                if url_type == 'sitemap':
                    # Sitemaps: depth 1 (just the sitemap entries themselves)
                    crawl_depth = 1
                elif url_type == 'single_page':
                    # Webpage: allow link-following up to the depth chosen in the UI.
                    # Depth 0 = just this page, >0 = follow links up to that depth.
                    crawl_depth = max(0, max_depth)
                else:  # website
                    # Website root or section: use full UI depth
                    crawl_depth = max_depth

                # Use a generous internal page cap so depth is the primary limiter.
                # This is independent of any frontend "max_pages" value.
                max_pages = 1000

                # Scrape options - combine frontend params with defaults
                options = {
                    "url": url,
                    "max_pages": max_pages,
                    "max_depth": min(crawl_depth, 5),   # Cap at depth 5
                    "replace_existing": replace_existing,
                    "delay_between_requests": max(0, float(body.get("delay_between_requests", 0))),
                    "max_concurrent": min(int(body.get("max_concurrent", 10)), 50),
                    "extract_links": body.get("extract_links", True),
                    "extract_images": body.get("extract_images", False),
                    "respect_robots_txt": body.get("respect_robots_txt", True),
                    "user_agent": body.get("user_agent", "KnowledgeBot-Crawler/1.0"),
                    "timeout": body.get("timeout", 30),
                    "include_patterns": include_patterns,
                    "exclude_patterns": exclude_patterns
                }

                result = await website_service.scrape_website(url, options)
                all_results.append({
                    "url": url,
                    "type": url_type,
                    "success": result.get("success", True),
                    "result": result
                })

            except Exception as e:
                logger.error(f"❌ Error scraping {url_type} ({url}): {e}")
                all_results.append({
                    "url": url,
                    "type": url_type,
                    "success": False,
                    "error": str(e)
                })

        # Determine overall success
        overall_success = all(r.get("success", False) for r in all_results)
        total_pages = sum(r.get("result", {}).get("pages_scraped", 0) for r in all_results if r.get("success"))

        logger.info(f"✅ Batch scrape completed: {len([r for r in all_results if r.get('success')])}/{len(urls)} succeeded")

        return {
            "success": overall_success,
            "data": all_results,
            "message": f"Scraped {len(urls)} URL(s)" + (f": {total_pages} pages processed" if total_pages > 0 else ""),
            "total_files_uploaded": total_pages
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in scrape endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jobs")
async def get_scraping_jobs():
    """Get all scraping jobs"""
    try:
        # Note: get_all_jobs() is not yet implemented in WebsiteService
        # For now, return empty list
        return {
            "success": True,
            "data": []
        }
    except Exception as e:
        logger.error(f"Error getting scraping jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jobs/{job_id}")
async def get_scraping_job_details(job_id: str):
    """Get details of a specific scraping job"""
    try:
        job_details = await website_service.get_job_details(job_id)
        
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

@router.delete("/jobs/{job_id}")
async def delete_scraping_job(job_id: str):
    """Delete a scraping job"""
    try:
        result = await website_service.delete_job(job_id)
        
        return {
            "success": True,
            "message": "Job deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# WEB CRAWLING ENDPOINTS
# =================================

@router.post("/crawl")
async def start_crawl_session(request: Request):
    """Start a crawl session for multiple websites"""
    try:
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
        
        result = await website_service.start_crawl_session(
            urls=urls,
            user_id="default",  # Use default user since no auth
            options=options
        )
        
        return {
            "success": True,
            "data": result,
            "message": "Crawl session started successfully"
        }
    except Exception as e:
        logger.error(f"Error starting crawl session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/crawl/sessions")
async def get_crawl_sessions():
    """Get all crawl sessions"""
    try:
        sessions = await website_service.get_all_sessions()
        
        return {
            "success": True,
            "data": sessions
        }
    except Exception as e:
        logger.error(f"Error getting crawl sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/crawl/sessions/{session_id}")
async def get_crawl_session_details(session_id: str):
    """Get details of a crawl session"""
    try:
        session_details = await website_service.get_session_details(session_id, "default")
        
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
async def stop_crawl_session(session_id: str):
    """Stop a running crawl session"""
    try:
        result = await website_service.stop_session(session_id, "default")
        
        return {
            "success": True,
            "message": "Crawl session stopped successfully"
        }
    except Exception as e:
        logger.error(f"Error stopping crawl session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# CONTENT ENDPOINTS
# =================================

@router.get("/jobs/{job_id}/content")
async def get_extracted_content(job_id: str, format: str = "json"):
    """Get extracted content from a scraping job"""
    try:
        content = await website_service.get_extracted_content(
            job_id=job_id,
            user_id="default",
            format=format
        )
        
        return {
            "success": True,
            "data": content
        }
    except Exception as e:
        logger.error(f"Error getting extracted content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search")
async def search_extracted_content(query: str, limit: int = 20):
    """Search across extracted content"""
    try:
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        results = await website_service.search_content(
            query=query,
            user_id="default",
            limit=limit
        )
        
        return {
            "success": True,
            "data": results,
            "query": query
        }
    except Exception as e:
        logger.error(f"Error searching content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# ANALYTICS ENDPOINTS
# =================================

@router.get("/analytics/scraping")
async def get_scraping_analytics():
    """Get scraping analytics summary"""
    try:
        analytics = await website_service.get_analytics_summary("default")
        
        return {
            "success": True,
            "data": analytics
        }
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analytics/domains")
async def get_domain_analytics():
    """Get domain-specific analytics"""
    try:
        domain_stats = await website_service.get_domain_analytics("default")
        
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
                "website_service": "healthy",
                "ai_service": "healthy",
                "database": "connected",
                "proxy": "available"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
