"""Health Monitoring Service - Microservice for tracking system health."""
import os
import logging
from shared.otel_logger import get_otel_logger
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from health_monitoring.core.config import settings
from shared.sqlalchemy_db import init_database, validate_database, close_database, health_check as db_health_check
from shared.telemetry import setup_telemetry
from health_monitoring.routers.router import router
from health_monitoring.scheduler.health_checker import get_scheduler

# Setup logging
setup_telemetry("health-monitoring")
logger = get_otel_logger(__name__, "health_monitoring")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        logger.info("🚀 Health Monitoring Service starting...")
        logger.info(f"⚙️  Config: HEALTH_MONITOR_ENABLED={settings.health_monitor_enabled}, HEALTH_CHECK_ENABLED={settings.health_check_enabled}")

        # Initialize SQLAlchemy database
        db_url = settings.railway_postgres_url or settings.database_url
        if db_url:
            try:
                await init_database(db_url)
                logger.info("✅ SQLAlchemy engine initialized")

                is_valid = await validate_database()
                if is_valid:
                    logger.info("✅ Database schema validated successfully")
                else:
                    logger.warning("⚠️ Database schema validation returned False")
            except Exception as e:
                logger.error(f"❌ Error initializing database: {e}")
                raise
        else:
            logger.warning("⚠️ Database URL not configured - health checks will not be persisted")

        # Start the health check scheduler (only if HEALTH_MONITOR_ENABLED=true)
        if settings.health_monitor_enabled:
            if settings.health_check_enabled:
                scheduler = get_scheduler()
                await scheduler.start()
                logger.info(f"✅ Health check scheduler started (interval: {settings.health_check_interval_seconds}s)")
            else:
                logger.info("ℹ️  Service monitoring is ENABLED, but checks are disabled (HEALTH_CHECK_ENABLED=false)")
        else:
            logger.warning("⚠️ Service monitoring is DISABLED (HEALTH_MONITOR_ENABLED=false)")

        logger.info("✅ Health Monitoring Service started successfully")
        yield

        # Shutdown
        logger.info("🛑 Health Monitoring Service shutting down...")
        try:
            await close_database()
            logger.info("✅ Database closed")
        except Exception as e:
            logger.error(f"❌ Error closing database: {e}")

        if settings.health_monitor_enabled and settings.health_check_enabled:
            scheduler = get_scheduler()
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
