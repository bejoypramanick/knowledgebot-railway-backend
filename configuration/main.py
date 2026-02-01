"""
Configuration Service - Handles chatbot and widget configuration management
"""
import datetime
import sys
import os

# VERY EARLY LOGGING - Before any other imports
print("🚀 CONFIGURATION SERVICE: STARTING EXECUTION - VERSION 3.0")
print(f"🚀 Python version: {sys.version}")
print(f"🚀 Working directory: {os.getcwd()}")
print(f"🚀 Script location: {__file__}")

# Configure Shared Telemetry
import logging
from contextlib import asynccontextmanager
from shared.telemetry import setup_telemetry, instrument_fastapi

# Initialize Telemetry
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("configuration")
logger = logging.getLogger("configuration")

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
from configuration.core.database_initializer import database_initializer
from configuration.core.db import close_databases, railway_db
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
db_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
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
        database_url = (
            os.getenv("DATABASE_URL") or
            os.getenv("RAILWAY_POSTGRES_URL") or
            os.getenv("POSTGRES_URL")
        )
        logger.info(f"🔍 LIFESPAN: Database URL configured: {'✅' if database_url else '❌'}")

        if database_url:
            # Initialize database connection pool using centralized initializer
            app.state.database_url = database_url
            logger.info("🚀 LIFESPAN: About to initialize database")
            try:
                await database_initializer.initialize_and_validate(database_url)
                logger.info("✅ LIFESPAN: Database initialized and validated")
            except Exception as e:
                logger.error(f"❌ LIFESPAN: Failed to initialize database: {e}")
                import traceback
                logger.error(f"❌ LIFESPAN: Database error traceback: {traceback.format_exc()}")
                # Don't fail startup, but log the error
        else:
            logger.error("❌ LIFESPAN: DATABASE_URL not set - configuration endpoints will not work")
            app.state.database_url = None
            service_status.set_status("error")
            raise ValueError("Database URL not configured")

        service_status.set_status("running")
        logger.info(f"🚀 LIFESPAN: Configuration service started successfully on port {PORT}")
        logger.info("✅ LIFESPAN: Startup complete - yielding to application")
        yield

        # Shutdown
        logger.info("🛑 LIFESPAN: Starting shutdown sequence")
        service_status.set_status("stopping")
        await close_databases()
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

# COOP/COEP headers middleware to fix Cross-Origin-Opener-Policy issues
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to prevent COOP/COEP issues with popup windows."""
    response = await call_next(request)
    
    # Set COOP and COEP headers to allow popup operations without restrictions
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    
    return response

# Health check endpoint
@app.get("/health")
async def health_check():
    """Shallow health check endpoint optimized for serverless - avoids DB queries to prevent keeping instances awake"""
    # Simple service health check without database queries
    # This prevents frequent health checks from keeping serverless instances awake unnecessarily
    
    # Basic service status - no DB queries for shallow check
    db_status = "not_checked"  # Shallow check doesn't query DB
    
    # Only check DB connection status without querying
    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        db_status = "connected"
    else:
        db_status = "disconnected"

    # Get overall service status
    service_info = service_status.get_status()
    service_info.update({
        "database": db_status,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    })

    return {
        "status": "healthy" if db_status in ["connected", "not_checked"] else "unhealthy",
        "service": "configuration_service",
        "database": db_status,
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
