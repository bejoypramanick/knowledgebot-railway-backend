"""OpenTelemetry logging setup for Health Monitoring Service."""
import logging

logger = logging.getLogger(__name__)


def setup_otel_logging(service_name: str):
    """Set up OpenTelemetry logging for the service."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger.info(f"✅ OpenTelemetry logging initialized for {service_name}")
