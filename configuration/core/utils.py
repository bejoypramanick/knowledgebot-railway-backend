"""Shared utility functions."""
import asyncio
import faulthandler
import logging
import os
import signal
import sys
import time
import traceback
from typing import Any, Dict, Optional

import httpx
import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# Enhanced retry configuration for Railway network issues
class RetryConfig:
    """Configuration for retry logic."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter


def retry_with_backoff(
    config: Optional[RetryConfig] = None,
    exceptions: tuple = (Exception,)
) -> callable:
    """
    Decorator that implements exponential backoff retry logic.

    Specifically designed for Railway's network initialization delays.
    """
    if config is None:
        config = RetryConfig()

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == config.max_attempts - 1:
                        # Last attempt failed
                        logger.error(f"❌ All {config.max_attempts} attempts failed for {func.__name__}: {e}")
                        raise e

                    # Calculate delay with exponential backoff
                    delay = min(
                        config.initial_delay * (config.backoff_factor ** attempt),
                        config.max_delay
                    )

                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        import random
                        delay = delay * (0.5 + random.random() * 0.5)

                    logger.warning(f"⚠️ Attempt {attempt + 1}/{config.max_attempts} failed for {func.__name__}: {e}. Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)

            # This should never be reached, but just in case
            raise last_exception

        return wrapper
    return decorator


# Handle asyncpg import at module level to avoid NameError during import
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False
    # Create a dummy asyncpg module to avoid NameError
    class DummyAsyncpg:
        class exceptions:
            class PostgresError(Exception):
                pass
    asyncpg = DummyAsyncpg()

# Pre-configured retry decorators for common scenarios
retry_database_operation = retry_with_backoff(
    config=RetryConfig(
        max_attempts=5,
        initial_delay=0.5,
        max_delay=10.0,
        backoff_factor=1.5
    ),
    exceptions=(RuntimeError, ConnectionError, asyncio.TimeoutError, asyncpg.exceptions.PostgresError)
)

retry_network_operation = retry_with_backoff(
    config=RetryConfig(
        max_attempts=3,
        initial_delay=2.0,
        max_delay=15.0,
        backoff_factor=2.0
    ),
    exceptions=(ConnectionError, asyncio.TimeoutError, OSError)
)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=10))
async def make_service_request(
    method: str,
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """Make HTTP request to internal service."""
    headers = {}
    logger.info(f"🔍 Making {method} request to {url}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            
            logger.info(f"🔍 Received response from {url} (Status: {response.status_code})")
            
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")
            raise


def dependency_unavailable_error(dependency_name: str, reason: Optional[str] = None) -> HTTPException:
    """Return a standardized HTTPException for missing/unavailable dependencies.

    Response JSON format:
    {
      "error": "dependency_unavailable",
      "dependency": "gemini",
      "message": "Gemini client not configured",
      "reason": "optional underlying reason"
    }
    """
    payload = {
        "error": "dependency_unavailable",
        "dependency": dependency_name,
        "message": f"{dependency_name} is not configured or unavailable",
    }
    if reason:
        payload["reason"] = str(reason)

    return HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=payload)


def setup_global_exception_logging(service_name: str) -> None:
    """Install global exception and signal handlers that log full tracebacks.

    This configures:
    - sys.excepthook to log uncaught exceptions
    - asyncio event loop exception handler to capture async errors
    - SIGTERM / SIGINT handlers that dump python tracebacks for diagnostics
    """
    # Use standard logger with OpenTelemetry integration
    svc_logger = logging.getLogger(service_name)

    def _excepthook(exc_type, exc_value, exc_tb):
        # Log an uncaught exception with full traceback
        try:
            svc_logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        except Exception:
            # Fallback to printing if logging fails
            traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Asyncio exception handler
    try:
        loop = asyncio.get_event_loop()

        def _async_exc_handler(loop, context):
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
        # Event loop may not exist yet
        svc_logger.debug("No running asyncio event loop to set exception handler on")

    # Signal handlers to capture shutdown requests
    def _signal_handler(signum, frame):
        try:
            svc_logger.warning(f"Received signal {signum} - initiating shutdown; dumping tracebacks for diagnostics")
            # Dump traceback of all threads to stderr (faulthandler is robust)
            try:
                faulthandler.dump_traceback(file=sys.stderr)
            except Exception:
                svc_logger.exception("faulthandler failed to dump traceback")
        except Exception:
            svc_logger.exception("Error inside signal handler")
        finally:
            # Chain to the original handler to ensure graceful shutdown
            original_handler = original_handlers.get(signum)
            if callable(original_handler):
                original_handler(signum, frame)
            elif original_handler == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            elif original_handler == signal.SIG_IGN:
                pass

    original_handlers = {}
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            original_handlers[s] = signal.getsignal(s)
            signal.signal(s, _signal_handler)
        except Exception:
            # Some environments (Windows, restricted containers) may not allow setting signals
            svc_logger.debug(f"Could not register signal handler for {s}")


def register_fastapi_exception_handlers(app: FastAPI, service_name: str) -> None:
    """Register a FastAPI exception handler that logs full traceback and returns a safe JSON response.

    Use this to ensure request-scoped exceptions are logged with stack traces.
    """
    svc_logger = logging.getLogger(service_name)

    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception):
        svc_logger.error("Unhandled exception during request processing", exc_info=True)
        # Return a minimal safe JSON payload to callers
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred. Check service logs for details."
            },
        )


def log_system_metrics(service_name: str) -> None:
    """Log system memory and CPU usage metrics for a given service.

    Args:
        service_name: Name of the service for logging context.
    """
    svc_logger = logging.getLogger(service_name)
    try:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        svc_logger.info(f"📊 System Metrics for {service_name}:")
        svc_logger.info(f"  Memory: {memory.used / (1024 ** 2):.2f} MB / {memory.total / (1024 ** 2):.2f} MB ({memory.percent}%)")
        svc_logger.info(f"  CPU Usage: {cpu}%")
    except Exception as e:
        svc_logger.error(f"Error logging system metrics: {e}")


def log_endpoint_request(service_name: str, endpoint_type: str, request: Request) -> None:
    """Log the full URL of an endpoint request for health and readiness checks.

    Args:
        service_name: Name of the service.
        endpoint_type: Type of endpoint (e.g., 'health', 'ready').
        request: FastAPI Request object.
    """
    svc_logger = logging.getLogger(service_name)
    url = str(request.url)
    svc_logger.info(f"🔍 {endpoint_type.capitalize()} check invoked: {url}")


async def wait_for_railway_network() -> None:
    """
    Wait for Railway's private network to initialize.

    Railway's private networks can take up to 3 seconds to initialize.
    """
    logger.info("⏳ Waiting for Railway network initialization...")
    await asyncio.sleep(3)
    logger.info("✅ Railway network initialization delay complete")


def validate_environment() -> None:
    """Validate required environment variables."""
    # Use local configuration instead of importing from api_gateway
    import os
    
    required_vars = []
    
    # Check for database URL
    if not os.getenv('RAILWAY_POSTGRES_URL') and not os.getenv('DATABASE_URL'):
        required_vars.append('DATABASE_URL or RAILWAY_POSTGRES_URL')
    
    # Check for Gemini API key
    if not os.getenv('GEMINI_API_KEY'):
        required_vars.append('GEMINI_API_KEY')

    if required_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(required_vars)}")

    # Log configuration status
    gemini_configured = os.getenv('GEMINI_API_KEY') is not None
    db_configured = os.getenv('RAILWAY_POSTGRES_URL') or os.getenv('DATABASE_URL')
    logger.info(f"INFO:main:GEMINI_API_KEY configured: {'YES' if gemini_configured else 'NO'}")
    logger.info(f"INFO:main:DATABASE_URL configured: {'YES' if db_configured else 'NO'}")


class GracefulShutdown:
    """Handles graceful shutdown with signal handling."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self._shutdown_handlers: list = []

    def add_shutdown_handler(self, handler):
        """Add a shutdown handler function."""
        self._shutdown_handlers.append(handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.warning(f"Received signal {signum} ({signal_name}) - initiating shutdown; dumping tracebacks for diagnostics")

        # Log current stack traces for debugging
        import threading
        import traceback

        logger.info("Current thread dump:")
        for thread in threading.enumerate():
            logger.info(f"Thread {thread.name} (ident: {thread.ident}):")
            if thread.is_alive():
                # Get stack trace for alive threads
                stack = traceback.format_stack(sys._current_frames().get(thread.ident))
                logger.info("".join(stack))

        # Set shutdown event
        self.shutdown_event.set()

    async def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Wait for shutdown event
        await self.shutdown_event.wait()

        # Execute shutdown handlers
        logger.info("🛑 Executing shutdown handlers...")
        for handler in self._shutdown_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    await asyncio.get_event_loop().run_in_executor(None, handler)
            except Exception as e:
                logger.error(f"Error in shutdown handler: {e}")

        logger.info("✅ All shutdown handlers completed")


# Global shutdown handler
shutdown_handler = GracefulShutdown()


class ServiceStatus:
    """Service status tracking."""

    def __init__(self):
        self._status = "initializing"
        self._start_time = time.time()
        self._stats: Dict[str, Any] = {}

    def set_status(self, status: str):
        """Set the current service status."""
        self._status = status
        logger.info(f"Service status changed to: {status}")

    def get_status(self) -> Dict[str, Any]:
        """Get current service status."""
        return {
            "status": self._status,
            "uptime": time.time() - self._start_time,
            "stats": self._stats
        }

    def update_stats(self, key: str, value: Any):
        """Update service statistics."""
        self._stats[key] = value


# Global service status
service_status = ServiceStatus()
