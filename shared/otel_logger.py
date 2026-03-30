"""
Unified OpenTelemetry Logging Utilities with Structlog Backend

Provides structured logging with OTel span context integration using structlog as the underlying engine.
All context variables and public APIs are preserved from the original implementation.
"""

import logging
import sys
from typing import Dict, Any, Optional
from contextvars import ContextVar
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import structlog
from shared.log_sanitizer import hash_pii

# Context variables to store task ID and session ID for logging
task_id_ctx_var: ContextVar[Optional[str]] = ContextVar("task_id", default=None)
session_id_ctx_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

# Admin context variables for audit trail logging
admin_session_id_ctx_var: ContextVar[Optional[str]] = ContextVar(
    "admin_session_id", default=None
)
admin_email_ctx_var: ContextVar[Optional[str]] = ContextVar("admin_email", default=None)
admin_role_ctx_var: ContextVar[Optional[str]] = ContextVar("admin_role", default=None)

# Workflow context variable for tracing feature workflows
workflow_ctx_var: ContextVar[Optional[str]] = ContextVar("workflow", default=None)


# Configure structlog once at module level
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)


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


def set_request_id(request_id: str) -> None:
    """Set request correlation id for the current context."""
    request_id_ctx_var.set(request_id)


def get_request_id() -> Optional[str]:
    """Get request correlation id from context."""
    return request_id_ctx_var.get()


def set_admin_context(session_id: str, email: str, role: str) -> None:
    """Set admin context for OTEL logging (session_id, email, role)"""
    admin_session_id_ctx_var.set(session_id)
    # Never store raw email in logging context.
    admin_email_ctx_var.set(hash_pii(email))
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


def set_workflow(workflow: str) -> None:
    """Set the current workflow being executed for tracing (e.g., 'human-agent-workflow')

    This allows you to trace complete workflows across multiple function calls and requests.
    Example: set_workflow("human-agent-workflow") will add [human-agent-workflow] to all logs
    """
    workflow_ctx_var.set(workflow)


def get_workflow() -> Optional[str]:
    """Get current workflow from context"""
    return workflow_ctx_var.get()


def clear_workflow() -> None:
    """Clear workflow context at end of operation"""
    workflow_ctx_var.set(None)


def get_calling_file_info() -> Dict[str, str]:
    """Get file info of calling code using sys._getframe (fast, no stack walk).

    sys._getframe(N) returns a single frame object directly — O(1).
    inspect.stack() builds FrameInfo for the ENTIRE stack — O(N) and very slow.
    """
    try:
        # Go up 3 levels: this function → _log_with_context → info/error/etc → caller
        frame = sys._getframe(3)
        filename = frame.f_code.co_filename
        lineno = frame.f_lineno
        funcname = frame.f_code.co_name
        return {
            "file_path": filename,
            "line_number": str(lineno),
            "method_name": funcname,
            "full_info": f"{filename}:{lineno}",
        }
    except (ValueError, AttributeError):
        return {
            "file_path": "unknown_file",
            "line_number": "unknown",
            "method_name": "unknown",
            "full_info": "unknown_file:unknown",
        }


