"""
Unified OpenTelemetry Logging Utilities
Provides structured logging with OTel span context integration for all services
"""
import logging
import inspect
from typing import Dict, Any, Optional
from contextvars import ContextVar
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Context variables to store task ID and session ID for logging
task_id_ctx_var: ContextVar[Optional[str]] = ContextVar("task_id", default=None)
session_id_ctx_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)

# Admin context variables for audit trail logging
admin_session_id_ctx_var: ContextVar[Optional[str]] = ContextVar("admin_session_id", default=None)
admin_email_ctx_var: ContextVar[Optional[str]] = ContextVar("admin_email", default=None)
admin_role_ctx_var: ContextVar[Optional[str]] = ContextVar("admin_role", default=None)

def set_task_id(task_id: str) -> None:
    """Set the task ID for the current context (will appear in all logs)"""
    task_id_ctx_var.set(task_id)

def get_task_id() -> Optional[str]:
    """Get current task ID from context"""
    return task_id_ctx_var.get()

def set_session_id(session_id: str) -> None:
    """Set the session ID for the current context (will appear in all logs)

    This is useful for tracking all logs for a specific user/chat session.
    Call this at the start of stream_agent_response() with the session_id.
    """
    session_id_ctx_var.set(session_id)

def get_session_id() -> Optional[str]:
    """Get current session ID from context"""
    return session_id_ctx_var.get()

def set_admin_context(session_id: str, email: str, role: str) -> None:
    """Set admin context for OTEL logging (session_id, email, role)"""
    admin_session_id_ctx_var.set(session_id)
    admin_email_ctx_var.set(email)
    admin_role_ctx_var.set(role)

def get_admin_session_id() -> Optional[str]:
    """Get current admin session ID from context"""
    return admin_session_id_ctx_var.get()

def get_admin_email() -> Optional[str]:
    """Get current admin email from context"""
    return admin_email_ctx_var.get()

def get_admin_role() -> Optional[str]:
    """Get current admin role from context"""
    return admin_role_ctx_var.get()

def clear_admin_context() -> None:
    """Clear admin context at end of request"""
    admin_session_id_ctx_var.set(None)
    admin_email_ctx_var.set(None)
    admin_role_ctx_var.set(None)

def get_calling_file_info() -> Dict[str, str]:
    """Get complete file info of calling code (3 levels up the stack)"""
    try:
        # Go up 3 levels in the stack to get the actual calling code
        # Level 0: this function
        # Level 1: _log_with_context method  
        # Level 2: info/error/warning/etc. method
        # Level 3: actual calling code (where logger.info() is called)
        frame = inspect.stack()[3]
        return {
            'file_path': frame.filename,
            'line_number': str(frame.lineno),
            'method_name': frame.function,
            'full_info': f"{frame.filename}:{frame.lineno} in {frame.function}()"
        }
    except (IndexError, AttributeError):
        return {
            'file_path': 'unknown_file',
            'line_number': 'unknown',
            'method_name': 'unknown',
            'full_info': 'unknown_file:unknown in unknown()'
        }

