import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configure Railway-compatible logging
# Configure Shared Telemetry
import logging
from shared.telemetry import setup_telemetry, instrument_fastapi

# Initialize Telemetry (Logging + Tracing)
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("api-gateway")
logger = logging.getLogger("api_gateway")

from api_gateway.core.config import get_settings
from api_gateway.core.auth_middleware import get_current_user
# Import routers and config
from api_gateway.routers import router as api_router
# Note: Service routers run in separate containers on Railway, so we can't import them directly
# We'll use HTTP proxy calls to communicate with other services
from api_gateway.utils.middleware import (add_security_headers_middleware,
                                          log_requests_middleware)
from api_gateway.core.utils import (register_fastapi_exception_handlers,
                          setup_global_exception_logging)

setup_global_exception_logging("api_gateway")

# OpenTelemetry setup is now handled at the top level via shared.telemetry

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        settings = get_settings()
        logger.info(f"🚀 API Gateway ({settings.service_identity}) starting up...")

        # Initialize Gemini FileSearch Store (centralized - done once here)
        logger.info("📂 Initializing Gemini FileSearch store...")
        try:
            from google import genai

            # Get Gemini API key
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                logger.warning("⚠️ GEMINI_API_KEY not set - FileSearch store initialization skipped")
            else:
                # Initialize Gemini client
                client = genai.Client(api_key=gemini_api_key)

                # Get store name from environment
                store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

                # Check if file_search_stores API is available
                if not hasattr(client, 'file_search_stores'):
                    logger.warning("⚠️ file_search_stores API not available")
                    formatted_name = f"fileSearchStores/{store_name}"
                    logger.info(f"   Using store name directly: {formatted_name}")
                else:
                    logger.info(f"🔍 Checking for existing FileSearch store with display_name: {store_name}")

                    # List existing stores
                    stores = list(client.file_search_stores.list())
                    logger.info(f"📋 Available FileSearch stores ({len(stores)}):")

                    # Check if a store with our desired display_name already exists
                    existing_store = None
                    for idx, store in enumerate(stores):
                        store_display_name = getattr(store, 'display_name', None)
                        logger.info(f"   {idx+1}. {store.name} - Display: {store_display_name}")
                        if store_display_name == store_name:
                            existing_store = store
                            logger.info(f"      ✅ MATCHES desired display_name")

                    if existing_store:
                        # Use the existing store with matching display_name
                        store_id = existing_store.name
                        logger.info(f"✅ Found existing FileSearch store with matching display_name")
                        logger.info(f"   Store ID: {store_id}")
                        logger.info(f"   Display name: {existing_store.display_name}")
                        logger.info("=" * 80)
                        logger.info(f"📋 COPY THIS STORE ID TO RAILWAY ENVIRONMENT VARIABLES:")
                        logger.info(f"   GEMINI_FILE_SEARCH_STORE_NAME={store_id}")
                        logger.info("=" * 80)
                        # Update environment variable so other services can use it (only works within this process)
                        os.environ["GEMINI_FILE_SEARCH_STORE_NAME"] = store_id
                    else:
                        # No store with matching display_name found
                        # Check if there are any existing stores we can use
                        if stores and len(stores) > 0:
                            # Use the first available store
                            store_id = stores[0].name
                            logger.info(f"ℹ️ No store found with display_name '{store_name}'")
                            logger.info(f"📌 Using existing store: {store_id}")
                            logger.info("=" * 80)
                            logger.info(f"📋 COPY THIS STORE ID TO RAILWAY ENVIRONMENT VARIABLES:")
                            logger.info(f"   GEMINI_FILE_SEARCH_STORE_NAME={store_id}")
                            logger.info("=" * 80)
                            logger.info(f"💡 TIP: To use display_name matching, create a new store with:")
                            logger.info(f"   client.file_search_stores.create(config={{'display_name': '{store_name}'}})")
                            os.environ["GEMINI_FILE_SEARCH_STORE_NAME"] = store_id
                        else:
                            # No existing stores, create a new one
                            logger.info(f"🔨 No stores found, creating new store with display_name '{store_name}'...")
                            new_store = client.file_search_stores.create(
                                config={'display_name': store_name}
                            )
                            store_id = new_store.name
                            logger.info(f"✅ FileSearch store created: {store_id}")
                            logger.info(f"   Display name: {getattr(new_store, 'display_name', store_name)}")
                            logger.info("=" * 80)
                            logger.info(f"📋 COPY THIS STORE ID TO RAILWAY ENVIRONMENT VARIABLES:")
                            logger.info(f"   GEMINI_FILE_SEARCH_STORE_NAME={store_id}")
                            logger.info("=" * 80)
                            os.environ["GEMINI_FILE_SEARCH_STORE_NAME"] = store_id

        except Exception as e:
            logger.error(f"❌ Error initializing FileSearch store: {e}")
            logger.warning("⚠️ Services will continue but file uploads may fail")

        logger.info(f"🚀 API Gateway ({settings.service_identity}) started successfully")
        yield
        # Shutdown
        logger.info("🛑 API Gateway shutting down")
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledge Bot API Gateway",
    version="1.0.0",
    description="API Gateway for Knowledge Bot microservices",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "api-gateway")

