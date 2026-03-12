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
from shared.otel_logger import get_otel_logger
from shared.telemetry import setup_telemetry, instrument_fastapi
from shared.otel_logger import get_otel_logger

# Initialize Telemetry (Logging + Tracing)
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("api-gateway")
logger = get_otel_logger("api_gateway", "api-gateway")

from api_gateway.core.config import get_settings
from api_gateway.core.auth_middleware import get_current_user, SessionAuthMiddleware
# Import routers and config
from api_gateway.routers import router as api_router
from api_gateway.routers.auth_router import router as auth_router
# Note: Service routers run in separate containers on Railway, so we can't import them directly
# We'll use HTTP proxy calls to communicate with other services
from api_gateway.utils.middleware import (add_security_headers_middleware,
                                          log_requests_middleware)
from api_gateway.core.utils import (register_fastapi_exception_handlers,
                          setup_global_exception_logging)
from shared.sqlalchemy_db import close_database, health_check as db_health_check
from shared.db_retry import initialize_database_with_retry

setup_global_exception_logging("api_gateway")

# OpenTelemetry setup is now handled at the top level via shared.telemetry

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        settings = get_settings()
        logger.info(f"🚀 API Gateway starting up...")
        logger.info(f"({settings.service_identity})")

        # Initialize SQLAlchemy database with centralized retry logic
        # Uses shared db_retry module for consistent Railway-ready retry behavior
        database_url = os.getenv("DATABASE_URL")
        await initialize_database_with_retry(database_url, service_name="api-gateway")

        # Initialize ProfileService (connection pooling for configuration service)
        logger.info("🔧 Initializing ProfileService...")
        from api_gateway.services.profile_service import init_profile_service
        init_profile_service()
        logger.info("✅ ProfileService initialized with connection pooling")

        # Initialize Gemini FileSearch Store (create if doesn't exist)
        logger.info("📂 Initializing Gemini FileSearch store...")
        try:
            from google.genai import Client

            # Get Gemini API key
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                logger.warning("⚠️ GEMINI_API_KEY not set - FileSearch store initialization skipped")
            else:
                # Get store display name from environment (must be set)
                store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME")
                if not store_display_name:
                    logger.warning("⚠️ GEMINI_FILE_SEARCH_STORE_NAME not set - cannot initialize FileSearch store")
                else:
                    # Initialize Gemini client
                    client = Client(api_key=gemini_api_key)

                    if not hasattr(client, 'file_search_stores'):
                        logger.warning("⚠️ file_search_stores API not available")
                    else:
                        logger.info(f"🔍 Checking for FileSearch store with display_name: {store_display_name}")

                        # First, clean up any unnamed stores (created incorrectly with display_name=None)
                        logger.info("🧹 Step 1: Cleaning up unnamed FileSearch stores...")
                        all_stores = list(client.file_search_stores.list())
                        logger.info(f"📋 Found {len(all_stores)} FileSearch store(s)")

                        unnamed_stores = [s for s in all_stores if not getattr(s, 'display_name', None)]
                        if unnamed_stores:
                            for unnamed_store in unnamed_stores:
                                try:
                                    logger.info(f"   🗑️ Deleting unnamed store: {unnamed_store.name}")
                                    client.file_search_stores.delete(name=unnamed_store.name)
                                    logger.info(f"   ✅ Deleted: {unnamed_store.name}")
                                except Exception as delete_error:
                                    logger.warning(f"   ⚠️ Failed to delete {unnamed_store.name}: {delete_error}")
                        else:
                            logger.info("   ✅ No unnamed stores to clean up")

                        # Now check for our target store
                        logger.info(f"🔍 Step 2: Looking for store with display_name: {store_display_name}")
                        stores = list(client.file_search_stores.list())

                        existing_store = None
                        for store in stores:
                            store_name = getattr(store, 'display_name', None)
                            if store_name == store_display_name:
                                existing_store = store
                                break

                        if existing_store:
                            # Store already exists
                            logger.info(f"✅ FileSearch store exists: {existing_store.name}")
                            logger.info(f"   Display name: {store_display_name}")
                        else:
                            # Store doesn't exist, create it
                            logger.info(f"🔨 Step 3: Creating FileSearch store with display_name: {store_display_name}")
                            new_store = client.file_search_stores.create(
                                config={'display_name': store_display_name}
                            )
                            logger.info(f"✅ FileSearch store created: {new_store.name}")
                            logger.info(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")

        except Exception as e:
            logger.error(f"❌ Error initializing FileSearch store: {e}")
            logger.warning("⚠️ Services will continue but file uploads may fail")

        # Initialize Firebase Admin SDK
        logger.info("🔐 Initializing Firebase Admin SDK...")
        try:
            from api_gateway.core.firebase_auth import init_firebase_auth
            init_firebase_auth()
            logger.info("✅ Firebase Admin SDK initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")
            logger.error("   Authentication will not work!")
            raise RuntimeError(f"Firebase initialization failed: {e}") from e

        logger.info(f"🚀 API Gateway ({settings.service_identity}) started successfully")
        yield
        # Shutdown
        logger.info("🛑 API Gateway shutting down")

        # Close ProfileService HTTP client
        try:
            from api_gateway.services.profile_service import close_profile_service
            await close_profile_service()
            logger.info("✅ ProfileService closed")
        except Exception as e:
            logger.error(f"❌ Error closing ProfileService: {e}")

        # Close database
        try:
            await close_database()
            logger.info("✅ Database closed")
        except Exception as e:
            logger.error(f"❌ Error closing database: {e}")
            
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledge Bot API Gateway",
    version="1.0.0",
    description="API Gateway for Knowledge Bot microservices",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "api-gateway")


