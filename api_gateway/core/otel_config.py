"""
OpenTelemetry Configuration for KnowledgeBot Backend
Provides centralized OTel setup for all microservices with Railway console integration
"""
import os
import logging
from typing import Optional
from opentelemetry import trace, metrics, baggage
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.semconv.trace import SpanKind
from opentelemetry import context as context_api

# Get Railway OTel endpoint from environment
RAILWAY_OTEL_ENDPOINT = os.getenv("RAILWAY_OTEL_ENDPOINT", "https://otel.railway.app")
SERVICE_NAME = os.getenv("SERVICE_NAME", "knowledgebot-service")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")

logger = logging.getLogger(__name__)

class OpenTelemetryConfig:
    """Centralized OpenTelemetry configuration for Railway"""
    
    def __init__(self, service_name: str, service_version: str = "1.0.0"):
        self.service_name = service_name
        self.service_version = service_version
        self._configured = False
        
    def configure(self) -> bool:
        """Configure OpenTelemetry for Railway console"""
        if self._configured:
            logger.info("🔍 OpenTelemetry already configured")
            return True
            
        try:
            # Configure resource with service metadata
            resource = Resource.create({
                "service.name": self.service_name,
                "service.version": self.service_version,
                "service.instance.id": os.getenv("RAILWAY_SERVICE_ID", "unknown"),
                "deployment.environment": os.getenv("RAILWAY_ENVIRONMENT", "development"),
                "provider": "railway"
            })
            
            # Configure tracing
            self._configure_tracing(resource)
            
            # Configure metrics
            self._configure_metrics(resource)
            
            # Configure auto-instrumentation
            self._configure_auto_instrumentation()
            
            # Configure propagation
            set_global_textmap()
            
            self._configured = True
            logger.info(f"✅ OpenTelemetry configured for {self.service_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to configure OpenTelemetry: {e}")
            return False
    
    def _configure_tracing(self, resource: Resource):
        """Configure OpenTelemetry tracing"""
        # Configure OTLP exporter for Railway
        otlp_exporter = OTLPSpanExporter(
            endpoint=f"{RAILWAY_OTEL_ENDPOINT}/v1/traces",
            headers={
                "Authorization": f"Bearer {os.getenv('RAILWAY_OTEL_TOKEN', '')}"
            } if os.getenv("RAILWAY_OTEL_TOKEN") else None
        )
        
        # Configure tracer provider
        tracer_provider = TracerProvider(resource=resource)
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)
        
        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)
        logger.info("🔍 OpenTelemetry tracing configured")
    
    def _configure_metrics(self, resource: Resource):
        """Configure OpenTelemetry metrics"""
        # Configure OTLP exporter for metrics
        otlp_exporter = OTLPMetricExporter(
            endpoint=f"{RAILWAY_OTEL_ENDPOINT}/v1/metrics",
            headers={
                "Authorization": f"Bearer {os.getenv('RAILWAY_OTEL_TOKEN', '')}"
            } if os.getenv("RAILWAY_OTEL_TOKEN") else None
        )
        
        # Configure metric reader
        metric_reader = PeriodicExportingMetricReader(
            exporter=otlp_exporter,
            export_interval_millis=30000  # Export every 30 seconds
        )
        
        # Configure meter provider
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        logger.info("🔍 OpenTelemetry metrics configured")
    
    def _configure_auto_instrumentation(self):
        """Configure auto-instrumentation for common libraries"""
        try:
            # FastAPI instrumentation
            FastAPIInstrumentor.instrument()
            logger.info("🔍 FastAPI instrumentation enabled")
        except Exception as e:
            logger.warning(f"⚠️ FastAPI instrumentation failed: {e}")
        
        try:
            # HTTPX instrumentation
            HTTPXClientInstrumentor.instrument()
            logger.info("🔍 HTTPX instrumentation enabled")
        except Exception as e:
            logger.warning(f"⚠️ HTTPX instrumentation failed: {e}")
        
        try:
            # AsyncPG instrumentation
            AsyncPGInstrumentor.instrument()
            logger.info("🔍 AsyncPG instrumentation enabled")
        except Exception as e:
            logger.warning(f"⚠️ AsyncPG instrumentation failed: {e}")
    
    def get_tracer(self, name: str = None):
        """Get a tracer instance"""
        if not self._configured:
            self.configure()
        
        tracer_name = f"{self.service_name}.{name}" if name else self.service_name
        return trace.get_tracer(tracer_name)
    
    def get_meter(self, name: str = None):
        """Get a meter instance"""
        if not self._configured:
            self.configure()
        
        meter_name = f"{self.service_name}.{name}" if name else self.service_name
        return metrics.get_meter(meter_name)

# Global OTel configuration instance
otel_config = OpenTelemetryConfig(SERVICE_NAME, SERVICE_VERSION)

# Convenience functions
def get_tracer(name: str = None):
    """Get tracer for current service"""
    return otel_config.get_tracer(name)

def get_meter(name: str = None):
    """Get meter for current service"""
    return otel_config.get_meter(name)

def configure_otel(service_name: str, service_version: str = "1.0.0") -> bool:
    """Configure OpenTelemetry for a specific service"""
    global otel_config
    otel_config = OpenTelemetryConfig(service_name, service_version)
    return otel_config.configure()

# Span context helpers
def add_span_attributes(attributes: dict):
    """Add attributes to current span"""
    span = trace.get_current_span()
    if span:
        for key, value in attributes.items():
            span.set_attribute(key, value)

def set_span_status(status_code: int, message: str = ""):
    """Set status for current span"""
    span = trace.get_current_span()
    if span:
        span.set_status(trace.Status(trace.StatusCode.OK if status_code < 400 else trace.StatusCode.ERROR, message))

def create_span(name: str, kind: SpanKind = SpanKind.INTERNAL):
    """Create a new span"""
    tracer = get_tracer()
    return tracer.start_span(name, kind=kind)
