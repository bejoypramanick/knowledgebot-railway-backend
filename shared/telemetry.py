import logging
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def setup_telemetry(service_name: str, log_level=logging.INFO):
    """
    Configures OpenTelemetry for the service (Tracing + Logging).
    
    1. Sets up the TracerProvider with a Console Exporter.
    2. Configures standard Python logging to include Trace ID and Span ID.
    3. Uses the format: [Timestamp] [Level] [Service-Name] [TraceID] [SpanID] - Message
    """
    
    # --- 1. IAM: Identity ---
    resource = Resource.create(attributes={
        "service.name": service_name
    })
    
    # --- 2. Tracing: The Glue ---
    provider = TracerProvider(resource=resource)
    
    # "Configure the Console Exporter": Print spans to STDOUT
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    
    # Set the global TracerProvider
    trace.set_tracer_provider(provider)
    
    # --- 3. Logging: The Output ---
    # We want a standardized format.
    # Note: LoggingInstrumentor sets otelTraceID and otelSpanID to "0" if no span is active.
    
    # Format: [Timestamp] [Level] [Service-Name] [TraceID] [SpanID] - Message
    log_format = f"%(asctime)s [%(levelname)s] [{service_name}] [%(otelTraceID)s] [%(otelSpanID)s] - %(message)s"
    formatter = logging.Formatter(log_format)
    
    # Reset root logger handlers to clean state
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    # Add StreamHandler (STDOUT)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)
    
    # Instrument standard logging
    # set_logging_format=False because we manually set the formatter above
    LoggingInstrumentor().instrument(set_logging_format=False)
    
    # Instrument HTTPX Clients (The Glue for Outgoing Requests)
    # This automatically injects the 'traceparent' header into outgoing httpx calls
    HTTPXClientInstrumentor().instrument()
    
    logging.info(f"🔭 OpenTelemetry initialized for {service_name}")
    
    return trace.get_tracer(service_name)

def instrument_fastapi(app, service_name):
    """
    Instruments a FastAPI application for context propagation.
    Injects trace_id into headers on requests and extracts on receipt.
    """
    FastAPIInstrumentor.instrument_app(app)
