import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configure Railway-compatible logging
from api_gateway.core.logging_config import auto_configure_logging

logger = auto_configure_logging("api_gateway")

from api_gateway.core.config import get_settings
from api_gateway.core.auth_middleware import get_current_user
# Import routers and config
from api_gateway.routers import router as api_router
try:
    from chatbot_orchestration.routers import router as chat_router
except ImportError:
    # Fallback if running in different context
    chat_router = None
    logger.warning("Could not import chatbot_orchestration router - running in standalone mode")
try:
    from configuration.routers import router as config_router
except ImportError:
    # Fallback if running in different context
    config_router = None
    logger.warning("Could not import configuration router - running in standalone mode")
try:
    from knowledgebase_ingestion.routers import router as knowledgebase_router
except ImportError:
    # Fallback if running in different context
    knowledgebase_router = None
    logger.warning("Could not import knowledgebase_ingestion router - running in standalone mode")
try:
    from website_crawling.routers import router as webcrawl_router
except ImportError:
    # Fallback if running in different context
    webcrawl_router = None
    logger.warning("Could not import website_crawling router - running in standalone mode")
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
        settings = get_settings()
        # Startup
        logger.info(f"🚀 API Gateway ({settings.service_identity}) started successfully")
        yield
        # Shutdown
        logger.info("🛑 API Gateway shutting down")
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledge Bot API Gateway",
    version="1.0.0",
    description="API Gateway for Knowledge Bot microservices",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add Firebase authentication middleware
class FirebaseAuthMiddleware(BaseHTTPMiddleware):
    """Firebase Authentication Middleware"""
    def __init__(self, app, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/",
            "/health",
            "/gateway/health",
            "/api/v1/gateway/configuration/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/auth/login",
            "/auth/verify"
        ]
    
    async def dispatch(self, request, call_next):
        # Skip auth for excluded paths and any health endpoint
        path = request.url.path
        if (path in self.exclude_paths or 
            path.endswith("/health") or 
            request.method == "OPTIONS"):
            return await call_next(request)
        
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authorization header"},
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Verify token and add user to request state
        token = auth_header.split(" ")[1]
        try:
            from api_gateway.core.firebase_auth import verify_firebase_token
            user_data = verify_firebase_token(token)
            if not user_data:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid token"}
                )
            request.state.user = user_data
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": f"Authentication failed: {str(e)}"}
            )
        
        try:
            return await call_next(request)
        except Exception as e:
            # Catch any other exceptions that might occur during request processing
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )

# Add middleware to app
app.add_middleware(FirebaseAuthMiddleware)

register_fastapi_exception_handlers(app, "api_gateway")

# Middleware
app.middleware("http")(log_requests_middleware)
app.add_middleware(CorrelationIDMiddleware)

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
async def chat_confusion_detector(request: Request):
    """Detect if Railway is misrouting the chatbot service to the API Gateway."""
    settings = get_settings()
    return JSONResponse(
        status_code=418,
        content={
            "error": "Service Confusion Detected",
            "identity": settings.service_identity,
            "message": "This is the API Gateway, but you called /chat (the Chatbot route). This proves Railway is misrouting your deployment.",
            "suggestion": "Check Railway UI -> Chatbot Service -> Settings -> Dockerfile Path. Ensure it points to 'services/chatbot_orchestration/Dockerfile'."
        }
    )

# Include Routers
app.include_router(api_router, prefix="/api/v1/gateway") 

# Add app-level endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "api_gateway", "status": "running"}

@app.get("/health")
async def root_health_check():
    """Root health check endpoint"""
    return {"status": "healthy", "service": "api_gateway", "version": "1.0.0"}

# Also keep /gateway/health for backward compatibility
@app.get("/gateway/health")
async def legacy_health_check():
    """Legacy health check endpoint"""
    return {"status": "healthy", "service": "api_gateway", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_GATEWAY_PORT", os.getenv("PORT", "8080")))
    logger.info(f"🚀 Starting API Gateway on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)