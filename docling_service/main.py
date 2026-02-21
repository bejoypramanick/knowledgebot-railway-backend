"""Docling Service - Document to Markdown Conversion with Image OCR."""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Configure OpenTelemetry
from shared.telemetry import setup_telemetry, instrument_fastapi

# Initialize Telemetry
if not hasattr(logging, '_otel_initialized_for_docling'):
    setup_telemetry("docling-service")
    logging._otel_initialized_for_docling = True

logger = logging.getLogger("docling_service")

from docling_service.core.config import settings
from docling_service.core.utils import (
    register_fastapi_exception_handlers,
    setup_global_exception_logging,
    log_endpoint_request
)
from docling_service.core.enhanced_docling_processor import enhanced_processor
from docling_service.routers import router
from shared.middleware import CorrelationIDMiddleware

setup_global_exception_logging("docling_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        logger.info("🚀 Docling Service starting...")

        # Log cache directory configuration
        hf_home = os.getenv('HF_HOME', '/models/huggingface')
        easyocr_home = os.getenv('EASYOCR_USER_AGENT_ORIGIN', '/models/easyocr')
        logger.info(f"📁 Model Cache Directories:")
        logger.info(f"   Hugging Face: {hf_home}")
        logger.info(f"   EasyOCR: {easyocr_home}")

        # Initialize Docling processor
        logger.info("⏳ Initializing Docling processor and OCR reader...")
        
        # Initialize enhanced processor
        init_success = await enhanced_processor.initialize()
        
        if init_success:
            logger.info("✅ Docling processor initialized successfully")
            logger.info(f"   Model: {settings.docling_model_name}")
            logger.info(f"   Max file size: {settings.docling_max_file_size_mb}MB")
            logger.info(f"   Processing timeout: {settings.docling_processing_timeout_seconds}s")
        else:
            logger.warning("⚠️ Docling processor initialization failed - service may have limited functionality")

        logger.info("🚀 Docling Service started successfully")
        yield

        logger.info("🛑 Docling Service shutdown complete")

    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise


app = FastAPI(
    title="Docling Service",
    description="Document to Markdown Conversion with Image OCR",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry
instrument_fastapi(app, "docling-service")

# Register exception handlers
register_fastapi_exception_handlers(app, "docling_service")

# Middleware
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
    """Handle validation errors."""
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": "Validation failed", "errors": str(exc)}
    )


# Routers
app.include_router(router, prefix="/api/v1/docling")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "docling_service",
        "status": "running",
        "description": "Document to Markdown conversion with image OCR extraction",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    log_endpoint_request("docling_service", "health", request)
    return {"status": "healthy", "service": "docling_service"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("DOCLING_PORT", os.getenv("PORT", "8004")))
    logger.info(f"🚀 Starting docling_service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
