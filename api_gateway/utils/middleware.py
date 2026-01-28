import time

from fastapi import Request

from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    request_id = f"{int(start_time * 1000000) % 1000000:06d}"

    logger.info(f"📨 [{request_id}] {request.method} {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")

    safe_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ['authorization', 'x-api-key', 'cookie']}
    if safe_headers:
        logger.debug(f"📋 [{request_id}] Headers: {dict(safe_headers)}")

    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        if response.status_code >= 400:
            logger.warning(f"↩️ [{request_id}] Response: {response.status_code} - Path: {request.url.path} - Total time: {duration:.3f}s")
            if response.status_code == 404:
                logger.error(f"❌ 404 DETECTED on path: {request.url.path}")
        else:
            logger.info(f"↩️ [{request_id}] Response: {response.status_code} - Total time: {duration:.3f}s")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 [{request_id}] Request failed after {duration:.3f}s: {e}")
        raise

async def add_security_headers_middleware(request: Request, call_next):
    """Add security headers to prevent COOP/COEP issues with popup windows."""
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response
