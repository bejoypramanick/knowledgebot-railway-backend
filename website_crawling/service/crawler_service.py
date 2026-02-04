"""
Website Crawling Service Layer for Website Crawling
Provides business logic for web crawling operations with session management
"""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from website_crawling.core.otel_logger import get_otel_logger
from website_crawling.service.scraping_service import ScrapingService

logger = get_otel_logger("crawler_service", "website-crawling")

# In-memory session storage (in production, use Redis or database)
_active_sessions: Dict[str, Dict[str, Any]] = {}


class CrawlerService:
    """Service layer for website crawling with session management"""

    def __init__(self):
        self.scraping_service = ScrapingService()

    async def start_crawl_session(
        self, urls: List[str], user_id: str, options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a crawl session for multiple URLs.

        Args:
            urls: List of URLs to crawl
            user_id: User ID for tracking
            options: Crawling options (max_depth, max_pages_per_site, etc.)

        Returns:
            Dict with session details
        """
        try:
            session_id = str(uuid.uuid4())

            session_data = {
                "session_id": session_id,
                "user_id": user_id,
                "urls": urls,
                "options": options,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
                "total_urls": len(urls),
                "completed_urls": 0,
                "failed_urls": 0,
                "results": [],
                "errors": []
            }

            _active_sessions[session_id] = session_data

            logger.info(f"🚀 Starting crawl session {session_id} for {len(urls)} URLs")

            # Start background task to process URLs
            asyncio.create_task(self._process_crawl_session(session_id))

            return {
                "success": True,
                "session_id": session_id,
                "message": "Crawl session started successfully",
                "total_urls": len(urls),
                "status": "running"
            }

        except Exception as e:
            logger.error(f"Error starting crawl session: {e}")
            raise

    async def _process_crawl_session(self, session_id: str):
        """Background task to process all URLs in a crawl session."""
        session = _active_sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return

        urls = session["urls"]
        options = session["options"]

        max_pages_per_site = options.get("max_pages_per_site", 20)
        max_depth = options.get("max_depth", 2)
        delay_between_requests = options.get("delay_between_requests", 1)

        logger.info(f"📋 Processing {len(urls)} URLs for session {session_id}")

        for i, url in enumerate(urls):
            # Check if session was stopped
            current_session = _active_sessions.get(session_id)
            if not current_session or current_session.get("status") == "stopped":
                logger.info(f"⏹️ Session {session_id} was stopped")
                break

            logger.info(f"🔄 Processing URL {i+1}/{len(urls)}: {url}")

            try:
                # Scrape the website
                scrape_options = {
                    "max_pages": max_pages_per_site,
                    "max_depth": max_depth,
                    "replace_existing": False,
                    "timeout": 30,
                    "user_email": session.get("user_id")
                }

                result = await self.scraping_service.scrape_website(url, scrape_options)

                if result.get("success"):
                    session["completed_urls"] += 1
                    session["results"].append({
                        "url": url,
                        "status": "success",
                        "pages_scraped": result.get("pages_scraped", 0),
                        "job_id": result.get("job_id"),
                        "record_id": result.get("record_id")
                    })
                    logger.info(f"✅ Successfully scraped {url}")
                else:
                    session["failed_urls"] += 1
                    session["errors"].append({
                        "url": url,
                        "error": result.get("error", "Unknown error")
                    })
                    logger.warning(f"⚠️ Failed to scrape {url}: {result.get('error')}")

            except Exception as e:
                session["failed_urls"] += 1
                session["errors"].append({
                    "url": url,
                    "error": str(e)
                })
                logger.error(f"❌ Error scraping {url}: {e}")

            # Update session
            _active_sessions[session_id] = session

            # Delay between requests to be respectful
            if i < len(urls) - 1:
                await asyncio.sleep(delay_between_requests)

        # Mark session as completed
        session["status"] = "completed"
        session["completed_at"] = datetime.utcnow().isoformat()
        _active_sessions[session_id] = session

        logger.info(f"🏁 Session {session_id} completed: {session['completed_urls']} successful, {session['failed_urls']} failed")

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all crawl sessions."""
        try:
            sessions = []
            for session_id, session_data in _active_sessions.items():
                sessions.append({
                    "session_id": session_id,
                    "user_id": session_data.get("user_id"),
                    "status": session_data.get("status"),
                    "total_urls": session_data.get("total_urls", 0),
                    "completed_urls": session_data.get("completed_urls", 0),
                    "failed_urls": session_data.get("failed_urls", 0),
                    "started_at": session_data.get("started_at"),
                    "completed_at": session_data.get("completed_at")
                })

            # Sort by started_at (most recent first)
            sessions.sort(key=lambda x: x.get("started_at", ""), reverse=True)

            return sessions

        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []

    async def get_session_details(
        self, session_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get details of a crawl session."""
        try:
            session = _active_sessions.get(session_id)
            if not session:
                logger.warning(f"Session {session_id} not found")
                return None

            return {
                "session_id": session_id,
                "user_id": session.get("user_id"),
                "urls": session.get("urls", []),
                "status": session.get("status"),
                "total_urls": session.get("total_urls", 0),
                "completed_urls": session.get("completed_urls", 0),
                "failed_urls": session.get("failed_urls", 0),
                "started_at": session.get("started_at"),
                "completed_at": session.get("completed_at"),
                "results": session.get("results", []),
                "errors": session.get("errors", []),
                "options": session.get("options", {})
            }

        except Exception as e:
            logger.error(f"Error getting session details: {e}")
            return None

    async def stop_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Stop a running crawl session."""
        try:
            session = _active_sessions.get(session_id)
            if not session:
                return {
                    "success": False,
                    "error": "Session not found"
                }

            if session.get("status") == "completed":
                return {
                    "success": False,
                    "error": "Session already completed"
                }

            session["status"] = "stopped"
            session["completed_at"] = datetime.utcnow().isoformat()
            _active_sessions[session_id] = session

            logger.info(f"⏹️ Session {session_id} stopped by user")

            return {
                "success": True,
                "message": f"Session {session_id} stopped successfully"
            }

        except Exception as e:
            logger.error(f"Error stopping session: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Clean up old completed sessions from memory."""
        try:
            current_time = datetime.utcnow()
            sessions_to_remove = []

            for session_id, session_data in _active_sessions.items():
                if session_data.get("status") in ["completed", "stopped"]:
                    completed_at = session_data.get("completed_at")
                    if completed_at:
                        completed_time = datetime.fromisoformat(completed_at)
                        age_hours = (current_time - completed_time).total_seconds() / 3600

                        if age_hours > max_age_hours:
                            sessions_to_remove.append(session_id)

            for session_id in sessions_to_remove:
                del _active_sessions[session_id]
                logger.info(f"🧹 Cleaned up old session {session_id}")

            return {
                "success": True,
                "cleaned_up": len(sessions_to_remove)
            }

        except Exception as e:
            logger.error(f"Error cleaning up sessions: {e}")
            return {
                "success": False,
                "error": str(e)
            }
