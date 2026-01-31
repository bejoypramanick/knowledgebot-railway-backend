"""
OpenTelemetry Logging Utilities for Chatbot Orchestration Service
Provides structured logging with OTel span context integration
"""
import logging
from typing import Dict, Any, Optional
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

def get_otel_logger(name: str, service_name: str):
    """Get OpenTelemetry-enhanced logger for chatbot orchestration service"""
    from api_gateway.core.otel_logger import OpenTelemetryLogger
    return OpenTelemetryLogger(name, service_name)
