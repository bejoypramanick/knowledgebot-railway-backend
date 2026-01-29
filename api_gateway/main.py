import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configure Railway-compatible logging
from api_gateway.core.logging_config import auto_configure_logging

logger = auto_configure_logging("api_gateway")

from api_gateway.core.config import SERVICE_IDENTITY
# Import routers and config
from api_gateway.routers import (chat_router, config_router, health_router,
                                 knowledgebase_router, scrape_router,
                                 sse_router)
from api_gateway.utils.middleware import (add_security_headers_middleware,
                                          log_requests_middleware)
from api_gateway.core.correlation_middleware import CorrelationIDMiddleware
from api_gateway.core.utils import (register_fastapi_exception_handlers,
                          setup_global_exception_logging)

setup_global_exception_logging("api_gateway")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Startup
        logger.info(f"🚀 API Gateway ({SERVICE_IDENTITY}) started successfully")
        yield
        # Shutdown
        logger.info("🛑 API Gateway shutting down")
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledge Bot API Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# Store start time
app.start_time = time.time()

register_fastapi_exception_handlers(app, "api_gateway")

# Middleware
app.middleware("http")(log_requests_middleware)
app.add_middleware(CorrelationIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": "Validation failed", "errors": str(exc)}
    )

# Endpoints
@app.get("/gateway-check")
async def gateway_check():
    """Direct diagnostic route to verify Gateway is responding."""
    return {
        "status": "online",
        "message": "API Gateway is responding directly",
        "timestamp": time.time(),
        "env_port": os.getenv("PORT"),
        "orchestration_url": os.getenv("CHATBOT_ORCHESTRATION_URL")
    }

@app.post("/chat")
async def chatbot_bypass_diagnostic(request: Request):
    """NUCLEAR DIAGNOSTIC BYPASS: Detects service confusion."""
    logger.error("🛑 CRITICAL: Service Confusion Detected!")
    return JSONResponse(
        status_code=418,
        content={
            "error": "Service Confusion Detected",
            "identity": SERVICE_IDENTITY,
            "message": "This is the API Gateway, but you called /chat (the Chatbot route). This proves Railway is misrouting your deployment.",
            "suggestion": "Check Railway UI -> Chatbot Service -> Settings -> Dockerfile Path. Ensure it points to 'services/chatbot_orchestration/Dockerfile'."
        }
    )

# Include Routers
app.include_router(health_router)
app.include_router(knowledgebase_router, prefix="/api/v1/knowledgebase")
app.include_router(scrape_router, prefix="/api/v1")
app.include_router(chat_router) # Chat router has mixed prefixes, so we include it directly
app.include_router(config_router, prefix="/api/v1")
app.include_router(sse_router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_GATEWAY_PORT", os.getenv("PORT", "8080")))
    logger.info(f"🚀 Starting API Gateway on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)