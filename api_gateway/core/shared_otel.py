"""
Shared OpenTelemetry Configuration for All Services
Provides centralized OTel setup that can be imported by any service
"""
import os
from api_gateway.core.otel_config import configure_otel

def setup_opentelemetry_for_service(service_name: str, service_version: str = "1.0.0") -> bool:
    """
    Setup OpenTelemetry for any service in the KnowledgeBot backend
    
    Args:
        service_name: Name of the service (e.g., "chatbot-orchestration", "configuration")
        service_version: Version of the service
        
    Returns:
        bool: True if configuration was successful, False otherwise
    """
    # Set environment variables for service identification
    os.environ["SERVICE_NAME"] = service_name
    os.environ["SERVICE_VERSION"] = service_version
    
    # Configure OpenTelemetry
    success = configure_otel(service_name, service_version)
    
    if success:
        print(f"✅ OpenTelemetry configured for {service_name}")
    else:
        print(f"❌ Failed to configure OpenTelemetry for {service_name}")
    
    return success
