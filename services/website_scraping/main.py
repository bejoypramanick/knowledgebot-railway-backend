"""Website Scraping Service - Handles website scraping using Crawl4AI and Gemini FileSearch."""
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl, validator, Field
from typing import Optional, Dict, Any, List
from google import genai
from google.genai import types
import os
import logging
import re
import json
from dotenv import load_dotenv
import asyncio
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
import tempfile
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from shared.config import settings

# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================
MAX_URL_LENGTH = 2048
MAX_PAGES_LIMIT = 100
MAX_DEPTH_LIMIT = 5
BLOCKED_DOMAINS = [
    'localhost', '127.0.0.1', '0.0.0.0',
    '192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.',
    '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
    '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
]
ALLOWED_SCHEMES = ['http', 'https']

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure shared utilities are importable and enable global exception logging
import sys
from pathlib import Path
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
except Exception:
    logger.debug("Could not adjust sys.path for shared imports")

from shared.utils import setup_global_exception_logging, register_fastapi_exception_handlers, dependency_unavailable_error, log_system_metrics, log_endpoint_request
from shared import db as shared_db
import json
setup_global_exception_logging("website_scraping")

# Validate required environment variables for this service
if not settings.gemini_api_key:
    raise dependency_unavailable_error("gemini_api_key", "Website scraping service requires GEMINI_API_KEY")

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Startup
        logger.info("🚀 Website scraping service started successfully")
        logger.info("🏥 Health check endpoint: /health")
        logger.info("🔗 Scrape endpoint: POST /scrape")

        # Initialize Railway Postgres DB at startup if configured.
        try:
            if settings.railway_postgres_url:
                logger.info("Initializing Railway Postgres DB connection pool...")
                await shared_db.init_railway_db(settings.railway_postgres_url)
                logger.info("✅ Railway Postgres DB initialized")
            else:
                logger.info("Railway Postgres URL not configured; skipping DB initialization")
        except Exception as e:
            logger.exception("Failed to initialize Railway Postgres DB at startup: %s", e)

        yield

        # Shutdown
        logger.info("🛑 Website scraping service shutting down")
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Website Scraping Service",
    version="1.0.0",
    lifespan=lifespan
)

# Register FastAPI-level exception handlers to ensure stack traces are logged
register_fastapi_exception_handlers(app, "website_scraping")

# Custom validation error handler for better error messages
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return user-friendly validation error messages."""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error.get("loc", []))
        message = error.get("msg", "Validation error")
        errors.append({"field": field, "message": message})
    
    logger.warning(f"Validation error for request: {errors}")
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "message": "Validation failed",
            "errors": errors
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
logger.info(f"GEMINI_API_KEY configured: {'YES' if GEMINI_API_KEY else 'NO'}")

# Do not crash the whole process if GEMINI_API_KEY is missing or Gemini init fails.
# Instead, initialize `genai_client` defensively and let endpoints return 503 when
# the client is required. This prevents the container from exiting at startup
# due to missing optional configuration.
genai_client = None
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY environment variable is not set - Gemini-dependent endpoints will be unavailable")
else:
    try:
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialized successfully")
    except Exception as e:
        genai_client = None
        logger.error(f"Failed to initialize Gemini client: {e}")


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL format and security."""
    if not url:
        return False, "URL is required"
    
    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH} characters"
    
    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    
    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"URL scheme must be one of: {', '.join(ALLOWED_SCHEMES)}"
    
    # Check for host
    if not parsed.netloc:
        return False, "URL must include a domain (e.g., example.com)"
    
    # Check for blocked domains (security)
    host = parsed.netloc.lower()
    for blocked in BLOCKED_DOMAINS:
        if blocked in host:
            return False, f"Access to internal/local domains is not allowed"
    
    return True, ""


