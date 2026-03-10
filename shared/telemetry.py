import logging
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def setup_telemetry(service_name: str, log_level=logging.INFO, enable_span_exporter=None):
    """
    Configures OpenTelemetry for the service (Tracing + Logging).
    
    1. Sets up the TracerProvider with optional Console Exporter.
    2. Configures standard Python logging to include Trace ID and Span ID.
    3. Uses the format: [Timestamp] [Level] [Service-Name] [TraceID] [SpanID] - Message
    
    Args:
        service_name: Name of the service
        log_level: Logging level
        enable_span_exporter: Whether to enable the ConsoleSpanExporter (detailed span output).
                          If None, defaults to OTEL_SPAN_EXPORTER_ENABLED env var or False.
    """
    
    # Determine if span exporter should be enabled
    if enable_span_exporter is None:
        enable_span_exporter = os.getenv("OTEL_SPAN_EXPORTER_ENABLED", "false").lower() == "true"
    
    # --- 1. IAM: Identity ---
    resource = Resource.create(attributes={
        "service.name": service_name
    })
    
    # --- 2. Tracing: The Glue ---
    provider = TracerProvider(resource=resource)
    
    # "Configure the Console Exporter": Print spans to STDOUT (optional)
    if enable_span_exporter:
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
    
    # Set the global TracerProvider
    trace.set_tracer_provider(provider)
    
    # --- 3. Logging: The Output ---
    # We want a standardized format.
    # Note: LoggingInstrumentor sets otelTraceID and otelSpanID to "0" if no span is active.
    
    # Create a safe formatter that handles missing OTel fields gracefully
    # This MUST be defined before any logging setup
    class SafeOTelFormatter(logging.Formatter):
        """Formatter that safely handles missing otelTraceID and otelSpanID fields"""
        def format(self, record):
            # Ensure OTel fields exist before formatting - this is the critical fix
            if not hasattr(record, 'otelTraceID'):
                record.otelTraceID = '0'
            if not hasattr(record, 'otelSpanID'):
                record.otelSpanID = '0'
            return super().format(record)
    
    # Add a global filter to ensure otelTraceID and otelSpanID always exist
    # This catches ALL log records across ALL loggers
    class OTelFieldFilter(logging.Filter):
        def filter(self, record):
            # Ensure these fields always exist, even if LoggingInstrumentor didn't set them
            if not hasattr(record, 'otelTraceID'):
                record.otelTraceID = '0'
            if not hasattr(record, 'otelSpanID'):
                record.otelSpanID = '0'
            return True
    
    # Create the global filter instance
    global_filter = OTelFieldFilter()
    
    # Reset root logger handlers to clean state FIRST
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Add the filter to root logger BEFORE any other setup
    root_logger.addFilter(global_filter)
    
    # Format: [Timestamp] [Level] [Service-Name] [TraceID] [SpanID] - Message
    log_format = f"%(asctime)s [%(levelname)s] [{service_name}] [%(otelTraceID)s] [%(otelSpanID)s] - %(message)s"
    formatter = SafeOTelFormatter(log_format)
    
    # Remove existing handlers to avoid duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    # Add StreamHandler (STDOUT) with immediate flushing for real-time log visibility
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level)
    # Add the filter to the handler as well for double protection
    stream_handler.addFilter(global_filter)
    
    # Override emit to flush immediately after each log (ensures real-time output during streaming)
    original_emit = stream_handler.emit
    def emit_with_flush(record):
        # Ensure fields exist right before emit as final safety check
        if not hasattr(record, 'otelTraceID'):
            record.otelTraceID = '0'
        if not hasattr(record, 'otelSpanID'):
            record.otelSpanID = '0'
        original_emit(record)
        # Flush immediately so logs appear in real-time during streaming/async operations
        if stream_handler.stream:
            stream_handler.stream.flush()
    stream_handler.emit = emit_with_flush
    root_logger.addHandler(stream_handler)
    
    # Instrument standard logging AFTER all filters and handlers are in place
    # This ensures otelTraceID and otelSpanID are available in log records
    LoggingInstrumentor().instrument(set_logging_format=False)
    
    # Instrument HTTPX Clients (The Glue for Outgoing Requests)
    # This automatically injects the 'traceparent' header into outgoing httpx calls
    HTTPXClientInstrumentor().instrument()
    
    logging.info(f"🔭 OpenTelemetry initialized for {service_name} (span_exporter={'enabled' if enable_span_exporter else 'disabled'})")
    
    return trace.get_tracer(service_name)

def instrument_fastapi(app, service_name):
    """
    Instruments a FastAPI application for context propagation.
    Injects trace_id into headers on requests and extracts on receipt.
    Also adds route path to spans for easier tracing.
    """
    from fastapi import Request
    from opentelemetry import trace
    
    # Instrument FastAPI with OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)
    
    # Add middleware to enrich spans with route information
    @app.middleware("http")
    async def add_route_to_span(request: Request, call_next):
        """Add route path to current span and log it"""
        # Get current span
        span = trace.get_current_span()
        
        if span and span.is_recording():
            # Get route path (e.g., /api/v1/gateway/auth/session)
            route_path = request.url.path
            
            # Try to get the matched route pattern (e.g., /api/v1/gateway/auth/{action})
            if hasattr(request, "scope") and "route" in request.scope:
                route = request.scope.get("route")
                if route and hasattr(route, "path"):
                    route_path = route.path
            
            # Add route as span attribute
            span.set_attribute("http.route", route_path)
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.target", request.url.path)
            
            # Update span name to include route
            span.update_name(f"{request.method} {route_path}")
            
            # Get trace context for logging
            span_context = span.get_span_context()
            trace_id = format(span_context.trace_id, '032x') if span_context.trace_id else '0'
            span_id = format(span_context.span_id, '016x') if span_context.span_id else '0'
            
            # Log the route with trace context
            logger = logging.getLogger(service_name)
            logger.info(
                f"🔀 ROUTE: {request.method} {route_path} | "
                f"Path: {request.url.path} | "
                f"TraceID: {trace_id} | "
                f"SpanID: {span_id}"
            )
        
        response = await call_next(request)
        return response
    
    logging.info(f"✅ FastAPI instrumented with route path logging for {service_name}")

