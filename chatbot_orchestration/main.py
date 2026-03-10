import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Configure OpenTelemetry for Railway
# Configure Shared Telemetry
import logging
from shared.otel_logger import get_otel_logger
from shared.telemetry import setup_telemetry, instrument_fastapi
from shared.sqlalchemy_db import close_database, health_check as db_health_check
from shared.db_retry import initialize_database_with_retry

# Initialize Telemetry
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("chatbot-orchestration")
logger = logging.getLogger("chatbot_orchestration")

from chatbot_orchestration.routers import router
from chatbot_orchestration.service.agent_service import PydanticAIGatewayService

# Create service instance
pydantic_ai_service = PydanticAIGatewayService()
from chatbot_orchestration.core.utils import log_endpoint_request

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the Chatbot Orchestration Service.
    Handles startup initialization and shutdown cleanup.
    """
    # Startup
    logger.info("🚀 Chatbot Orchestration Service starting up...")

    # Initialize Pydantic AI Service (and DBs lazily)
    await pydantic_ai_service.initialize()
    logger.info("🤖 Pydantic AI Service initialized")

    # Initialize SQLAlchemy database with centralized retry logic
    # Uses shared db_retry module for consistent Railway-ready retry behavior
    database_url = os.getenv("DATABASE_URL")
    await initialize_database_with_retry(database_url, service_name="chatbot-orchestration")

    logger.info("✅ Chatbot Orchestration Service fully ready")
    yield

    logger.info("🛑 Chatbot Orchestration Service shutting down...")
    try:
        await close_database()
        logger.info("✅ Database closed")
    except Exception as e:
        logger.error(f"❌ Error closing database: {e}")

app = FastAPI(
    title="Chatbot Orchestration Service",
    version="1.0.0",
    description="Handles chatbot logic, AI interactions, and response generation",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Instrument FastAPI for OpenTelemetry immediately after app creation
instrument_fastapi(app, "chatbot-orchestration")

# CORS Middleware
# Allow all origins in production for simplicity, or restrict as needed
origins = [
    "http://localhost:3000",
    "http://localhost:8003",
    "https://knowledgebot-railway-backend-production.up.railway.app",
    "https://configuration-service-production.up.railway.app",
    "*"  # Allow all for now to avoid CORS issues
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(router, prefix="/api/v1/chatbot")

@app.get("/")
async def root_diagnostic(request: Request):
    """Simple root endpoint for basic liveliness check."""
    logger.info(f"Root diagnostic check invoked: {request.url}")
    return {"status": "ok", "message": "Chatbot Orchestration Is Alive", "port_env": os.getenv("PORT")}

@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint with database verification."""
    logger.info(f"Health check invoked: {request.url}")
    log_endpoint_request("chatbot_orchestration", "health", request)
    db_health = await db_health_check()
    return {
        "status": "healthy" if db_health["status"] == "healthy" else "unhealthy",
        "service": "chatbot_orchestration",
        "database": db_health["status"],
        "database_latency_ms": db_health.get("latency_ms", 0)
    }

if __name__ == "__main__":
    import uvicorn

    # Port selection order: Service-specific -> Railway PORT -> Default 8003
    port = int(os.getenv("CHATBOT_ORCH_PORT", os.getenv("PORT", "8003")))
    logger.info(f"🚀 Starting chatbot_orchestration service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
