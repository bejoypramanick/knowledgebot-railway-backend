import os
import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from shared.config import settings
from shared.utils import log_endpoint_request
from services.chatbot_orchestration.agent.service import pydantic_ai_service
from services.chatbot_orchestration.routers import chat
from services.chatbot_orchestration.core.database import get_railway_db, get_neon_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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
    
    # Trigger lazy DB init to ensure connections are warm
    try:
        await get_railway_db()
        await get_neon_db()
        logger.info("🗄️ Database connections initialized")
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
app.include_router(chat.router)

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