class OpenTelemetryLogger:
    """Enhanced logger with OpenTelemetry and Structlog integration for Railway"""

    def __init__(self, name: str, service_name: str):
        self.logger = structlog.get_logger(name)
        self.service_name = service_name
        self.tracer = trace.get_tracer(f"{service_name}.{name}")
        self.stdlib_logger = logging.getLogger(name)

    def _format_message(self, message: str) -> str:
        """Add admin/task/session/workflow context prefix to message if available"""
        admin_session_id = get_admin_session_id()
        admin_email = get_admin_email()
        admin_role = get_admin_role()
        task_id = get_task_id()
        session_id = get_session_id()
        request_id = get_request_id()
        workflow = get_workflow()

        # Build context prefix
        context_parts = []

        # Workflow context - highest priority when present
        if workflow:
            context_parts.append(f"workflow:{workflow}")

        # Admin context - high priority when present
        if admin_email:
            admin_str = f"admin_hash:{admin_email}"
            if admin_role:
                admin_str += f" role:{admin_role}"
            if admin_session_id:
                admin_str += f" admin_session:{admin_session_id[:8]}"
            context_parts.append(admin_str)

        if request_id:
            context_parts.append(f"req:{request_id}")

        # Chat session context
        if session_id:
            context_parts.append(f"session:{session_id[:16]}")

        # Task context
        if task_id:
            context_parts.append(f"task:{task_id[:16]}")

        if context_parts:
            context_str = " ".join(context_parts)
            return f"[{context_str}] {message}"
        return message

    def _log_with_context(
        self, level: int, message: str, extra: Dict[str, Any] = None, **kwargs
    ):
        """Log message with OpenTelemetry context"""
        # Get calling file info automatically
        file_info = get_calling_file_info()

        # Add task ID and session ID to message
        formatted_message = self._format_message(message)

        # Prepare context/extra fields
        extra = extra or {}
        admin_session_id = get_admin_session_id()
        admin_email = get_admin_email()
        admin_role = get_admin_role()
        task_id = get_task_id()
        session_id = get_session_id()
        request_id = get_request_id()
        workflow = get_workflow()

        # Add workflow context (highest priority)
        if workflow:
            extra["workflow"] = workflow

        # Add admin context
        if admin_session_id:
            extra["admin_session_id"] = admin_session_id
        if admin_email:
            extra["admin_email"] = admin_email
        if admin_role:
            extra["admin_role"] = admin_role

        # Add other context
        if task_id:
            extra["task_id"] = task_id
        if session_id:
            extra["session_id"] = session_id
        if request_id:
            extra["request_id"] = request_id

        # Add file info
        extra.update(
            {
                "file_path": file_info["file_path"],
                "line_number": file_info["line_number"],
                "func_name": file_info["method_name"],
            }
        )

        # Log via structlog
        level_name = logging.getLevelName(level).lower()
        getattr(self.logger, level_name)(formatted_message, **extra)

        # Also log via stdlib for compatibility with handlers (e.g., file rotation)
        self.stdlib_logger.log(level, formatted_message, extra=extra)

        # Get current span and extract trace/span IDs
        span = trace.get_current_span()
        trace_id = None
        span_id = None
        if span and span.is_recording():
            span_context = span.get_span_context()
            trace_id = (
                format(span_context.trace_id, "032x") if span_context.trace_id else "0"
            )
            span_id = (
                format(span_context.span_id, "016x") if span_context.span_id else "0"
            )

        # Add span attributes if span exists
        if span and span.is_recording():
            span_attributes = {
                "log.level": logging.getLevelName(level),
                "log.message": message,
                "service.name": self.service_name,
                "file.path": file_info["file_path"],
                "file.line": file_info["line_number"],
                "file.func": file_info["method_name"],
            }

            # Add trace/span IDs to span attributes
            if trace_id:
                span_attributes["otelTraceID"] = trace_id
            if span_id:
                span_attributes["otelSpanID"] = span_id

            # Add workflow context
            if workflow:
                span_attributes["workflow"] = workflow

            # Add optional admin context
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

            span.add_event(name="log", attributes=span_attributes)

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

        # Log to console at DEBUG level
        param_str = f" | Params: {params}" if params else ""
        self.debug(f"🔍 DB Executing: {query}{param_str}")

    def log_db_query(
        self,
        query: str,
        params: Any = None,
        result: Any = None,
        error: Exception = None,
    ):
        """Log database query AFTER execution with result or error"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("db.query", query)
            if params:
                span.set_attribute("db.params", str(params))

            if result is not None:
                if hasattr(result, "__len__") and not isinstance(result, (str, bytes)):
                    span.set_attribute("db.rows_affected", len(result))
                else:
                    span.set_attribute("db.result", str(result))

            if error:
                span.set_status(Status(StatusCode.ERROR, str(error)))
                span.record_exception(error)

        # Log to console at DEBUG level (errors still at ERROR level)
        if error:
            try:
                error_msg = str(error) if str(error) else type(error).__name__
            except Exception:
                error_msg = type(error).__name__
            self.error(f"❌ DB Query Error: {query} | Error: {error_msg}")
        else:
            rows = (
                len(result)
                if result is not None
                and hasattr(result, "__len__")
                and not isinstance(result, (str, bytes))
                else "N/A"
            )
            self.debug(f"✅ DB Query Success: {query} | Rows/Result: {rows}")

    def log_storage_operation(self, operation: str, **kwargs):
        """Log storage backend operations"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("storage.operation", operation)
            for key, value in kwargs.items():
                span.set_attribute(f"storage.{key}", str(value))

        # Also log to console
        details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        details_str = f" | {details}" if details else ""
        self.info(f"📂 Storage Operation: {operation}{details_str}")


def get_otel_logger(name: str, service_name: str) -> OpenTelemetryLogger:
    return OpenTelemetryLogger(name, service_name)


def setup_otel_logging(service_name: str):
    """Initialize OpenTelemetry logging for a service"""
    from shared.telemetry import setup_telemetry

    setup_telemetry(service_name)
