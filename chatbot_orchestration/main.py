import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from chatbot_orchestration.routers import router
from chatbot_orchestration.service.agent_service import pydantic_ai_service
from chatbot_orchestration.core.logging_config import auto_configure_logging
from chatbot_orchestration.core.utils import log_endpoint_request

# Configure Railway-compatible logging
logger = auto_configure_logging("chatbot_orchestration")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the Chatbot Orchestration Service.
    Handles startup initialization and shutdown cleanup.
    """
    logger.info("🚀 Chatbot Orchestration Service starting up...")
    
    # Initialize Pydantic AI Service (and DBs lazily)
    await pydantic_ai_service.initialize()
    logger.info("🤖 Pydantic AI Service initialized")
    
    # Initialize database using centralized initializer
    try:
        from chatbot_orchestration.core.database_initializer import database_initializer
        await database_initializer.initialize_database()
        logger.info("🗄️ Database connections initialized (singleton)")
    except Exception as e:
        logger.warning(f"⚠️ Initial database connection check failed: {e}")

    logger.info("✅ Chatbot Orchestration Service fully ready")
    yield
    
    logger.info("🛑 Chatbot Orchestration Service shutting down...")
    # Add cleanup logic here if needed

app = FastAPI(
    title="Chatbot Orchestration Service",
    version="1.0.0",
    lifespan=lifespan
)

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
app.include_router(router, prefix="/api/v1/chatbot")  # Service name as root

@app.get("/")
async def root_diagnostic(request: Request):
    """Simple root endpoint for basic liveliness check."""
    logger.info(f"Root diagnostic check invoked: {request.url}")
    return {"status": "ok", "message": "Chatbot Orchestration Is Alive", "port_env": os.getenv("PORT")}

@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    logger.info(f"Health check invoked: {request.url}")
    log_endpoint_request("chatbot_orchestration", "health", request)
    return {"status": "healthy", "service": "chatbot_orchestration"}

if __name__ == "__main__":
    import uvicorn

    # Port selection order: Service-specific -> Railway PORT -> Default 8003
    port = int(os.getenv("CHATBOT_ORCH_PORT", os.getenv("PORT", "8003")))
    logger.info(f"🚀 Starting chatbot_orchestration service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