def validate_patterns(patterns: Optional[List[str]]) -> tuple[bool, str]:
    """Validate include/exclude patterns."""
    if not patterns:
        return True, ""
    
    if len(patterns) > 50:
        return False, "Maximum 50 patterns allowed"
    
    for pattern in patterns:
        if len(pattern) > 500:
            return False, f"Pattern too long (max 500 chars): {pattern[:50]}..."
        # Check for potentially dangerous regex patterns
        dangerous = ['(?!', '(?=', '(?<', '(?P']
        for d in dangerous:
            if d in pattern:
                return False, f"Pattern contains potentially dangerous regex: {pattern[:50]}..."
    
    return True, ""


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL to scrape", min_length=1, max_length=MAX_URL_LENGTH)
    session_id: Optional[str] = Field(None, description="Session ID for SSE progress tracking")
    max_depth: Optional[int] = Field(1, ge=0, le=MAX_DEPTH_LIMIT, description="Maximum crawl depth")
    max_pages: Optional[int] = Field(10, ge=1, le=MAX_PAGES_LIMIT, description="Maximum pages to scrape")
    include_patterns: Optional[List[str]] = Field(None, description="URL patterns to include")
    exclude_patterns: Optional[List[str]] = Field(None, description="URL patterns to exclude")
    wait_for: Optional[str] = Field(None, max_length=200, description="CSS selector to wait for")
    js_code: Optional[str] = Field(None, max_length=5000, description="JavaScript to execute")
    screenshot: Optional[bool] = Field(False, description="Take screenshot of page")
    replace_existing: Optional[bool] = Field(False, description="Replace existing website if duplicate found")
    
    @validator('url')
    def validate_url_format(cls, v):
        is_valid, error = validate_url(v)
        if not is_valid:
            raise ValueError(error)
        return v
    
    @validator('include_patterns', 'exclude_patterns')
    def validate_pattern_list(cls, v):
        is_valid, error = validate_patterns(v)
        if not is_valid:
            raise ValueError(error)
        return v


class ScrapeResponse(BaseModel):
    success: bool
    message: str
    file_name: Optional[str] = None
    file_info: Optional[Dict[str, Any]] = None
    scraped_urls: Optional[List[str]] = None
    validation_warnings: Optional[List[str]] = None


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    log_endpoint_request("website_scraping", "health", request)
    return {"status": "healthy", "service": "website_scraping"}

# Store for active scraping sessions
active_scraping_sessions: Dict[str, asyncio.Queue] = {}

