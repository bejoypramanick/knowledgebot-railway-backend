"""
Configuration Service - Handles chatbot and widget configuration management
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import datetime
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

from shared.db import close_databases, railway_db
from shared.utils import validate_environment, wait_for_railway_network, service_status
from shared.firebase_auth import init_firebase_auth
from shared.database_initializer import database_initializer

# Import Routers
from configuration.routers import chatbot, widget
from configuration.human_agents import router as human_agents_router
from configuration.feedback import router as feedback_router
from configuration.token_usage import router as token_usage_router
from configuration.performance import router as performance_router
from configuration.admin_management import router as admin_management_router
from configuration.auth_optimized import router as auth_router
from configuration.chat_log import router as chat_log_router, public_chat_router
from configuration.user_ids import router as user_ids_router

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)
logger = logging.getLogger(__name__)

# Log startup diagnostics
logger.info("="*60)
logger.info("CONFIGURATION SERVICE STARTING UP")
logger.info("="*60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")

# Get port configuration
PORT = int(os.getenv('CONFIGURATION_SERVICE_PORT', os.getenv('PORT', '8004')))
logger.info(f"PORT being used: {PORT}")

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events with Railway fixes."""
    try:
        service_status.set_status("starting")

        # Validate environment variables
        try:
            validate_environment()
        except ValueError as e:
            logger.error(f"❌ Environment validation failed: {e}")
            service_status.set_status("error")
            raise

        # Wait for Railway network initialization
        await wait_for_railway_network()

        # Store database URL for lazy initialization
        database_url = (
            os.getenv("DATABASE_URL") or
            os.getenv("RAILWAY_POSTGRES_URL") or
            os.getenv("POSTGRES_URL")
        )

        if database_url:
            # Initialize database connection pool using centralized initializer
            app.state.database_url = database_url
            try:
                await database_initializer.initialize_and_validate(database_url)
                logger.info("✅ Database initialized and validated")
            except Exception as e:
                logger.error(f"❌ Failed to initialize database: {e}")
                # Don't fail startup, but log the error
        else:
            logger.error("❌ DATABASE_URL, RAILWAY_POSTGRES_URL, or POSTGRES_URL not set - configuration endpoints will not work")
            app.state.database_url = None
            service_status.set_status("error")
            raise ValueError("Database URL not configured")

        # Initialize Firebase Auth and Firestore
        try:
            init_firebase_auth()
            logger.info("✅ Firebase Auth and Firestore initialized")
        except Exception as e:
            logger.warning(f"⚠️ Firebase Auth/Firestore not initialized: {e}")
            logger.warning("Authentication endpoints will not work without Firebase")

        service_status.set_status("running")
        logger.info(f"🚀 Configuration service started successfully on port {PORT}")
        yield

        # Shutdown
        service_status.set_status("stopping")
        await close_databases()
        logger.info("✅ Configuration service shutdown complete")
    except Exception as e:
        service_status.set_status("error")
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

# Create FastAPI app
app = FastAPI(
    title="Configuration Service",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    # I'll rely on service_status.get_status() being correct generally.

    return {
        "status": "healthy" if db_status in ["connected", "not_checked"] else "unhealthy",
        "service": "configuration_service",
        "database": db_status,
        "timestamp": service_info.get("timestamp")
    }

# Include Routers
app.include_router(chatbot.router)
app.include_router(widget.router)
app.include_router(human_agents_router)
app.include_router(feedback_router)
app.include_router(token_usage_router)
app.include_router(admin_management_router)
app.include_router(auth_router)
app.include_router(performance_router)
app.include_router(chat_log_router)
app.include_router(user_ids_router)
app.include_router(public_chat_router)

logger.info("✅ All endpoints loaded successfully")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
