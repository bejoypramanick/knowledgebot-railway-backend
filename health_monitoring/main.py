"""Health Monitoring Service - Microservice for tracking system health."""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from health_monitoring.core.config import settings
from health_monitoring.core.db import init_railway_db
from health_monitoring.core.otel_logger import setup_otel_logging
from health_monitoring.routers.router import router
from health_monitoring.scheduler.health_checker import get_scheduler

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
            await init_railway_db(settings.railway_postgres_url or settings.database_url)
            logger.info("✅ Database initialized")
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
