import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Configure OpenTelemetry for Railway
# Configure Shared Telemetry
import logging
from shared.telemetry import setup_telemetry, instrument_fastapi

# Initialize Telemetry
# Use default behavior (span exporter disabled by default via env var)
setup_telemetry("chatbot-orchestration")
logger = logging.getLogger("chatbot_orchestration")

from chatbot_orchestration.routers import router
from chatbot_orchestration.service.agent_service import pydantic_ai_service
from chatbot_orchestration.core.utils import log_endpoint_request
from shared.file_search import get_file_search_store_by_display_name

# Global variable to cache resolved FileSearch store ID
_resolved_store_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the Chatbot Orchestration Service.
    Handles startup initialization and shutdown cleanup.
    """
    try:
        # Log environment variables for debugging
        logger.info("🔧 Environment Variables Check:")
        gemini_key_status = "✅ Set" if os.getenv('GEMINI_API_KEY') else "❌ Missing"
        logger.info(f"   GEMINI_API_KEY: {gemini_key_status}")
        logger.info(f"   CHATBOT_MODEL: {os.getenv('CHATBOT_MODEL', 'Not set')}")
        logger.info(f"   GEMINI_FILE_SEARCH_STORE_NAME: {os.getenv('GEMINI_FILE_SEARCH_STORE_NAME', 'Not set')}")
        
        # Initialize Gemini Client (Check)
        from chatbot_orchestration.core.ai import get_genai_client
        if get_genai_client():
             logger.info("✅ Gemini client initialized")
        else:
             logger.warning("⚠️ Gemini client failed to initialize")

        # Initialize Gemini Model (Check)
        from chatbot_orchestration.core.ai import get_gemini_model
        if get_gemini_model():
             logger.info("✅ Gemini model initialized")
        else:
             logger.warning("⚠️ Gemini model failed to initialize")

        # Note: FileSearch store is created by API Gateway during startup
        # Read display_name from environment variable and look it up
        store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")
        logger.info(f"📂 Looking for FileSearch store by display_name: {store_display_name}")

        # Lookup store by display name using shared utility
        global _resolved_store_id
        try:
            genai_client = get_genai_client()
            if genai_client:
                _resolved_store_id = get_file_search_store_by_display_name(
                    genai_client,
                    display_name=store_display_name
                )
                if _resolved_store_id:
                    logger.info(f"✅ Resolved FileSearch store ID: {_resolved_store_id}")
                else:
                    logger.error(f"❌ FileSearch store not found with display_name: {store_display_name}")
                    logger.error("   Please ensure API Gateway has initialized FileSearch stores")
            else:
                logger.error("❌ Gemini client not available for FileSearch lookup")
        except Exception as lookup_error:
            logger.error(f"❌ Error looking up FileSearch store: {lookup_error}")

        logger.info("🚀 Chatbot orchestration service started successfully")
        yield
        
        logger.info("🛑 Chatbot orchestration service shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

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