class OpenTelemetryLogger:
    """Enhanced logger with OpenTelemetry integration for Railway"""
    
    def __init__(self, name: str, service_name: str):
        self.logger = logging.getLogger(name)
        self.service_name = service_name
        self.tracer = trace.get_tracer(f"{service_name}.{name}")
        
    def _format_message(self, message: str) -> str:
        """Add admin/task/session context prefix to message if available"""
        admin_session_id = get_admin_session_id()
        admin_email = get_admin_email()
        admin_role = get_admin_role()
        task_id = get_task_id()
        session_id = get_session_id()

        # Build context prefix: admin context (highest priority), then chat session, then task
        context_parts = []

        # Admin context - highest priority when present
        if admin_email:
            admin_str = f"admin:{admin_email}"
            if admin_role:
                admin_str += f" role:{admin_role}"
            if admin_session_id:
                admin_str += f" admin_session:{admin_session_id[:8]}"
            context_parts.append(admin_str)

        # Chat session context
        if session_id:
            # Show more of the session ID for visibility (not just first 8 chars)
            context_parts.append(f"session:{session_id[:16]}")

        # Task context
        if task_id:
            # Show more of the task ID for visibility (not just first 8 chars)
            context_parts.append(f"task:{task_id[:16]}")

        if context_parts:
            context_str = " ".join(context_parts)
            return f"[{context_str}] {message}"
        return message
        
    def _log_with_context(self, level: int, message: str, extra: Dict[str, Any] = None, **kwargs):
        """Log message with OpenTelemetry context using standard logging"""
        # Get calling file info automatically
        file_info = get_calling_file_info()

        # Add task ID and session ID to message
        formatted_message = self._format_message(message)

        # Add file info to message for debugging
        file_prefix = f"[{file_info['full_info']}]"
        full_message = f"{file_prefix} {formatted_message}"

        # Add admin, task, and session context to extra fields
        extra = extra or {}
        admin_session_id = get_admin_session_id()
        admin_email = get_admin_email()
        admin_role = get_admin_role()
        task_id = get_task_id()
        session_id = get_session_id()

        # Add admin context
        if admin_session_id:
            extra['admin_session_id'] = admin_session_id
        if admin_email:
            extra['admin_email'] = admin_email
        if admin_role:
            extra['admin_role'] = admin_role

        # Add other context
        if task_id:
            extra['task_id'] = task_id
        if session_id:
            extra['session_id'] = session_id

        extra.update({
            'file_path': file_info['file_path'],
            'line_number': file_info['line_number'],
            'method_name': file_info['method_name']
        })

        # Extract reserved LogRecord attributes from kwargs (these can't go in extra dict)
        exc_info = kwargs.pop('exc_info', None)
        exc_text = kwargs.pop('exc_text', None)
        stack_info = kwargs.pop('stack_info', None)

        # Prepare logger.log kwargs
        log_kwargs = {'extra': extra}
        if exc_info is not None:
            log_kwargs['exc_info'] = exc_info
        if exc_text is not None:
            log_kwargs['exc_text'] = exc_text
        if stack_info is not None:
            log_kwargs['stack_info'] = stack_info

        # Standard logger automatically includes otelTraceID and otelSpanID
        # from shared/telemetry.py LoggingInstrumentor
        self.logger.log(level, full_message, **log_kwargs)

        # Add span attributes if span exists
        span = trace.get_current_span()
        if span and span.is_recording():
            span_attributes = {
                "log.level": logging.getLevelName(level),
                "log.message": message,
                "log.logger": self.logger.name,
                "service.name": self.service_name,
                "file.path": file_info['file_path'],
                "file.line": file_info['line_number'],
                "file.method": file_info['method_name'],
            }

            # Add optional admin context (highest priority)
            if admin_email:
                span_attributes["admin_email"] = admin_email
            if admin_role:
                span_attributes["admin_role"] = admin_role
            if admin_session_id:
                span_attributes["admin_session_id"] = admin_session_id

            # Add other context
            if task_id:
                span_attributes["task_id"] = task_id
            if session_id:
                span_attributes["session_id"] = session_id

            span.add_event(
                name="log",
                attributes=span_attributes
            )
    
    def info(self, message: str, **kwargs):
        self._log_with_context(logging.INFO, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log_with_context(logging.ERROR, message, **kwargs)
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_status(Status(StatusCode.ERROR, message))

    def warning(self, message: str, **kwargs):
        self._log_with_context(logging.WARNING, message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._log_with_context(logging.DEBUG, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log_with_context(logging.CRITICAL, message, **kwargs)
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
            # Safely convert error to string, handling generator and other async exceptions
            try:
                error_msg = str(error) if str(error) else type(error).__name__
            except Exception:
                error_msg = type(error).__name__
            self.error(f"❌ DB Query Error: {query} | Error: {error_msg}")
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