# Add middleware to app
# IMPORTANT: Middleware execution order in Starlette/FastAPI is LIFO (Last In, First Out)
# - Last middleware added = First to execute (closest to the request)
# - First middleware added = Last to execute (closest to response)
# We want: SessionAuth -> Other Middlewares -> CORS -> App
# So add in reverse order: CORS first, then SessionAuth
# This ensures CORS headers are added to all responses (including auth errors)

# Configure SessionAuthMiddleware with public endpoints excluded
app.add_middleware(
    SessionAuthMiddleware,
    exclude_paths=[
        "/",
        "/health",
        "/gateway/health",
        "/gateway-check",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        "/api/v1/gateway/auth/session",  # Session creation endpoint
        "/api/v1/gateway/auth/logout",   # Logout endpoint
        "/api/v1/gateway/chatbot/chat/stream",  # Public chat widget endpoint
        "/api/v1/gateway/widget",  # Public widget HTML endpoint
        "/chat",  # Confusion detector endpoint
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://digibot-dev.globistaan.com",
        "https://digibot.globistaan.com",
        "https://dailogue.globistaan.com",  # Production frontend
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

register_fastapi_exception_handlers(app, "api_gateway")

# Middleware
app.middleware("http")(log_requests_middleware)

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
app.include_router(auth_router, prefix="/api/v1/gateway")  # Auth endpoints at gateway prefix
app.include_router(api_router, prefix="/api/v1/gateway")  
logger.info(f"🔧 Auth router included at /api/v1/gateway prefix")
logger.info(f"🔧 API Gateway router included with /api/v1/gateway prefix")
logger.info("📋 Note: Service endpoints will be proxied via HTTP calls to separate containers") 

# Add app-level endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "api_gateway", "status": "running"}

@app.get("/health")
async def root_health_check():
    """Root health check endpoint with database verification"""
    db_health = await db_health_check()
    return {
        "status": "healthy" if db_health["status"] == "healthy" else "unhealthy",
        "service": "api_gateway",
        "version": "1.0.0",
        "database": db_health["status"],
        "database_latency_ms": db_health.get("latency_ms", 0)
    }

# Also keep /gateway/health for backward compatibility
@app.get("/gateway/health")
async def legacy_health_check():
    """Legacy health check endpoint with database verification"""
    db_health = await db_health_check()
    return {
        "status": "healthy" if db_health["status"] == "healthy" else "unhealthy",
        "service": "api_gateway",
        "version": "1.0.0",
        "database": db_health["status"],
        "database_latency_ms": db_health.get("latency_ms", 0)
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_GATEWAY_PORT", os.getenv("PORT", "8080")))
    logger.info(f"🚀 Starting API Gateway on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)