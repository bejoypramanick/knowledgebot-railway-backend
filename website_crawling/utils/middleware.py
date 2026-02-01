import time
import logging

from fastapi import Request

logger = logging.getLogger(__name__)

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log all incoming requests."""
    start_time = time.time()
    logger.info(f"📨 {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"↩️ {response.status_code} - {duration:.3f}s")
        return response
    except Exception as e:
        logger.error(f"💥 Request failed: {e}")
        raise
