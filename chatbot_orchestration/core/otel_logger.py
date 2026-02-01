"""
OpenTelemetry Logging Utilities for Chatbot Orchestration Service
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
    
    def log_db_query(self, query: str, params: Dict[str, Any] = None, result: Any = None, error: Exception = None):
        """Log database query with OTel context"""
        span = trace.get_current_span()
        if span:
            span.set_attribute("db.query", query)
            if params:
                span.set_attribute("db.params", str(params))
            if result:
                if hasattr(result, '__len__'):
                    span.set_attribute("db.rows_affected", len(result))
                else:
                    span.set_attribute("db.result", str(result))
            if error:
                span.set_status(Status(StatusCode.ERROR, str(error)))
                span.record_exception(error)
        
        # Also log to console with context
        if error:
            self.error(f"DB Query Error: {query[:100]}... | Error: {error}")
        else:
            self.info(f"DB Query: {query[:100]}... | Rows: {len(result) if result and hasattr(result, '__len__') else 'N/A'}")

def get_otel_logger(name: str, service_name: str) -> OpenTelemetryLogger:
    """Get OpenTelemetry-enhanced logger for chatbot orchestration service"""
    return OpenTelemetryLogger(name, service_name)