# Add Firebase authentication middleware
class FirebaseAuthMiddleware(BaseHTTPMiddleware):
    """Firebase Authentication Middleware"""
    def __init__(self, app, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/",  # Root endpoint
            "/health",  # General health check
            "/gateway/health",  # Gateway health check
            "/api/v1/gateway/configuration/health",  # Configuration service health
            "/api/v1/gateway/configuration/test",  # Configuration service test endpoint
            "/api/v1/gateway/configuration/version",  # Configuration service version endpoint
            "/docs",  # API documentation
            "/redoc",  # ReDoc documentation
            "/openapi.json",  # OpenAPI schema
            "/favicon.ico",  # Favicon
            "/auth/login",  # Login endpoint
            "/auth/verify",  # Token verification endpoint
            "/gateway-check",  # Gateway diagnostic endpoint
            "/api/v1/gateway/chatbot/chat/stream",  # Public chat streaming endpoint
            "/api/v1/gateway/widget",  # Public widget endpoint
            "/widget"  # Alternative widget endpoint
        ]
    
    async def dispatch(self, request, call_next):
        # Skip auth for excluded paths and any health endpoint
        # ALL OTHER PATHS REQUIRE AUTHENTICATION
        path = request.url.path
        if (path in self.exclude_paths or 
            path.endswith("/health") or 
            request.method == "OPTIONS"):
            return await call_next(request)
        
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Verify token and add user to request state
        token = auth_header.split(" ")[1]
        try:
            from api_gateway.core.firebase_auth import verify_firebase_token
            user_data = verify_firebase_token(token)
            if not user_data:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid token"}
                )
            request.state.user = user_data
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": f"Authentication failed: {str(e)}"}
            )
        
        try:
            return await call_next(request)
        except Exception as e:
            # Catch any other exceptions that might occur during request processing
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )

# Add middleware to app
app.add_middleware(FirebaseAuthMiddleware)

register_fastapi_exception_handlers(app, "api_gateway")

# Middleware
app.middleware("http")(log_requests_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://digibot-dev.globistaan.com",
        "https://digibot.globistaan.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": "Validation failed", "errors": str(exc)}
    )

# Endpoints
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
async def chat_confusion_detector(request: Request):
    """Detect if Railway is misrouting the chatbot service to the API Gateway."""
    settings = get_settings()
    return JSONResponse(
        status_code=418,
        content={
            "error": "Service Confusion Detected",
            "identity": settings.service_identity,
            "message": "This is the API Gateway, but you called /chat (the Chatbot route). This proves Railway is misrouting your deployment.",
            "suggestion": "Check Railway UI -> Chatbot Service -> Settings -> Dockerfile Path. Ensure it points to 'services/chatbot_orchestration/Dockerfile'."
        }
    )

# Include Routers
app.include_router(api_router, prefix="/api/v1/gateway")  
logger.info(f"🔧 API Gateway router included with /api/v1/gateway prefix")
logger.info("📋 Note: Service endpoints will be proxied via HTTP calls to separate containers") 

# Add app-level endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "api_gateway", "status": "running"}

@app.get("/health")
async def root_health_check():
    """Root health check endpoint"""
    return {"status": "healthy", "service": "api_gateway", "version": "1.0.0"}

# Also keep /gateway/health for backward compatibility
@app.get("/gateway/health")
async def legacy_health_check():
    """Legacy health check endpoint"""
    return {"status": "healthy", "service": "api_gateway", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_GATEWAY_PORT", os.getenv("PORT", "8080")))
    logger.info(f"🚀 Starting API Gateway on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)