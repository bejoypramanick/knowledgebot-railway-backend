"""
Main FastAPI application for Celery File Processing Worker
Provides internal endpoints for task dispatch and management
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.otel_logger import get_otel_logger
from shared.middleware import CorrelationIDMiddleware

# Import internal router
from internal import router

logger = get_otel_logger("celery-file-worker", "celery-file-worker")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Initialize Celery for task processing
        try:
            from celery_app import celery_app
            logger.info(f"✅ Celery application initialized - Ready to process file tasks")
        except Exception as celery_error:
            logger.error(f"❌ Failed to initialize Celery: {celery_error}")
        
        logger.info("🚀 File worker service started successfully")
        yield
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Celery File Processing Worker",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include internal router
from routers.internal import router
app.include_router(router)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "celery-file-worker", "status": "running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "celery-file-worker"}

@app.get("/api/workers")
async def worker_status():
    """Worker status endpoint for health checks"""
    try:
        from celery_app import celery_app
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()
        
        return {
            "status": "healthy",
            "service": "celery-file-worker",
            "stats": stats,
            "active_tasks": len(active) if active else 0
        }
    except Exception as e:
        logger.error(f"❌ Error getting worker status: {e}")
        return {
            "status": "unhealthy",
            "service": "celery-file-worker",
            "error": str(e)
        }
