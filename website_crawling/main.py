import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from website_crawling.core.logging_config import auto_configure_logging
from website_crawling.core.correlation_middleware import CorrelationIDMiddleware

# Configure Railway-compatible logging
logger = auto_configure_logging("website_crawling")

from website_crawling.core import db
from website_crawling.core.config import settings
from website_crawling.core.utils import (register_fastapi_exception_handlers,
                          setup_global_exception_logging)
from website_crawling.core.ai import get_genai_client
from website_crawling.routers.scrape import router
from website_crawling.utils.middleware import log_requests_middleware

setup_global_exception_logging("website_scraping")

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

        logger.info("🚀 Website scraping service started successfully")
        yield
        
        if db.railway_db:
             await db.railway_db.disconnect()
        logger.info("🛑 Website scraping service shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Website Scraping Service",
    version="1.0.0",
    lifespan=lifespan
)

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
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEBSITE_SCRAPING_PORT", os.getenv("PORT", "8002")))
    logger.info(f"🚀 Starting website_scraping service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
