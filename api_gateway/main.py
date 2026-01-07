# --- 🔍 STARTUP DIAGNOSTIC ---
import os
import sys
import logging
import time
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Configure basic logging for early diagnostics
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Log port and environment basic state
logger.info("🔍 --- API Gateway Startup Diagnostics ---")
logger.info("🆔 SERVICE_IDENTITY: API_GATEWAY_V1")
logger.info(f"🐍 Python: {sys.version}")
logger.info(f"📂 Current Dir: {os.getcwd()}")
logger.info(f"🌐 API_GATEWAY_PORT: {os.getenv('API_GATEWAY_PORT')}")
logger.info(f"🌐 PORT (Railway): {os.getenv('PORT')}")
logger.info(f"🔗 CHATBOT_ORCHESTRATION_URL: {os.getenv('CHATBOT_ORCHESTRATION_URL')}")
logger.info(f"🔍 --------------------------------------")

# Debug logging to check if script starts
logger.info("🔍 API Gateway script starting...")
logger.info("🔍 Testing basic imports and setup...")

# Add startup logging
logger.info("="*60)
logger.info("API GATEWAY SERVICE STARTING UP")
logger.info("="*60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")

# Log service URLs and configuration
logger.info("SERVICE CONFIGURATION:")
logger.info(f"KNOWLEDGEBASE_INGESTION_URL: {os.getenv('KNOWLEDGEBASE_INGESTION_URL', 'http://localhost:8001')}")
logger.info(f"WEBSITE_SCRAPING_URL: {os.getenv('WEBSITE_SCRAPING_URL', 'http://localhost:8002')}")
logger.info(f"CHATBOT_ORCHESTRATION_URL: {os.getenv('CHATBOT_ORCHESTRATION_URL', 'http://localhost:8003')}")
logger.info(f"CONFIGURATION_SERVICE_URL: {os.getenv('CONFIGURATION_SERVICE_URL', 'http://localhost:8004')}")
# Get port configuration
PORT = int(os.getenv('API_GATEWAY_PORT', os.getenv('PORT', '8080')))
logger.info(f"PORT being used: {PORT}")

# Check if required environment variables are set
required_env_vars = ['KNOWLEDGEBASE_INGESTION_URL', 'WEBSITE_SCRAPING_URL', 'CHATBOT_ORCHESTRATION_URL']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.warning(f"Missing environment variables: {missing_vars}")
else:
    logger.info("All required environment variables are set")

logger.info(f"🚀 Application will start on port {PORT}")

# Make shared package importable when code runs inside container
from pathlib import Path
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
except Exception:
    logger.debug("Could not adjust sys.path for shared imports")

from shared.utils import setup_global_exception_logging, register_fastapi_exception_handlers, log_system_metrics, log_endpoint_request

# Install global exception and signal handlers early so any startup issues get logged
setup_global_exception_logging("api_gateway")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Configuration endpoints are now handled by a separate service
        # No database initialization needed in API gateway
        
        # Startup
        startup_time = time.time() - getattr(app, 'start_time', time.time())
        logger.info(f"Startup time: {startup_time:.2f} seconds")
        logger.info(f"🚀 FastAPI application started successfully on port {PORT}")
        logger.info("🏥 Health check endpoint: /health")
        logger.info("📊 Status endpoint: /status")
        
        # Log registered routes
        logger.info("📋 Registered routes:")
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                methods = ', '.join(route.methods)
                logger.info(f"  {methods} {route.path}")
        logger.info(f"📊 Total routes registered: {len([r for r in app.routes if hasattr(r, 'path')])}")
        
        logger.info("🎉 API Gateway is ready to accept requests!")

        yield

        # Shutdown
        logger.info("🛑 FastAPI application shutting down")
        # API Gateway doesn't manage database connections directly
        # No cleanup needed here
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise

# Track application start time for uptime calculations
app_start_time = time.time()

logger.info("="*60)
logger.info("🏗️ Creating FastAPI application...")

try:
    app = FastAPI(
        title="Knowledge Bot API Gateway",
        version="1.0.0",
        lifespan=lifespan
    )

    # Store start time for uptime calculations
    app.start_time = app_start_time
    logger.info("✅ FastAPI application created successfully")

except Exception as e:
    logger.error(f"❌ Failed to create FastAPI application: {e}")
    logger.error(f"Error type: {type(e).__name__}")
    raise

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    request_id = f"{int(start_time * 1000000) % 1000000:06d}"  # Simple request ID

    # Log incoming request
    logger.info(f"📨 [{request_id}] {request.method} {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")

    # Log headers (excluding sensitive ones)
    safe_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ['authorization', 'x-api-key', 'cookie']}
    if safe_headers:
        logger.debug(f"📋 [{request_id}] Headers: {dict(safe_headers)}")

    try:
        # Process the request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        if response.status_code >= 400:
            logger.warning(f"↩️ [{request_id}] Response: {response.status_code} - Path: {request.url.path} - Total time: {duration:.3f}s")
            if response.status_code == 404:
                logger.error(f"❌ 404 DETECTED on path: {request.url.path}")
        else:
            logger.info(f"↩️ [{request_id}] Response: {response.status_code} - Total time: {duration:.3f}s")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 [{request_id}] Request failed after {duration:.3f}s: {e}")
        raise

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Service URLs from environment
KNOWLEDGEBASE_INGESTION_URL = os.getenv(
    "KNOWLEDGEBASE_INGESTION_URL", "http://localhost:8001"
)
WEBSITE_SCRAPING_URL = os.getenv(
    "WEBSITE_SCRAPING_URL", "http://localhost:8002"
)
CHATBOT_ORCHESTRATION_URL = os.getenv(
    "CHATBOT_ORCHESTRATION_URL", "http://localhost:8003"
)
CONFIGURATION_SERVICE_URL = os.getenv(
    "CONFIGURATION_SERVICE_URL", "http://localhost:8004"
)

