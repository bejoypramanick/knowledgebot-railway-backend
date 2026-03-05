import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Configure OpenTelemetry for Railway
# Configure Shared Telemetry
import logging
from shared.telemetry import setup_telemetry, instrument_fastapi

# Initialize Telemetry
# Use default behavior (span exporter disabled by default via env var)
# Only set up once - add a guard to prevent re-initialization
if not hasattr(logging, '_otel_initialized_for_kb'):
    setup_telemetry("knowledgebase-ingestion")
    logging._otel_initialized_for_kb = True

logger = logging.getLogger("knowledgebase_ingestion")

from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.routers import fileupload_router, webcrawl_router
from knowledgebase_ingestion.utils.middleware import log_requests_middleware
from shared.sqlalchemy_db import init_database, validate_database, close_database
from knowledgebase_ingestion.core.config import settings
from knowledgebase_ingestion.core.utils import (log_endpoint_request,
                          register_fastapi_exception_handlers,
                          setup_global_exception_logging)
from shared.middleware import CorrelationIDMiddleware
from shared.file_search import get_file_search_store_by_display_name

setup_global_exception_logging("knowledgebase_ingestion")

# Global variable to cache resolved FileSearch store ID
# Only initialize if not already set (to prevent re-initialization on module reload)
if '_resolved_store_id' not in globals():
    _resolved_store_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Note: Celery worker is now a separate service (celery-file-worker)
        # This web service only handles HTTP requests, no Celery initialization needed
        logger.info("✅ Web service started - Celery worker is separate service")
        
        # Initialize SQLAlchemy database
        database_url = settings.railway_postgres_url or settings.database_url or os.getenv("DATABASE_URL")
        if database_url:
            try:
                await init_database(database_url)
                logger.info("✅ SQLAlchemy engine initialized")
                app.state.database_ready = True

                is_valid = await validate_database()
                if is_valid:
                    logger.info("✅ Database schema validated successfully")
                else:
                    logger.warning("⚠️ Database schema validation returned False")
            except Exception as e:
                logger.error(f"❌ Error initializing database: {e}")
                app.state.database_ready = False
                logger.warning("⚠️ Service starting with database unavailable - endpoints will return 503")
        else:
            logger.error("❌ DATABASE_URL not set")
            app.state.database_ready = False
            logger.warning("⚠️ Service starting without database - endpoints will return 503")

        # Initialize Gemini Client (Check)
        if get_genai_client():
             logger.info("✅ Gemini client initialized")
        else:
             logger.warning("⚠️ Gemini client failed to initialize")

        # Note: FileSearch store is created by API Gateway during startup
        # Read display_name from environment variable and look it up
        store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")
        logger.info(f"📂 Looking for FileSearch store by display_name: {store_display_name}")

        # Lookup store by display name using shared utility
        global _resolved_store_id
        try:
            genai_client = get_genai_client()
            if genai_client:
                _resolved_store_id = get_file_search_store_by_display_name(
                    genai_client,
                    display_name=store_display_name
                )
                if _resolved_store_id:
                    logger.info(f"✅ Resolved FileSearch store ID: {_resolved_store_id}")
                else:
                    logger.error(f"❌ FileSearch store not found with display_name: {store_display_name}")
                    logger.error("   Please ensure API Gateway has initialized FileSearch stores")
            else:
                logger.error("❌ Gemini client not available for FileSearch lookup")
        except Exception as lookup_error:
            logger.error(f"❌ Error looking up FileSearch store: {lookup_error}")

        logger.info("🚀 Knowledgebase ingestion service started successfully")
        yield

        try:
            await close_database()
            logger.info("✅ Database closed")
        except Exception as e:
            logger.error(f"❌ Error closing database: {e}")

        logger.info("🛑 Knowledgebase ingestion service shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledgebase Ingestion Service",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "knowledgebase-ingestion")

register_fastapi_exception_handlers(app, "knowledgebase_ingestion")

# Middleware
app.middleware("http")(log_requests_middleware)
app.add_middleware(CorrelationIDMiddleware)

# Database readiness check middleware
@app.middleware("http")
async def check_database_ready(request: Request, call_next):
    """Check if database is ready before processing requests"""
    # Skip check for health endpoint
    if request.url.path == "/health":
        return await call_next(request)
    
    # Check database readiness for other endpoints
    database_ready = getattr(request.app.state, 'database_ready', False)
    if not database_ready:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Service temporarily unavailable - database not ready",
                "service": "knowledgebase_ingestion"
            }
        )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": "Validation failed", "errors": str(exc)}
    )

# Routers
# Both file uploads and website scraping are under the same knowledgebase prefix
app.include_router(fileupload_router, prefix="/api/v1/knowledgebase")
app.include_router(webcrawl_router, prefix="/api/v1/knowledgebase")

@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "knowledgebase_ingestion", "status": "running"}

@app.get("/health")
async def health_check(request: Request):
    log_endpoint_request("knowledgebase_ingestion", "health", request)
    return {"status": "healthy", "service": "knowledgebase_ingestion"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("KB_INGESTION_PORT", os.getenv("PORT", "8001")))
    logger.info(f"🚀 Starting knowledgebase_ingestion service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
