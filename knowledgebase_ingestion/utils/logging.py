"""
Logging utilities for knowledgebase ingestion
"""
from shared.otel_logger import get_otel_logger

# Re-export the shared logger for backward compatibility
def get_otel_logger(name: str, service_name: str = None):
    """
    Get OpenTelemetry logger instance.
    
    Args:
        name: Logger name
        service_name: Service name for OpenTelemetry
        
    Returns:
        Configured logger instance
    """
    return get_otel_logger(name, service_name)
