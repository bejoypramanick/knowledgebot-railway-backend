"""
OpenTelemetry Logging Utilities for Railway Console
Provides structured logging with OTel span context integration
"""
import logging
import time
from typing import Dict, Any, Optional
from opentelemetry import trace, context
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
        """Log message with OpenTelemetry context"""
        span_context = self._get_span_context()
        
        # Create log prefix with trace context
        prefix = f"[{self.service_name}]"
        if span_context:
            prefix += f"[trace:{span_context['trace_id'][:8]}]"
        
        # Format message with context
        formatted_message = f"{prefix} {message}"
        
        # Add span attributes if span exists
        if span_context:
            span = trace.get_current_span()
            if span:
                # Add log entry as span event
                span.add_event(
                    name="log",
                    attributes={
                        "log.level": logging.getLevelName(level),
                        "log.message": message,
                        "log.logger": self.logger.name
                    }
                )
        
        # Log with formatted message
        self.logger.log(level, formatted_message)
    
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
            span.set_attribute("db.type", "postgresql")
            
            if params:
                span.set_attribute("db.parameters", str(params))
            
            if error:
                span.set_status(Status(StatusCode.ERROR, str(error)))
                self.error(f"DB Query Failed: {query.strip()}", params=params, error=str(error))
            else:
                if result is not None:
                    if isinstance(result, list):
                        span.set_attribute("db.rows_affected", len(result))
                    elif hasattr(result, '__len__'):
                        span.set_attribute("db.rows_affected", len(result))
                
                self.info(f"DB Query Success: {query.strip()}", params=params, result_type=type(result).__name__)
    
    def log_http_request(self, method: str, url: str, status_code: int = None, error: Exception = None):
        """Log HTTP request with OTel context"""
        span = trace.get_current_span()
        if span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.url", url)
            
            if status_code:
                span.set_attribute("http.status_code", status_code)
                span.set_status(Status(StatusCode.OK if status_code < 400 else StatusCode.ERROR))
            
            if error:
                span.set_status(Status(StatusCode.ERROR, str(error)))
                self.error(f"HTTP Request Failed: {method} {url}", status_code=status_code, error=str(error))
            else:
                self.info(f"HTTP Request: {method} {url}", status_code=status_code)
    
    def create_span(self, name: str, kind: SpanKind = SpanKind.INTERNAL, attributes: Dict[str, Any] = None):
        """Create a new span with logging"""
        span = self.tracer.start_span(name, kind=kind)
        
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        
        return span

def get_otel_logger(name: str, service_name: str) -> OpenTelemetryLogger:
    """Get OpenTelemetry-enhanced logger"""
    return OpenTelemetryLogger(name, service_name)
