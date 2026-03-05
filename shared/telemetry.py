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
    
    # Add a filter to ensure otelTraceID and otelSpanID always exist
    # This MUST be done BEFORE LoggingInstrumentor to catch early logs
    class OTelFieldFilter(logging.Filter):
        def filter(self, record):
            # Ensure these fields always exist, even if LoggingInstrumentor didn't set them
            if not hasattr(record, 'otelTraceID'):
                record.otelTraceID = '0'
            if not hasattr(record, 'otelSpanID'):
                record.otelSpanID = '0'
            return True
    
    # Reset root logger handlers to clean state FIRST
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Add the filter to root logger BEFORE any other setup
    root_logger.addFilter(OTelFieldFilter())
    
    # Create a safe formatter that handles missing OTel fields gracefully
    class SafeOTelFormatter(logging.Formatter):
        """Formatter that safely handles missing otelTraceID and otelSpanID fields"""
        def format(self, record):
            # Ensure OTel fields exist before formatting
            if not hasattr(record, 'otelTraceID'):
                record.otelTraceID = '0'
            if not hasattr(record, 'otelSpanID'):
                record.otelSpanID = '0'
            return super().format(record)
    
    # Format: [Timestamp] [Level] [Service-Name] [TraceID] [SpanID] - Message
    log_format = f"%(asctime)s [%(levelname)s] [{service_name}] [%(otelTraceID)s] [%(otelSpanID)s] - %(message)s"
    formatter = SafeOTelFormatter(log_format)
    
    # Instrument standard logging AFTER filter is in place
    # This ensures otelTraceID and otelSpanID are available in log records
    LoggingInstrumentor().instrument(set_logging_format=False)
    
    # Remove existing handlers to avoid duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    # Add StreamHandler (STDOUT) with immediate flushing for real-time log visibility
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level)
    # Override emit to flush immediately after each log (ensures real-time output during streaming)
    original_emit = stream_handler.emit
    def emit_with_flush(record):
        original_emit(record)
        # Flush immediately so logs appear in real-time during streaming/async operations
        if stream_handler.stream:
            stream_handler.stream.flush()
    stream_handler.emit = emit_with_flush
    root_logger.addHandler(stream_handler)
    
    # Instrument HTTPX Clients (The Glue for Outgoing Requests)
    # This automatically injects the 'traceparent' header into outgoing httpx calls
    HTTPXClientInstrumentor().instrument()
    
    logging.info(f"🔭 OpenTelemetry initialized for {service_name} (span_exporter={'enabled' if enable_span_exporter else 'disabled'})")
    
    return trace.get_tracer(service_name)

def instrument_fastapi(app, service_name):
    """
    Instruments a FastAPI application for context propagation.
    Injects trace_id into headers on requests and extracts on receipt.
    """
    FastAPIInstrumentor.instrument_app(app)
