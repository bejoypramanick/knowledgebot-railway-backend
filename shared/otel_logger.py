"""
Unified OpenTelemetry Logging Utilities
Provides structured logging with OTel span context integration for all services
"""
import logging
from typing import Dict, Any, Optional
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

class OpenTelemetryLogger:
    """Enhanced logger with OpenTelemetry integration for Railway"""
    
    def __init__(self, name: str, service_name: str):
        self.logger = logging.getLogger(name)
        self.service_name = service_name
        self.tracer = trace.get_tracer(f"{service_name}.{name}")
        
    def _log_with_context(self, level: int, message: str, extra: Dict[str, Any] = None):
        """Log message with OpenTelemetry context using standard logging"""
        # Standard logger automatically includes otelTraceID and otelSpanID 
        # from shared/telemetry.py LoggingInstrumentor
        self.logger.log(level, message, extra=extra or {})
        
        # Add span attributes if span exists
        span = trace.get_current_span()
        if span and span.is_recording():
            span.add_event(
                name="log",
                attributes={
                    "log.level": logging.getLevelName(level),
                    "log.message": message,
                    "log.logger": self.logger.name,
                    "service.name": self.service_name
                }
            )
    
    def info(self, message: str, **kwargs):
        self._log_with_context(logging.INFO, message, kwargs)
    
    def error(self, message: str, **kwargs):
        self._log_with_context(logging.ERROR, message, kwargs)
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_status(Status(StatusCode.ERROR, message))
    
    def warning(self, message: str, **kwargs):
        self._log_with_context(logging.WARNING, message, kwargs)
    
    def debug(self, message: str, **kwargs):
        self._log_with_context(logging.DEBUG, message, kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log_with_context(logging.CRITICAL, message, kwargs)
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_status(Status(StatusCode.ERROR, message))

    def log_db_operation(self, query: str, params: Any = None):
        """Log database operation BEFORE execution"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("db.query", query)
            if params:
                span.set_attribute("db.params", str(params))
        
        # Also log to console
        param_str = f" | Params: {params}" if params else ""
        self.info(f"🔍 DB Executing: {query}{param_str}")

    def log_db_query(self, query: str, params: Any = None, result: Any = None, error: Exception = None):
        """Log database query AFTER execution with result or error"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("db.query", query)
            if params:
                span.set_attribute("db.params", str(params))

            if result is not None:
                if hasattr(result, '__len__') and not isinstance(result, (str, bytes)):
                    span.set_attribute("db.rows_affected", len(result))
                else:
                    span.set_attribute("db.result", str(result))

            if error:
                span.set_status(Status(StatusCode.ERROR, str(error)))
                span.record_exception(error)

        # Also log to console
        if error:
            self.error(f"❌ DB Query Error: {query} | Error: {error}")
        else:
            rows = len(result) if result is not None and hasattr(result, '__len__') and not isinstance(result, (str, bytes)) else 'N/A'
            self.info(f"✅ DB Query Success: {query} | Rows/Result: {rows}")

    def log_file_search_operation(self, operation: str, **kwargs):
        """Log FileSearch store operations"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("file_search.operation", operation)
            for key, value in kwargs.items():
                span.set_attribute(f"file_search.{key}", str(value))

        # Also log to console
        details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        details_str = f" | {details}" if details else ""
        self.info(f"📂 FileSearch Operation: {operation}{details_str}")

def get_otel_logger(name: str, service_name: str) -> OpenTelemetryLogger:
    return OpenTelemetryLogger(name, service_name)

def setup_otel_logging(service_name: str):
    """Initialize OpenTelemetry logging for a service"""
    from shared.telemetry import setup_telemetry
    setup_telemetry(service_name)
