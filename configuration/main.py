"""
Configuration Service - Handles chatbot and widget configuration management
"""
import asyncio
import datetime
import sys
import os

# VERY EARLY LOGGING - Before any other imports
print("🚀 CONFIGURATION SERVICE: STARTING EXECUTION - VERSION 3.1")
print(f"🚀 Python version: {sys.version}")
print(f"🚀 Working directory: {os.getcwd()}")
print(f"🚀 Script location: {__file__}")

# Configure Shared Telemetry
import logging
from contextlib import asynccontextmanager
from shared.telemetry import setup_telemetry, instrument_fastapi
from shared.otel_logger import get_otel_logger

# Initialize Telemetry
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("configuration")
logger = get_otel_logger("configuration", "configuration")

print("✅ RAILWAY TELEMETRY CONFIGURED SUCCESSFULLY")

# NOW import FastAPI and other dependencies
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Import routers and services
try:
    print("🚀 IMPORTING ROUTERS AND SERVICES...")
    from configuration.routers import router as config_router
    print("✅ ROUTERS AND SERVICES IMPORTED SUCCESSFULLY")
except Exception as e:
    print(f"❌ ROUTERS AND SERVICES IMPORT FAILED: {e}")
    import traceback
    print(f"❌ TRACEBACK: {traceback.format_exc()}")
    sys.exit(1)

# Import core utilities
from shared.sqlalchemy_db import init_database, validate_database, close_database, health_check as db_health_check
from configuration.core.utils import (
    validate_environment,
    wait_for_railway_network,
    ServiceStatus
)

# Initialize service status
service_status = ServiceStatus()

# Log startup diagnostics
logger.info("="*60)
logger.info("CONFIGURATION SERVICE STARTING UP")
logger.info("="*60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")

# Check critical environment variables early
db_url = os.getenv("DATABASE_URL")
gemini_key = os.getenv("GEMINI_API_KEY")

logger.info(f"🔍 Database URL configured: {'✅' if db_url else '❌'}")
logger.info(f"🔍 Gemini API Key configured: {'✅' if gemini_key else '❌'}")

# Get port configuration
PORT = int(os.getenv('CONFIGURATION_SERVICE_PORT', os.getenv('PORT', '8004')))
logger.info(f"🔍 PORT being used: {PORT}")

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events with Railway fixes."""
    try:
        logger.info("🚀 LIFESPAN: Starting application startup sequence")
        service_status.set_status("starting")
        logger.info("🚀 LIFESPAN: Service status set to 'starting'")

        # Validate environment variables
        logger.info("🚀 LIFESPAN: About to validate environment variables")
        try:
            validate_environment()
            logger.info("✅ LIFESPAN: Environment validation successful")
        except ValueError as e:
            logger.error(f"❌ LIFESPAN: Environment validation failed: {e}")
            service_status.set_status("error")
            raise

        # Wait for Railway network initialization
        logger.info("🚀 LIFESPAN: About to wait for Railway network")
        await wait_for_railway_network()
        logger.info("✅ LIFESPAN: Railway network ready")

        # Store database URL for lazy initialization
        database_url = os.getenv("DATABASE_URL")
        logger.info(f"🔍 LIFESPAN: Database URL configured: {'✅' if database_url else '❌'}")

        if database_url:
            # Initialize SQLAlchemy database with retries
            app.state.database_url = database_url
            logger.info("🚀 LIFESPAN: About to initialize SQLAlchemy database")
            
            max_retries = 5
            retry_delay = 2  # seconds
            
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"🔄 LIFESPAN: Database connection attempt {attempt}/{max_retries}")
                    await init_database(database_url)
                    logger.info("✅ LIFESPAN: SQLAlchemy engine initialized")

                    is_valid = await validate_database()
                    if is_valid:
                        logger.info("✅ LIFESPAN: Database schema validated successfully")
                        app.state.database_ready = True
                        break
                    else:
                        logger.warning("⚠️ LIFESPAN: Database schema validation returned False")
                        app.state.database_ready = False
                        if attempt < max_retries:
                            logger.info(f"⏳ LIFESPAN: Retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                except Exception as e:
                    logger.error(f"❌ LIFESPAN: Database connection attempt {attempt} failed: {e}")
                    app.state.database_ready = False
                    
                    if attempt < max_retries:
                        logger.info(f"⏳ LIFESPAN: Retrying in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                    else:
                        import traceback
                        logger.error(f"❌ LIFESPAN: All {max_retries} connection attempts failed")
                        logger.error(f"❌ LIFESPAN: Final error traceback: {traceback.format_exc()}")
                        logger.warning("⚠️ LIFESPAN: Service starting with database unavailable - endpoints will return 503")
        else:
            logger.error("❌ LIFESPAN: DATABASE_URL not set - configuration endpoints will not work")
            app.state.database_url = None
            app.state.database_ready = False
            logger.warning("⚠️ LIFESPAN: Service starting without database - endpoints will return 503")

        service_status.set_status("running")
        logger.info(f"🚀 LIFESPAN: Configuration service started successfully on port {PORT}")
        logger.info("✅ LIFESPAN: Startup complete - yielding to application")
        yield

        # Shutdown
        logger.info("🛑 LIFESPAN: Starting shutdown sequence")
        service_status.set_status("stopping")
        await close_database()
        logger.info("✅ LIFESPAN: Configuration service shutdown complete")
    except Exception as e:
        logger.error(f"❌ LIFESPAN: Error in lifespan handler: {e}")
        import traceback
        logger.error(f"❌ LIFESPAN: Full traceback: {traceback.format_exc()}")
        service_status.set_status("error")
        raise

# Create FastAPI app
app = FastAPI(
    title="Configuration Service",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "configuration")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://digibot-dev.globistaan.com",
        "https://digibot.globistaan.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database readiness check middleware
@app.middleware("http")
async def check_database_ready(request: Request, call_next):
    """Check if database is ready before processing requests."""
    # Skip database check for health endpoint
    if request.url.path == "/health":
        response = await call_next(request)
    else:
        # Check if database is ready for other endpoints
        database_ready = getattr(request.app.state, 'database_ready', False)
        if not database_ready:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service temporarily unavailable - database not ready",
                    "service": "configuration_service"
                }
            )
        response = await call_next(request)

    return response

# Health check endpoint
@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint with database connection verification"""
    # Check if database is ready
    database_ready = getattr(request.app.state, 'database_ready', False)
    
    if not database_ready:
        # Service is up but database is not ready
        return {
            "status": "degraded",
            "service": "configuration_service",
            "database": "unavailable",
            "message": "Service is running but database is not available",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
        }
    
    # Database is ready, check connection
    db_health = await db_health_check()

    # Get overall service status
    service_info = service_status.get_status()
    service_info.update({
        "database": db_health["status"],
        "database_latency_ms": db_health.get("latency_ms", 0),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    })

    return {
        "status": "healthy" if db_health["status"] == "healthy" else "unhealthy",
        "service": "configuration_service",
        "database": db_health["status"],
        "database_latency_ms": db_health.get("latency_ms", 0),
        "timestamp": service_info.get("timestamp")
    }

# Include Routers
app.include_router(config_router, prefix="/api/v1/configuration")

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "configuration", "status": "running"}

logger.info("✅ All endpoints loaded successfully")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
