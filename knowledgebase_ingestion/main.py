import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.logging_config import auto_configure_logging

# Configure Railway-compatible logging
logger = auto_configure_logging("knowledgebase_ingestion")

from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.routers import files
from knowledgebase_ingestion.utils.middleware import log_requests_middleware
from shared import db
from shared.config import settings
from shared.utils import (log_endpoint_request,
                          register_fastapi_exception_handlers,
                          setup_global_exception_logging)

setup_global_exception_logging("knowledgebase_ingestion")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Initialize database using centralized initializer
        if settings.railway_postgres_url:
            from shared.database_initializer import database_initializer
            await database_initializer.initialize_and_validate(settings.railway_postgres_url)
            logger.info("✅ Railway PostgreSQL database initialized and validated")
        
        # Initialize Gemini Client (Check)
        if get_genai_client():
             logger.info("✅ Gemini client initialized")
        else:
             logger.warning("⚠️ Gemini client failed to initialize")

        logger.info("🚀 Knowledgebase ingestion service started successfully")
        yield
        
        if db.railway_db:
             await db.railway_db.disconnect()
        logger.info("🛑 Knowledgebase ingestion service shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledgebase Ingestion Service",
    version="1.0.0",
    lifespan=lifespan
)

register_fastapi_exception_handlers(app, "knowledgebase_ingestion")

# Middleware
app.middleware("http")(log_requests_middleware)
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
app.include_router(files.router)

@app.get("/health")
async def health_check(request: Request):
    log_endpoint_request("knowledgebase_ingestion", "health", request)
    return {"status": "healthy", "service": "knowledgebase_ingestion"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("KB_INGESTION_PORT", os.getenv("PORT", "8001")))
    logger.info(f"🚀 Starting knowledgebase_ingestion service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
