"""
OpenTelemetry Logging Utilities for API Gateway Service
Provides structured logging with OTel span context integration
"""
import logging
import sys
from typing import Dict, Any, Optional
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

class OpenTelemetryLogger:
    """Enhanced logger with OpenTelemetry integration for Railway"""

    def __init__(self, name: str, service_name: str):
        self.logger = logging.getLogger(name)
        self.service_name = service_name
        self.tracer = trace.get_tracer(f"{service_name}.{name}")

    def _get_span_context(self) -> Optional[Dict[str, Any]]:
        """Get current span context for logging"""
        span = trace.get_current_span()
        if span and span.is_recording():
            return {
                "trace_id": format(span.get_span_context().trace_id, "032x"),
                "span_id": format(span.get_span_context().span_id, "032x")
            }
        return None

    def _log_with_context(self, level: int, message: str, extra: Dict[str, Any] = None):
        """Log message with OpenTelemetry context using standard logging"""
        # Use the standard logger which will automatically include otelTraceID and otelSpanID
        # due to the LoggingInstrumentor setup in shared/telemetry.py
        self.logger.log(level, message, extra=extra or {})

        # Add span attributes if span exists
        span = trace.get_current_span()
        if span and span.is_recording():
            # Add log entry as span event
            span.add_event(
                name="log",
                attributes={
                    "log.level": logging.getLevelName(level),
                    "log.message": message,
                    "log.logger": self.logger.name
                }
            )

    def info(self, message: str, **kwargs):
        """Info level log with OTel context"""
        self._log_with_context(logging.INFO, message, kwargs)

    def error(self, message: str, **kwargs):
        """Error level log with OTel context"""
        self._log_with_context(logging.ERROR, message, kwargs)
        # Set span status to error
        span = trace.get_current_span()
        if span:
            span.set_status(Status(StatusCode.ERROR, message))

    def warning(self, message: str, **kwargs):
        """Warning level log with OTel context"""
        self._log_with_context(logging.WARNING, message, kwargs)

    def debug(self, message: str, **kwargs):
        """Debug level log with OTel context"""
        self._log_with_context(logging.DEBUG, message, kwargs)

    def critical(self, message: str, **kwargs):
        """Critical level log with OTel context"""
        self._log_with_context(logging.CRITICAL, message, kwargs)
        # Set span status to error
        span = trace.get_current_span()
        if span:
            span.set_status(Status(StatusCode.ERROR, message))

    def log_file_search_operation(self, operation: str, store_id: str = None, details: Dict[str, Any] = None):
        """Log FileSearch store operations with OTel context"""
        span = trace.get_current_span()
        if span:
            span.set_attribute("file_search.operation", operation)
            if store_id:
                span.set_attribute("file_search.store_id", store_id)
            if details:
                for key, value in details.items():
                    span.set_attribute(f"file_search.{key}", str(value))

        # Also log to console with context
        msg = f"FileSearch | Operation: {operation}"
        if store_id:
            msg += f" | Store: {store_id}"
        if details:
            msg += f" | Details: {details}"
        self.info(msg)

def get_otel_logger(name: str, service_name: str) -> OpenTelemetryLogger:
    """Get OpenTelemetry-enhanced logger for API Gateway service"""
    return OpenTelemetryLogger(name, service_name)