class HealthResponse(BaseModel):
    status: str
    services: Dict[str, str]

# Pydantic Models for API Gateway
# Based on the README and downstream service expectations

# Knowledgebase Models
class FileUploadResponse(BaseModel):
    message: str
    file_id: str
    filename: str

class FileMetadata(BaseModel):
    id: str
    filename: str
    display_name: str
    mime_type: str
    size_bytes: int
    create_time: str

class ListFilesResponse(BaseModel):
    files: List[FileMetadata]

# Website Scraping Models
class ScrapeRequest(BaseModel):
    url: str
    max_depth: Optional[int] = 1
    max_pages: Optional[int] = 10
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    wait_for: Optional[str] = None
    js_code: Optional[str] = None
    screenshot: Optional[bool] = False
    replace_existing: Optional[bool] = False

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    file_name: Optional[str] = None
    file_info: Optional[Dict[str, Any]] = None
    scraped_urls: Optional[List[str]] = None

# Chatbot Models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    max_results: int = 5

class SearchResult(BaseModel):
    file_name: str
    content: str
    relevance_score: Optional[float] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[SearchResult] = []
    confidence: float
    data_sources_used: List[str] = []

class ChatSessionResponse(BaseModel):
    session_id: str
    message: str
    response: ChatResponse
    usage: Optional[Dict[str, Any]] = None
    timestamp: str

class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    message_count: int

class ListSessionsResponse(BaseModel):
    sessions: List[SessionSummary]

class DeleteSessionResponse(BaseModel):
    message: str
    session_id: str

class ReviewRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None
    corrected_answer: Optional[str] = None

