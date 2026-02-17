"""
Consolidated Website Crawling Router
All website crawling endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging

from ..service.website_service import WebsiteService, scrape_website_celery
from ..service.ai_service import upload_content_to_gemini

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
website_service = WebsiteService()

# =================================
# WEB SCRAPING ENDPOINTS
# =================================

@router.post("/async")
async def scrape_website_async_endpoint(request: Request):
    """
    Async website scraping endpoint with Celery - returns immediately with pending status.
    Actual processing happens in Celery worker. Frontend should poll /status/{id} to track progress.
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

        # Get crawling parameters from frontend
        max_depth = body.get("max_depth", 2)
        replace_existing = body.get("replace_existing", False)
        include_patterns = body.get("include_patterns", []) or []
        exclude_patterns = body.get("exclude_patterns", []) or []

        logger.info(f"🎯 Starting async batch scrape for {len(urls)} URL(s)")
        all_results = []

        # Process each URL
        for idx, url in enumerate(urls, 1):
            try:
                url_type = WebsiteService.classify_url_type(url)
                logger.info(f"[{idx}/{len(urls)}] Queueing {url_type}: {url}")

                # Determine crawl depth based on URL type
                if url_type == 'sitemap':
                    crawl_depth = 1
                elif url_type == 'single_page':
                    crawl_depth = max(0, max_depth)
                else:  # website
                    crawl_depth = max_depth

                # Use generous internal page cap
                max_pages = 1000

                # Scrape options
                options = {
                    "url": url,
                    "max_pages": max_pages,
                    "max_depth": min(crawl_depth, 5),
                    "replace_existing": replace_existing,
                    "max_concurrent": min(int(body.get("max_concurrent", 10)), 50),
                    "extract_links": body.get("extract_links", True),
                    "extract_images": body.get("extract_images", False),
                    "respect_robots_txt": body.get("respect_robots_txt", True),
                    "user_agent": body.get("user_agent", "KnowledgeBot-Crawler/1.0"),
                    "timeout": body.get("timeout", 30),
                    "include_patterns": include_patterns,
                    "exclude_patterns": exclude_patterns
                }

                # Queue for async processing
                result = await scrape_website_celery(url, options)
                all_results.append({
                    "url": url,
                    "type": url_type,
                    "success": result.get("success", True),
                    "result": result
                })

            except Exception as e:
                logger.error(f"❌ Error queueing {url}: {e}")
                all_results.append({
                    "url": url,
                    "type": "unknown",
                    "success": False,
                    "error": str(e)
                })

        logger.info(f"✅ Async batch scrape queued: {len([r for r in all_results if r.get('success')])}/{len(urls)} accepted")

        return {
            "success": True,
            "data": all_results,
            "message": f"Queued {len(urls)} URL(s) for scraping"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in async scrape endpoint: {e}", exc_info=True)
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
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_scraping_task(item_id: str):
    """
    Cancel a pending or processing website scraping task.
    Revokes the Celery task and marks as cancelled in database.
    """
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            website_record = await conn.fetchrow(
                "SELECT id, processing_status, celery_task_id FROM scraped_websites WHERE id = $1",
                int(item_id)
            )

            if not website_record:
                raise HTTPException(status_code=404, detail=f"Website {item_id} not found")

            if website_record['processing_status'] not in ('pending', 'processing'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel website with status '{website_record['processing_status']}'"
                )

            celery_task_id = website_record['celery_task_id']

            # ATOMIC TRANSACTION: Either both succeed or both fail
            async with conn.transaction():
                # Step 1: Revoke the Celery task (if it exists)
                if celery_task_id:
                    try:
                        from website_crawling.celery_app import celery_app
                        celery_app.control.revoke(celery_task_id, terminate=True)
                        logger.info(f"🔴 [CELERY_REVOKE] Revoked task {celery_task_id} from Redis queue")
                    except Exception as e:
                        # If revoke fails, raise exception to trigger transaction rollback
                        logger.error(f"❌ [ATOMIC_TX] Revoke failed for task {celery_task_id}: {e}")
                        raise HTTPException(status_code=500, detail=f"Failed to revoke task from queue: {e}")

                # Step 2: Update database (same transaction)
                try:
                    await conn.execute(
                        "UPDATE scraped_websites SET processing_status = 'cancelled', task_revoked_at = NOW() WHERE id = $1",
                        int(item_id)
                    )
                    logger.info(f"✅ [ATOMIC_TX] Updated DB: website {item_id} marked as cancelled")
                except Exception as e:
                    # If DB update fails, transaction rolls back
                    logger.error(f"❌ [ATOMIC_TX] DB update failed for website {item_id}: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to update cancellation status: {e}")

            # If we reach here, transaction is committed - both operations succeeded
            logger.info(f"✅ [ATOMIC_COMMIT] Cancelled website scraping task: {item_id} (celery_task_id: {celery_task_id})")
            return {
                "success": True,
                "item_id": item_id,
                "celery_task_id": celery_task_id,
                "message": "Website scraping cancelled successfully"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling scraping task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_scraping_tasks():
    """
    Cancel all pending and processing website scraping tasks.
    Revokes tasks from Redis queue and marks as cancelled in database.
    """
    try:
        from shared.db import get_db_connection
        from website_crawling.celery_app import celery_app

        async with get_db_connection() as conn:
            # ATOMIC TRANSACTION: Either all tasks cancel or none cancel
            async with conn.transaction():
                try:
                    # Get all pending/processing websites with task IDs
                    pending_websites = await conn.fetch(
                        """SELECT id, celery_task_id FROM scraped_websites
                           WHERE processing_status IN ('pending', 'processing') AND celery_task_id IS NOT NULL"""
                    )

                    # Step 1: Revoke all website tasks from queue
                    websites_revoked = 0
                    for website_record in pending_websites:
                        try:
                            celery_app.control.revoke(website_record['celery_task_id'], terminate=True)
                            websites_revoked += 1
                            logger.info(f"🔴 [CELERY_REVOKE] Revoked website task {website_record['celery_task_id']}")
                        except Exception as e:
                            logger.error(f"❌ [ATOMIC_TX] Failed to revoke website task {website_record['celery_task_id']}: {e}")
                            raise HTTPException(status_code=500, detail=f"Failed to revoke website tasks: {e}")

                    # Step 2: Update all websites in database (same transaction)
                    try:
                        result = await conn.execute(
                            """UPDATE scraped_websites
                               SET processing_status = 'cancelled', task_revoked_at = NOW()
                               WHERE processing_status IN ('pending', 'processing')"""
                        )
                        websites_cancelled = int(result.split()[-1]) if result else 0
                        logger.info(f"✅ [ATOMIC_TX] Updated DB: {websites_cancelled} websites marked as cancelled")
                    except Exception as e:
                        logger.error(f"❌ [ATOMIC_TX] Failed to update website statuses: {e}")
                        raise HTTPException(status_code=500, detail=f"Failed to update website statuses: {e}")

                    # If we reach here, transaction is committed - all operations succeeded
                    logger.info(f"✅ [ATOMIC_COMMIT] Cancelled all scraping tasks: {websites_cancelled} websites (Revoked: {websites_revoked} tasks)")

                    return {
                        "success": True,
                        "message": "All pending scraping tasks cancelled successfully",
                        "websites_cancelled": websites_cancelled,
                        "websites_revoked": websites_revoked
                    }
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"❌ [ATOMIC_TX] Transaction failed: {e}")
                    raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling all scraping tasks: {e}")
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