@app.get("/scrape-progress/{session_id}")
async def scrape_progress(session_id: str):
    """SSE endpoint for real-time scraping progress updates"""

    async def event_generator():
        queue = active_scraping_sessions.get(session_id)
        if not queue:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        try:
            while True:
                # Wait for new data with timeout
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"

                    # If this is a completion or error message, clean up
                    if data.get('type') in ['completed', 'error']:
                        if session_id in active_scraping_sessions:
                            del active_scraping_sessions[session_id]
                        break

                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
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

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(request: ScrapeRequest):
    """
    Scrape a website and upload to Gemini FileSearch.

    Args:
        request: ScrapeRequest with URL and options

    Returns:
        ScrapeResponse with upload information

    Raises:
        HTTPException 400: Validation errors (URL format, parameters)
        HTTPException 500: Scraping or processing failed
        HTTPException 503: Service dependencies unavailable
    """
    validation_warnings = []

    # Set up SSE queue if session_id provided
    sse_queue = None
    if request.session_id:
        sse_queue = asyncio.Queue()
        active_scraping_sessions[request.session_id] = sse_queue

        # Send initial progress update
        await sse_queue.put({
            "type": "started",
            "message": f"Started scraping {request.url}",
            "url": request.url,
            "timestamp": asyncio.get_event_loop().time()
        })

    try:
        # Additional runtime validation (Pydantic handles most)
        logger.info(f"Received scrape request for URL: {request.url}")
        
        # Validate URL is accessible (quick check)
        parsed_url = urlparse(request.url)
        domain = parsed_url.netloc.replace('www.', '')
        
        # Warn about potentially problematic URLs
        if len(request.url) > 500:
            validation_warnings.append("Long URLs may cause issues with some websites")
        
        if request.max_pages and request.max_pages > 20:
            validation_warnings.append(f"Scraping {request.max_pages} pages may take a long time")
        
        # Check for duplicate website
        existing_version = 1
        if shared_db.railway_db:
            existing_website = await shared_db.railway_db.fetchrow(
                """
                SELECT id, original_url, gemini_file_name, COALESCE(version, 1) as version
                FROM scraped_websites
                WHERE original_url = $1 OR domain = $2
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                request.url, domain
            )

            logger.info(f"URL check: request.url={request.url}, domain={domain}, replace_existing={request.replace_existing}")
            logger.info(f"Found existing_website: {existing_website}")

            if existing_website and not request.replace_existing:
                logger.info(f"Raising 409 because existing_website found and replace_existing is False")
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": f"Website '{request.url}' has already been scraped (Version {existing_website['version']}). Set replace_existing=true to re-scrape.",
                        "existing_url": existing_website['original_url'],
                        "version": existing_website['version'],
                        "suggestion": "Set replace_existing=true to create a new version"
                    }
                )
            
            if existing_website and request.replace_existing:
                existing_version = existing_website['version'] + 1
                logger.info(f"Replacing existing website: {existing_website['original_url']} (version {existing_website['version']} -> {existing_version})")
                logger.info(f"Proceeding with rescraping since replace_existing=True")
                # Delete the old Gemini file
                if existing_website['gemini_file_name'] and genai_client:
                    try:
                        genai_client.files.delete(name=existing_website['gemini_file_name'])
                        logger.info(f"Deleted old Gemini file: {existing_website['gemini_file_name']}")
                    except Exception as e:
                        logger.warning(f"Failed to delete old Gemini file: {e}")
                # Delete old database record
                await shared_db.railway_db.execute(
                    "DELETE FROM scraped_websites WHERE id = $1",
                    existing_website['id']
                )
                logger.info(f"Deleted old database record: {existing_website['id']}")
        
        # Scrape the website using Crawl4AI
        logger.info(f"Scraping website: {request.url} (version {existing_version})")

        if sse_queue:
            await sse_queue.put({
                "type": "scraping_started",
                "message": f"Initializing scraper for {request.url}",
                "url": request.url,
                "timestamp": asyncio.get_event_loop().time()
            })

        # Configure browser
        browser_config = BrowserConfig(verbose=False, headless=True)

        # Configure crawl options using CrawlerRunConfig
        run_config = CrawlerRunConfig()

        # Note: crawl4ai 0.7.x API changes - single URL crawling via arun()
        # For multi-page crawling, we'll use deep crawling or arun_many in future
        # For MVP, we'll scrape single page

        async with AsyncWebCrawler(config=browser_config) as crawler:
            # Execute crawl
            if sse_queue:
                await sse_queue.put({
                    "type": "page_crawling",
                    "message": f"Crawling page: {request.url}",
                    "url": request.url,
                    "timestamp": asyncio.get_event_loop().time()
                })

            result = await crawler.arun(url=request.url, config=run_config)
            
            if not result.success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Scraping failed: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
            
            # Extract content - use markdown property (0.7.x API)
            scraped_content = ""
            if hasattr(result, 'markdown'):
                # markdown is a MarkdownOutput object with raw_markdown and fit_markdown
                if hasattr(result.markdown, 'raw_markdown'):
                    scraped_content = result.markdown.raw_markdown
                elif hasattr(result.markdown, 'fit_markdown'):
                    scraped_content = result.markdown.fit_markdown
                else:
                    scraped_content = str(result.markdown)
            
            if not scraped_content and hasattr(result, 'html'):
                scraped_content = result.html
            if not scraped_content and hasattr(result, 'cleaned_html'):
                scraped_content = result.cleaned_html
            
            if not scraped_content:
                raise HTTPException(
                    status_code=500,
                    detail="No content extracted from website"
                )
            
            # Get scraped URLs
            scraped_urls = [request.url]
            if hasattr(result, 'links') and result.links:
                # links is a dict with 'internal' and 'external' keys in 0.7.x
                if isinstance(result.links, dict):
                    if 'internal' in result.links:
                        internal_links = result.links['internal']
                        if isinstance(internal_links, list):
                            # Extract href from link dicts
                            urls = [link.get('href', link) if isinstance(link, dict) else link for link in internal_links[:request.max_pages or 10]]
                            scraped_urls.extend(urls)
                elif isinstance(result.links, list):
                    scraped_urls.extend(result.links[:request.max_pages or 10])
            
            # Ensure Gemini client is available before attempting upload
            if not genai_client:
                logger.error("Gemini client not available - cannot upload scraped content")
                from shared.utils import dependency_unavailable_error
                raise dependency_unavailable_error("gemini", "client not configured")

            # Save to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.md',
                delete=False,
                encoding='utf-8'
            ) as tmp_file:
                tmp_file.write(scraped_content)
                tmp_path = tmp_file.name
            
            try:
                # Generate display name from URL (urlparse already imported at module level)
                parsed_url = urlparse(request.url)
                domain = parsed_url.netloc.replace('www.', '')
                # Format: "Display Name | original_url" to store URL as metadata
                display_name_with_metadata = f"scraped_{domain}_{os.path.basename(tmp_path)}.md | {request.url}"
                
                # Upload to Gemini FileSearch
                logger.info(f"Uploading scraped content to Gemini FileSearch: {display_name_with_metadata}")

                if sse_queue:
                    await sse_queue.put({
                        "type": "uploading",
                        "message": f"Uploading content to Gemini FileSearch",
                        "url": request.url,
                        "timestamp": asyncio.get_event_loop().time()
                    })

                # Use `file=` (library expects file param) and add simple retry/backoff for rate limits
                uploaded_file = None
                for attempt in range(3):
                    try:
                        uploaded_file = genai_client.files.upload(
                            file=tmp_path,
                            config=types.UploadFileConfig(display_name=display_name_with_metadata, mime_type="text/markdown")
                        )
                        break
                    except Exception as e:
                        err_text = str(e)
                        if '429' in err_text or 'RESOURCE_EXHAUSTED' in err_text or 'Too Many Requests' in err_text:
                            wait = 2 ** attempt
                            logger.warning(f"Gemini upload attempt {attempt+1} failed (rate limit). Retrying in {wait}s: {e}")
                            await asyncio.sleep(wait)
                            continue
                        else:
                            logger.error(f"Error uploading to Gemini: {e}")
                            raise

                if not uploaded_file:
                    logger.error("Gemini FileSearch upload failed after retries")
                    from shared.utils import dependency_unavailable_error
                    raise dependency_unavailable_error("gemini", "File upload failed or quota exceeded")
                
                # Wait for file processing
                logger.info(f"Uploaded file: {uploaded_file.name}, waiting for processing...")
                
                file_info = {
                    "name": uploaded_file.name,
                    "display_name": uploaded_file.display_name,
                    "mime_type": uploaded_file.mime_type,
                    "state": uploaded_file.state.name if hasattr(uploaded_file, 'state') else None,
                }
                # Persist scraped metadata to Railway Postgres if available
                try:
                    if shared_db.railway_db:
                        scraping_cfg = {
                            "max_depth": request.max_depth,
                            "max_pages": request.max_pages,
                            "include_patterns": request.include_patterns,
                            "exclude_patterns": request.exclude_patterns,
                            "wait_for": request.wait_for,
                        }
                        content_bytes = scraped_content.encode('utf-8')
                        size_bytes = len(content_bytes)
                        pages_scraped = len(scraped_urls) or (request.max_pages or 1)
                        await shared_db.railway_db.execute(
                            """
                            INSERT INTO scraped_websites (
                                user_id, original_url, domain, title,
                                content_length, pages_scraped,
                                gemini_file_name, gemini_file_uri, mime_type, size_bytes,
                                gemini_state, scraping_config, metadata, version
                            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                            """,
                            None,
                            request.url,
                            domain,
                            None,
                            len(scraped_content),
                            pages_scraped,
                            uploaded_file.name,
                            getattr(uploaded_file, 'uri', None) or uploaded_file.name,
                            file_info.get('mime_type'),
                            size_bytes,
                            file_info.get('state'),
                            json.dumps(scraping_cfg),
                            json.dumps({"scraped_urls": scraped_urls}),
                            existing_version
                        )
                        logger.info(f"Persisted scraped website metadata to database (version {existing_version})")
                except Exception as e:
                    logger.exception("Failed to persist scraped website metadata: %s", e)

                # Send completion event via SSE
                if sse_queue:
                    await sse_queue.put({
                        "type": "completed",
                        "message": f"Successfully scraped and uploaded {request.url}",
                        "url": request.url,
                        "file_name": uploaded_file.name,
                        "scraped_urls": scraped_urls,
                        "timestamp": asyncio.get_event_loop().time()
                    })

                return ScrapeResponse(
                    success=True,
                    message=f"Website scraped and uploaded successfully",
                    file_name=uploaded_file.name,
                    file_info=file_info,
                    scraped_urls=scraped_urls,
                    validation_warnings=validation_warnings if validation_warnings else None
                )
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error scraping website: {error_msg}")

        # Send error event via SSE
        if sse_queue:
            await sse_queue.put({
                "type": "error",
                "message": f"Failed to scrape {request.url}: {error_msg}",
                "url": request.url,
                "error": error_msg,
                "timestamp": asyncio.get_event_loop().time()
            })

        # Provide user-friendly error messages for common issues
        if "ERR_NAME_NOT_RESOLVED" in error_msg:
            user_friendly_msg = "Unable to access the website. Please check that the URL is correct and the website is accessible."
        elif "ERR_INTERNET_DISCONNECTED" in error_msg:
            user_friendly_msg = "Internet connection issue. Please check your connection and try again."
        elif "TimeoutError" in error_msg or "timeout" in error_msg.lower():
            user_friendly_msg = "Website took too long to respond. The site might be slow or temporarily unavailable."
        elif "403" in error_msg or "Forbidden" in error_msg:
            user_friendly_msg = "Access to the website is blocked. The site might have anti-scraping measures."
        elif "404" in error_msg or "Not Found" in error_msg:
            user_friendly_msg = "The webpage was not found. Please check that the URL is correct."
        else:
            user_friendly_msg = "An error occurred while scraping the website. Please try again later."

        raise HTTPException(
            status_code=500,
            detail=f"Scraping failed: {user_friendly_msg} (Technical details: {error_msg})"
        )


if __name__ == "__main__":
    import uvicorn
    # Port selection order: Service-specific -> Railway PORT -> Default 8002
    port = int(os.getenv("WEBSITE_SCRAPING_PORT", os.getenv("PORT", "8002")))
    logger.info(f"🚀 Starting website_scraping service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
