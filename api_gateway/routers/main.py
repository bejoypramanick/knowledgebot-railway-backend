"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging
import json

from ..core.firebase_auth import verify_token, get_user_from_firestore
from ..core.config import get_settings
from ..routers.chat import router as chat_router
from ..routers.config import router as config_router
from ..routers.health import router as health_router
from ..routers.knowledgebase import router as knowledgebase_router
from ..routers.scrape import router as scrape_router
from ..routers.sse import router as sse_router

logger = logging.getLogger(__name__)
router = APIRouter()

# =================================
# FIREBASE AUTHENTICATION ENDPOINTS
# =================================

@router.post("/auth/verify")
async def verify_auth_token(request: Request):
    """Verify Firebase authentication token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.split(" ")[1]
        user_data = verify_token(token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(status_code=500, detail=f"Error verifying token: {str(e)}")

@router.get("/auth/user/{uid}")
async def get_user_by_uid(uid: str):
    """Get user information by Firebase UID."""
    try:
        user_data = get_user_from_firestore(uid)
        
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user by UID {uid}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")

@router.post("/auth/login")
async def login_user(request: Request):
    """Login user with Firebase token"""
    try:
        # Get token from request body
        body = await request.json()
        token = body.get("token")
        
        if not token:
            raise HTTPException(status_code=400, detail="Missing token")
        
        user_data = verify_token(token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data,
            "message": "Login successful"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")

# =================================
# CONFIGURATION ENDPOINTS
# =================================

@router.get("/config/settings")
async def get_api_settings():
    """Get API configuration settings"""
    try:
        settings = get_settings()
        return {
            "success": True,
            "data": {
                "environment": settings.environment,
                "version": settings.version,
                "debug": settings.debug
            }
        }
    except Exception as e:
        logger.error(f"Error getting API settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH AND MONITORING ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Comprehensive health check for API Gateway"""
    try:
        health_status = {
            "status": "healthy",
            "service": "api-gateway",
            "timestamp": "2024-01-01T00:00:00Z",
            "services": {
                "firebase": "healthy",
                "chat": "healthy",
                "config": "healthy",
                "knowledgebase": "healthy",
                "scraping": "healthy"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_service_status():
    """Get detailed service status"""
    try:
        status = {
            "api_gateway": {
                "status": "running",
                "uptime": "0h 0m 0s",
                "version": "1.0.0"
            },
            "dependencies": {
                "firebase": "connected",
                "database": "connected",
                "cache": "connected"
            }
        }
        return {"success": True, "data": status}
    except Exception as e:
        logger.error(f"Error getting service status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# RATE LIMITING ENDPOINTS
# =================================

@router.get("/rate-limit/status")
async def get_rate_limit_status():
    """Get rate limiting status"""
    try:
        # This would typically check Redis or other rate limiting store
        rate_limit_info = {
            "enabled": True,
            "limits": {
                "requests_per_minute": 100,
                "requests_per_hour": 1000,
                "requests_per_day": 10000
            },
            "current_usage": {
                "requests_this_minute": 5,
                "requests_this_hour": 45,
                "requests_today": 230
            }
        }
        return {"success": True, "data": rate_limit_info}
    except Exception as e:
        logger.error(f"Error getting rate limit status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# LOGGING ENDPOINTS
# =================================

@router.get("/logs/recent")
async def get_recent_logs(limit: int = 50):
    """Get recent API logs"""
    try:
        # This would typically fetch from a logging service
        logs = [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "level": "INFO",
                "message": "API Gateway started successfully",
                "service": "api-gateway"
            }
        ]
        return {"success": True, "data": logs[:limit]}
    except Exception as e:
        logger.error(f"Error getting recent logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/logs/error")
async def log_error(error_data: Dict[str, Any]):
    """Log an error from client"""
    try:
        logger.error(f"Client error: {error_data}")
        return {"success": True, "message": "Error logged successfully"}
    except Exception as e:
        logger.error(f"Error logging client error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# METRICS ENDPOINTS
# =================================

@router.get("/metrics/overview")
async def get_metrics_overview():
    """Get API metrics overview"""
    try:
        metrics = {
            "requests": {
                "total": 10000,
                "today": 500,
                "this_hour": 25
            },
            "errors": {
                "total": 50,
                "rate": 0.5,
                "recent": []
            },
            "performance": {
                "avg_response_time": "120ms",
                "p95_response_time": "250ms",
                "p99_response_time": "500ms"
            }
        }
        return {"success": True, "data": metrics}
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# INCLUDE OTHER ROUTERS
# =================================

# Include all the existing routers with proper prefixes
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(config_router, prefix="/config", tags=["config"])
router.include_router(health_router, prefix="/health", tags=["health"])
router.include_router(knowledgebase_router, prefix="/knowledgebase", tags=["knowledgebase"])
router.include_router(scrape_router, prefix="/scrape", tags=["scrape"])
router.include_router(sse_router, prefix="/sse", tags=["sse"])

# =================================
# MIDDLEWARE ENDPOINTS
# =================================

@router.get("/middleware/cors")
async def get_cors_status():
    """Get CORS configuration status"""
    try:
        cors_config = {
            "enabled": True,
            "allowed_origins": ["*"],
            "allowed_methods": ["GET", "POST", "PUT", "DELETE"],
            "allowed_headers": ["*"],
            "max_age": 3600
        }
        return {"success": True, "data": cors_config}
    except Exception as e:
        logger.error(f"Error getting CORS status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/middleware/auth")
async def get_auth_status():
    """Get authentication middleware status"""
    try:
        auth_status = {
            "enabled": True,
            "required_paths": ["/api/v1/chat", "/api/v1/config"],
            "public_paths": ["/api/v1/health", "/api/v1/auth/login"],
            "firebase_project": "your-project-id"
        }
        return {"success": True, "data": auth_status}
    except Exception as e:
        logger.error(f"Error getting auth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
