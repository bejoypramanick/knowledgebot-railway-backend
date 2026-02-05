"""Utility functions for Docling Service."""
import logging
import os
import signal
import sys
import traceback
import faulthandler
import asyncio
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def setup_global_exception_logging(service_name: str) -> None:
    """Install global exception and signal handlers that log full tracebacks."""
    svc_logger = logging.getLogger(service_name)

    def _excepthook(exc_type, exc_value, exc_tb):
        """Log an uncaught exception with full traceback."""
        try:
            svc_logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        except Exception:
            traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Asyncio exception handler
    try:
        loop = asyncio.get_event_loop()

        def _async_exc_handler(loop, context):
            """Handle unhandled async exceptions."""
            try:
                msg = context.get("message", "Unhandled async exception")
                svc_logger.error(f"Unhandled async exception: {msg}")
                if "exception" in context and context["exception"] is not None:
                    svc_logger.error("Async exception detail:", exc_info=context["exception"])
                else:
                    svc_logger.error(f"Async context: {context}")
            except Exception:
                svc_logger.exception("Failed while logging asyncio exception")

        loop.set_exception_handler(_async_exc_handler)
    except RuntimeError:
        svc_logger.debug("No running asyncio event loop to set exception handler on")

    # Signal handlers for graceful shutdown
    def _signal_handler(signum, frame):
        """Handle shutdown signals."""
        try:
            svc_logger.warning(f"Received signal {signum} - initiating shutdown")
            try:
                faulthandler.dump_traceback(file=sys.stderr)
            except Exception:
                svc_logger.exception("faulthandler failed to dump traceback")
        except Exception:
            svc_logger.exception("Error inside signal handler")
        finally:
            original_handler = original_handlers.get(signum)
            if callable(original_handler):
                original_handler(signum, frame)
            elif original_handler == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

    original_handlers = {}
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            original_handlers[s] = signal.getsignal(s)
            signal.signal(s, _signal_handler)
        except Exception:
            svc_logger.debug(f"Could not register signal handler for {s}")


def register_fastapi_exception_handlers(app: FastAPI, service_name: str) -> None:
    """Register FastAPI exception handler that logs full traceback."""
    svc_logger = logging.getLogger(service_name)

    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception):
        """Global exception handler."""
        svc_logger.error("Unhandled exception during request processing", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred. Check service logs for details."
            },
        )


def log_endpoint_request(service_name: str, endpoint_type: str, request: Request) -> None:
    """Log the full URL of an endpoint request."""
    svc_logger = logging.getLogger(service_name)
    url = str(request.url)
    svc_logger.info(f"🔍 {endpoint_type.capitalize()} check invoked: {url}")
