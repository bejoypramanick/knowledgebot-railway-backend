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
if not hasattr(logging, '_otel_initialized_for_wc'):
    setup_telemetry("website-crawling")
    logging._otel_initialized_for_wc = True

logger = logging.getLogger("website_crawling")

from shared.db import close_databases
from website_crawling.core.config import settings
from website_crawling.core.utils import (register_fastapi_exception_handlers,
                          setup_global_exception_logging,
                          log_endpoint_request)
from website_crawling.core.ai import get_genai_client
from website_crawling.routers import router
from website_crawling.utils.middleware import log_requests_middleware
from shared.middleware import CorrelationIDMiddleware
from shared.file_search import get_file_search_store_by_display_name

setup_global_exception_logging("website_scraping")

# Global variable to cache resolved FileSearch store ID
# Only initialize if not already set (to prevent re-initialization on module reload)
if '_resolved_store_id' not in globals():
    _resolved_store_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Initialize database using centralized initializer
        if settings.railway_postgres_url:
            from website_crawling.core.database_initializer import database_initializer
            await database_initializer.initialize_and_validate(settings.railway_postgres_url)
            logger.info("✅ Railway Postgres DB initialized and validated")

        # Gemini Init
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

        logger.info("🚀 Website scraping service started successfully")
        yield

        await close_databases()
        logger.info("🛑 Website scraping service shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Website Scraping Service",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "website-crawling")

register_fastapi_exception_handlers(app, "website_scraping")

# Middleware
app.middleware("http")(log_requests_middleware)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Routers
app.include_router(router, prefix="/api/v1/webcrawl")  # Service name as root

@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "website_crawling", "status": "running"}

@app.get("/health")
async def health_check(request: Request):
    log_endpoint_request("website_crawling", "health", request)
    return {"status": "healthy", "service": "website_crawling"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEBSITE_SCRAPING_PORT", os.getenv("PORT", "8002")))
    logger.info(f"🚀 Starting website_scraping service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
