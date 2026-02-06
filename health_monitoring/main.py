"""Health Monitoring Service - Microservice for tracking system health."""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from health_monitoring.core.config import settings
from shared.db import init_railway_db
from shared.otel_logger import setup_otel_logging
from health_monitoring.routers.router import router
from health_monitoring.scheduler.health_checker import get_scheduler
from health_monitoring.core.database_initializer import database_initializer

# Setup logging
setup_otel_logging("health-monitoring")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        logger.info("🚀 Health Monitoring Service starting...")

        # Initialize database
        if settings.railway_postgres_url or settings.database_url:
            db_url = settings.railway_postgres_url or settings.database_url
            await init_railway_db(db_url)
            await database_initializer.initialize_and_validate(db_url)
            logger.info("✅ Database initialized and schema validated")
        else:
            logger.warning("⚠️ Database URL not configured - health checks will not be persisted")

        # Start the health check scheduler
        scheduler = get_scheduler()
        await scheduler.start()
        logger.info(f"✅ Health check scheduler started (interval: {settings.health_check_interval_seconds}s)")

        logger.info("✅ Health Monitoring Service started successfully")
        yield

        # Shutdown
        logger.info("🛑 Health Monitoring Service shutting down...")
        await scheduler.stop()
        logger.info("✅ Health Monitoring Service shutdown complete")

    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise


# Create FastAPI app
app = FastAPI(
    title="Health Monitoring Service",
    description="Microservice for monitoring the health of all other services",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "health-monitoring",
        "status": "running",
        "description": "Health monitoring microservice for tracking system availability"
    }


# Health check endpoint for Railway and other services
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and external health checks."""
    return {
        "status": "healthy",
        "service": "health-monitoring",
        "version": "1.0.0"
    }


# Include routers
app.include_router(router, prefix="/api/v1/health", tags=["health"])


# Error handling
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"❌ Unhandled exception: {exc}")
    return {"error": str(exc), "status": "error"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("HEALTH_MONITORING_PORT", settings.health_monitoring_port))
    logger.info(f"🚀 Starting Health Monitoring Service on port {port}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
