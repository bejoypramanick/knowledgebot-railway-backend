"""Configuration settings for Health Monitoring Service."""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    railway_postgres_url: Optional[str] = None
    database_url: Optional[str] = None

    # Health Check Configuration
    health_check_interval_seconds: int = 300  # 5 minutes
    health_check_timeout_seconds: int = 10

    # Service URLs to Monitor (read from environment variables)
    api_gateway_url: str = "http://api-gateway.railway.internal:8080"
    chatbot_orchestration_url: str = "http://chatbot-orchestration.railway.internal:8080"
    configuration_service_url: str = "http://configuration.railway.internal:8080"
    knowledgebase_ingestion_url: str = "http://knowledge-base.railway.internal:8080"
    website_crawling_url: str = "http://web-crawling.railway.internal:8080"
    docling_service_url: str = "http://docling.railway.internal:8080"

    # Service Health Check Endpoints
    api_gateway_health_endpoint: str = "/health"
    configuration_health_endpoint: str = "/api/v1/configuration/health"
    chatbot_health_endpoint: str = "/health"
    knowledgebase_health_endpoint: str = "/health"
    website_crawling_health_endpoint: str = "/health"
    docling_health_endpoint: str = "/health"

    # Port Configuration
    health_monitoring_port: int = 8006

    # Validate service URLs
    def __init__(self, **data):
        super().__init__(**data)
        # Log service URLs on startup
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"📡 Service URLs configured: api_gateway={self.api_gateway_url}, chatbot={self.chatbot_orchestration_url}")

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
