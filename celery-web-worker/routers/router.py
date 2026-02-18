"""
Internal API endpoints for web worker service
Only /health endpoint is exposed (health checks from other services)
All task processing happens via Redis polling
"""
from fastapi import APIRouter
from shared.otel_logger import get_otel_logger
from shared.redis_message_queue import redis_message_queue

logger = get_otel_logger("internal_router", "celery-web-worker")
router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/health")
async def health_check():
    """Health check endpoint for internal use"""
    return {
        "status": "healthy",
        "service": "celery-web-worker",
        "redis_available": redis_message_queue.is_available(),
        "mode": "Redis-polling"
    }
