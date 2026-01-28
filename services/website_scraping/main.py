import sys
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.config import settings
from shared import db as shared_db
from shared.utils import register_fastapi_exception_handlers, setup_global_exception_logging, log_endpoint_request

from services.website_scraping.routers import scrape
from services.website_scraping.utils.middleware import log_requests_middleware
from services.website_scraping.core.ai import get_genai_client

setup_global_exception_logging("website_scraping")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # DB Init
        if settings.railway_postgres_url:
            await shared_db.init_railway_db(settings.railway_postgres_url)
            logger.info("✅ Railway Postgres DB initialized")

        # Gemini Init
        if get_genai_client():
            logger.info("✅ Gemini client initialized")
        else:
            logger.warning("⚠️ Gemini client failed to initialize")

        logger.info("🚀 Website scraping service started successfully")
        yield
        
        if shared_db.railway_db:
             await shared_db.railway_db.disconnect()
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
app.include_router(scrape.router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEBSITE_SCRAPING_PORT", os.getenv("PORT", "8002")))
    logger.info(f"🚀 Starting website_scraping service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