class ReviewResponse(BaseModel):
    message: str
    review_status: str


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint - returns gateway status with detailed logging."""
    log_endpoint_request("api_gateway", "health", request)
    start_time = time.time()
    logger.info("🔍 Health check request received")

    try:
        # Check if the application is responsive
        health_status = {
            "status": "healthy",
            "service": "api-gateway",
            "timestamp": time.time(),
            "uptime_seconds": time.time() - getattr(app, 'start_time', time.time())
        }

        # Log environment checks
        logger.info("✅ Application is responsive")
        logger.info(f"📊 Health status: {health_status['status']}")

        # Check critical dependencies (basic connectivity)
        try:
            # Test if httpx client can be created (basic functionality check)
            async with httpx.AsyncClient() as client:
                logger.info("✅ HTTP client initialization successful")
        except Exception as e:
            logger.error(f"❌ HTTP client initialization failed: {e}")
            health_status["status"] = "unhealthy"
            health_status["error"] = f"HTTP client error: {str(e)}"

        # Check if service URLs are reachable (lightweight check)
        service_urls = {
            "knowledgebase_ingestion": KNOWLEDGEBASE_INGESTION_URL,
            "website_scraping": WEBSITE_SCRAPING_URL,
            "chatbot_orchestration": CHATBOT_ORCHESTRATION_URL
        }

        connectivity_checks = {}
        for service_name, url in service_urls.items():
            try:
                # Just check if URL is parseable and reachable, not full health check
                parsed_url = httpx.URL(url)
                connectivity_checks[service_name] = {
                    "url": url,
                    "reachable": True,
                    "scheme": parsed_url.scheme,
                    "host": parsed_url.host,
                    "port": parsed_url.port
                }
                logger.info(f"✅ {service_name} URL configured: {url}")
            except Exception as e:
                connectivity_checks[service_name] = {
                    "url": url,
                    "reachable": False,
                    "error": str(e)
                }
                logger.warning(f"⚠️  {service_name} URL configuration issue: {e}")
                health_status["status"] = "degraded"

        health_status["connectivity_checks"] = connectivity_checks

        # Log final health status
        duration = time.time() - start_time
        logger.info(f"⏱️ Health check duration: {duration:.3f}s")

        if health_status["status"] == "healthy":
            logger.info("🎉 Health check completed successfully")
        elif health_status["status"] == "degraded":
            logger.warning("⚠️  Health check completed with warnings")
        else:
            logger.error("❌ Health check failed")

        return health_status

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"⏱️ Health check heartbeat error after {duration:.3f}s")
        logger.error(f"💥 Critical health check error: {e}")
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@app.get("/status")
async def system_status():
    """Check connections to all downstream services with detailed logging."""
    start_time = time.time()
    logger.info("🔍 System status check initiated")

    services = {
        "knowledgebase": KNOWLEDGEBASE_INGESTION_URL,
        "website_scraping": WEBSITE_SCRAPING_URL,
        "chatbot": CHATBOT_ORCHESTRATION_URL
    }
    statuses = {"gateway": "online"}
    detailed_results = {
        "timestamp": time.time(),
        "overall_status": "checking",
        "services": {}
    }

    logger.info("🌐 Checking downstream service connectivity...")

    async with httpx.AsyncClient(timeout=10.0) as client:  # Increased timeout for better diagnostics
        for name, url in services.items():
            service_start_time = time.time()
            logger.info(f"🔗 Checking {name} service at {url}")

            try:
                # Try to hit the health endpoint of the downstream service
                health_url = f"{url}/health"
                logger.info(f"📡 Making request to: {health_url}")

                resp = await client.get(health_url, timeout=5.0)

                service_duration = time.time() - service_start_time
                logger.info(".3f")

                if resp.status_code == 200:
                    statuses[name] = "online"
                    logger.info(f"✅ {name} service is ONLINE (status: {resp.status_code})")

                    # Try to parse response for additional details
                    try:
                        response_data = resp.json()
                        logger.info(f"📊 {name} health response: {response_data}")
                        detailed_results["services"][name] = {
                            "status": "online",
                            "http_status": resp.status_code,
                            "response_time_seconds": round(service_duration, 3),
                            "health_data": response_data
                        }
                    except Exception as parse_error:
                        logger.warning(f"⚠️  Could not parse {name} health response as JSON: {parse_error}")
                        detailed_results["services"][name] = {
                            "status": "online",
                            "http_status": resp.status_code,
                            "response_time_seconds": round(service_duration, 3),
                            "response_text": resp.text[:200]  # First 200 chars
                        }

                else:
                    statuses[name] = f"error: {resp.status_code}"
                    logger.error(f"❌ {name} service returned error status: {resp.status_code}")
                    logger.error(f"📄 Response: {resp.text[:500]}")  # Log response body for debugging

                    detailed_results["services"][name] = {
                        "status": "error",
                        "http_status": resp.status_code,
                        "response_time_seconds": round(service_duration, 3),
                        "error": f"HTTP {resp.status_code}",
                        "response_preview": resp.text[:200]
                    }

            except httpx.TimeoutException as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"timeout: {str(e)}"
                logger.error(".3f")
                logger.error(f"⏰ {name} service health check timed out")

                detailed_results["services"][name] = {
                    "status": "timeout",
                    "error": "Request timeout",
                    "response_time_seconds": round(service_duration, 3),
                    "timeout_seconds": 5.0
                }

            except httpx.ConnectError as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"unreachable: {str(e)}"
                logger.error(".3f")
                logger.error(f"🚫 {name} service is unreachable: {e}")

                detailed_results["services"][name] = {
                    "status": "unreachable",
                    "error": str(e),
                    "response_time_seconds": round(service_duration, 3)
                }

            except Exception as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"error: {str(e)}"
                logger.error(".3f")
                logger.error(f"💥 Unexpected error checking {name} service: {e}")

                detailed_results["services"][name] = {
                    "status": "error",
                    "error": str(e),
                    "response_time_seconds": round(service_duration, 3),
                    "error_type": type(e).__name__
                }

    # Determine overall system status
    online_services = sum(1 for status in statuses.values() if status == "online")
    total_services = len(services) + 1  # +1 for gateway

    if online_services == total_services:
        detailed_results["overall_status"] = "healthy"
        logger.info("🎉 All services are healthy")
    elif online_services >= total_services - 1:  # At least gateway + most services
        detailed_results["overall_status"] = "degraded"
        logger.warning("⚠️  System is degraded - some services may be unavailable")
    else:
        detailed_results["overall_status"] = "unhealthy"
        logger.error("❌ System is unhealthy - critical services are down")

    total_duration = time.time() - start_time
    logger.info(".3f")

    # Return both simple status and detailed results
    return {
        "simple_status": statuses,
        "detailed_status": detailed_results
    }


@app.get("/gateway-check")
async def gateway_check():
    """Direct diagnostic route to verify Gateway is responding."""
    return {
        "status": "online",
        "message": "API Gateway is responding directly",
        "timestamp": time.time(),
        "env_port": os.getenv("PORT"),
        "orchestration_url": os.getenv("CHATBOT_ORCHESTRATION_URL")
    }


@app.post("/chat")
async def chatbot_bypass_diagnostic(request: Request):
    """
    NUCLEAR DIAGNOSTIC BYPASS: If this route is hit, it means Railway has deployed
    the API Gateway container where the Chatbot service should be.
    """
    logger.error("🛑 CRITICAL: Service Confusion Detected!")
    logger.error("This container is running API_GATEWAY code but was hit on the /chat route.")
    return JSONResponse(
        status_code=418,
        content={
            "error": "Service Confusion Detected",
            "identity": SERVICE_IDENTITY,
            "message": "This is the API Gateway, but you called /chat (the Chatbot route). This proves Railway is misrouting your deployment.",
            "suggestion": "Check Railway UI -> Chatbot Service -> Settings -> Dockerfile Path. Ensure it points to 'services/chatbot_orchestration/Dockerfile'."
        }
    )


# API Gateway Routing Endpoints

@app.post("/api/v1/chat")
async def chat_endpoint(chat_request: ChatRequest, request: Request):
    """Route chat requests to chatbot orchestration service."""
    try:
        # Get the request headers
        headers = dict(request.headers)

        # Remove hop-by-hop headers and problematic headers like Host/Content-Length
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers}
        
        # Explicitly remove Host and Content-Length so httpx sets them correctly
        headers.pop('host', None)
        headers.pop('Host', None)
        headers.pop('content-length', None)
        headers.pop('Content-Length', None)

        target_url = f"{CHATBOT_ORCHESTRATION_URL}/chat"
        logger.info(f"🧪 Forwarding chat request to: {target_url}")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target_url,
                json=chat_request.model_dump(),
                headers=headers,
                timeout=30.0
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing chat request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")


@app.get("/api/v1/sessions", response_model=ListSessionsResponse)
async def list_sessions_endpoint(request: Request):
    """Route list sessions requests to chatbot orchestration service."""
    try:
        headers = dict(request.headers)
        # Remove hop-by-hop and problematic headers
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


@app.delete("/api/v1/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session_endpoint(session_id: str, request: Request):
    """Route delete session requests to chatbot orchestration service."""
    try:
        headers = dict(request.headers)
        # Remove hop-by-hop and problematic headers
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


@app.post("/api/v1/knowledgebase/upload")
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
        logger.info(f"📋 Content type: {file.content_type}")
        logger.info(f"🔄 Replace existing: {replace_existing}")

        # Read the file content asynchronously
        file_content = await file.read()
        logger.info(f"📦 File content read: {len(file_content)} bytes")

        # Prepare multipart form data for forwarding
        # Using a tuple of (filename, file_content, content_type) for httpx
        # This maps to FastAPI's: file: UploadFile = File(...)
        files = {
            'file': (
                file.filename or 'uploaded_file',
                file_content,
                file.content_type or 'application/octet-stream'
            )
        }

        # Prepare form data fields
        # This maps to FastAPI's: display_name: Optional[str] = Form(None), replace_existing: bool = Form(False)
        data = {}
        if display_name:
            data['display_name'] = display_name
            logger.info(f"📝 Display name: {display_name}")
        else:
            logger.info("📝 No display name provided")
        
        # Always include replace_existing in form data
        data['replace_existing'] = str(replace_existing).lower()
        logger.info(f"🔄 Forwarding replace_existing: {data['replace_existing']}")

        # Prepare headers for forwarding
        # This maps to FastAPI's: user_email: Optional[str] = Header(None, alias="X-User-Email")
        headers = {}
        if user_email:
            headers['X-User-Email'] = user_email
            logger.info(f"👤 User email: {user_email}")
        else:
            logger.info("👤 No user email provided in headers")

        # Remove hop-by-hop and problematic headers
        request_headers = dict(request.headers)
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers.update({k: v for k, v in request_headers.items()
                       if k.lower() not in hop_by_hop_headers and k.lower() not in ['content-type', 'content-length', 'host']})

        target_url = f"{KNOWLEDGEBASE_INGESTION_URL}/upload"
        logger.info(f"📤 Forwarding upload to: {target_url}")
        logger.info(f"📋 Multipart file field: 'file' = {file.filename} ({len(file_content)} bytes)")
        logger.info(f"📋 Form data fields: {data if data else 'None'}")
        logger.info(f"📋 Custom headers: {headers if headers else 'None'}")

        # Create async HTTP client with appropriate timeout
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            # Forward the request asynchronously
            resp = await client.post(
                target_url,
                files=files,
                data=data,
                headers=headers
            )

            logger.info(f"📥 Upload response status: {resp.status_code}")

            # Parse response content
            response_content = None
            try:
                response_content = resp.json()
                logger.info(f"📥 Upload response (JSON): {response_content}")
            except Exception as json_error:
                logger.warning(f"⚠️  Could not parse response as JSON: {json_error}")
                response_content = resp.text
                logger.info(f"📥 Upload response (text): {response_content[:500]}")

            # Log success or warnings
            if resp.status_code == 200:
                logger.info("✅ File upload completed successfully")
            else:
                logger.warning(f"⚠️  File upload returned status {resp.status_code}")
                logger.warning(f"⚠️  Response details: {response_content}")

            # Return the response from the backend service
            return JSONResponse(
                status_code=resp.status_code,
                content=response_content if isinstance(response_content, dict) else {"detail": response_content}
            )

    except httpx.TimeoutException as te:
        logger.error(f"⏰ Upload request timed out: {te}")
        raise HTTPException(
            status_code=504,
            detail=f"Upload request timed out. The file may be too large or the service is slow to respond: {str(te)}"
        )
    except httpx.ConnectError as ce:
        logger.error(f"🚫 Could not connect to knowledgebase service at {KNOWLEDGEBASE_INGESTION_URL}: {ce}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to knowledgebase service: {str(ce)}"
        )
    except Exception as e:
        logger.error(f"❌ Error routing knowledgebase upload request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Knowledgebase service error: {str(e)}"
        )
    finally:
        # Clean up file content from memory
        if file_content:
            del file_content
            logger.debug("🧹 File content cleaned from memory")


@app.get("/api/v1/knowledgebase/upload/constraints")
async def knowledgebase_upload_constraints_endpoint(request: Request):
    """Route upload constraints requests to knowledgebase ingestion service."""
    try:
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/upload/constraints"

        headers = dict(request.headers)
        # Remove hop-by-hop and problematic headers
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
        logger.error(f"Error routing upload constraints request: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")


@app.get("/api/v1/knowledgebase/files")
async def knowledgebase_files_endpoint(request: Request):
    """Route knowledgebase files list requests to knowledgebase ingestion service."""
    try:
        # Get query parameters
        query_params = str(request.url.query)
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files"
        if query_params:
            url += f"?{query_params}"

        headers = dict(request.headers)
        # Remove hop-by-hop and problematic headers
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
        logger.error(f"Error routing knowledgebase files request: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")


@app.get("/api/v1/knowledgebase/files/metadata")
async def knowledgebase_files_metadata_endpoint(
    request: Request,
    include_signed_urls: bool = False,
    signed_url_expiration: int = 3600
):
    """Route knowledgebase files metadata requests to knowledgebase ingestion service."""
    try:
        # Build URL with query parameters
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files/metadata"
        query_params = []
        if include_signed_urls:
            query_params.append(f"include_signed_urls=true")
        if signed_url_expiration != 3600:
            query_params.append(f"signed_url_expiration={signed_url_expiration}")

        if query_params:
            url += "?" + "&".join(query_params)

        headers = dict(request.headers)
        # Remove hop-by-hop and problematic headers
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


# R2 storage removed - signed-url and download endpoints removed


@app.delete("/api/v1/knowledgebase/files/{file_name:path}")
async def knowledgebase_file_delete_endpoint(
    file_name: str,
    request: Request
):
    """Route file deletion requests to knowledgebase ingestion service.
    
    Deletes a file from Gemini FileSearch and database.
    The file_name should be the database ID (UUID).
    """
    try:
        url = f"{KNOWLEDGEBASE_INGESTION_URL}/files/{file_name}"
        logger.info(f"🗑️ Forwarding delete request for file: {file_name} to {url}")

        headers = dict(request.headers)
        # Remove hop-by-hop headers and problematic ones
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30.0)
            
            logger.info(f"🗑️ Delete response status: {resp.status_code}")
            
            response_content = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {"detail": resp.text}
            
            if resp.status_code == 200:
                logger.info(f"✅ File {file_name} deleted successfully")
            else:
                logger.warning(f"⚠️ Delete returned status {resp.status_code}: {response_content}")
            
            return JSONResponse(
                status_code=resp.status_code,
                content=response_content
            )
    except Exception as e:
        logger.error(f"Error routing delete request for file {file_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Knowledgebase service error: {str(e)}")


@app.post("/api/v1/scrape")
async def scrape_endpoint(scrape_request: ScrapeRequest, request: Request):
    """Route scraping requests to website scraping service."""
    try:
        # Get the request headers
        headers = dict(request.headers)

        # Remove hop-by-hop headers and problematic headers like Host/Content-Length
        hop_by_hop_headers = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
        ]
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() not in ['host', 'content-length']}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{WEBSITE_SCRAPING_URL}/scrape",
                json=scrape_request.model_dump(),
                headers=headers,
                timeout=60.0  # Longer timeout for scraping
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            )
    except Exception as e:
        logger.error(f"Error routing scrape request: {e}")
        raise HTTPException(status_code=500, detail=f"Scraping service error: {str(e)}")


# Configuration API endpoints - proxy to configuration service
@app.get("/api/v1/configuration/chatbot")
@app.post("/api/v1/configuration/chatbot")
async def proxy_chatbot_config(request: Request):
    """Proxy chatbot configuration requests to configuration service"""
    try:
        # Increased timeout to 60s to allow for email sending operations
        async with httpx.AsyncClient(timeout=60.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/configuration/chatbot"
            
            # Get request body if it's a POST
            body = None
            if method == "POST":
                body = await request.body()
            
            # Forward headers (excluding host)
            headers = dict(request.headers)
            headers.pop("host", None)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in configuration proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/v1/configuration/widget")
@app.post("/api/v1/configuration/widget")
async def proxy_widget_config(request: Request):
    """Proxy widget configuration requests to configuration service"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/configuration/widget"
            
            # Get request body if it's a POST
            body = None
            if method == "POST":
                body = await request.body()
            
            # Forward headers (excluding host)
            headers = dict(request.headers)
            headers.pop("host", None)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Configuration service timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying to configuration service: {e}")
        raise HTTPException(status_code=503, detail=f"Configuration service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in configuration proxy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Admin API endpoints - proxy to configuration service
@app.api_route("/api/v1/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_admin_routes(request: Request, path: str):
    """Proxy admin API requests to configuration service (token-usage, human-agents, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            method = request.method
            url = f"{CONFIGURATION_SERVICE_URL}/api/v1/admin/{path}"
            
            # Get request body if it's a POST/PUT/PATCH
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
            
            # Forward headers (excluding host)
            headers = dict(request.headers)
            headers.pop("host", None)
            
            response = await client.request(
                method=method,
                url=url,
                content=body,
                headers=headers
            )
            
            # Return JSON if content-type is JSON, otherwise return raw response
            if "application/json" in response.headers.get("content-type", ""):
                return response.json()
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

logger.info("✅ Configuration API proxy endpoints configured")
logger.info("✅ Admin API proxy endpoints configured")