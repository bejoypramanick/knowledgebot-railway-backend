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

    # Service URLs to Monitor
    api_gateway_url: str = "http://localhost:8000"
    configuration_service_url: str = "http://localhost:8001"
    chatbot_orchestration_url: str = "http://localhost:8003"
    knowledgebase_ingestion_url: str = "http://localhost:8005"
    website_crawling_url: str = "http://localhost:8002"
    docling_service_url: str = "http://localhost:8004"

    # Service Health Check Endpoints
    api_gateway_health_endpoint: str = "/health"
    configuration_health_endpoint: str = "/api/v1/configuration/health"
    chatbot_health_endpoint: str = "/health"
    knowledgebase_health_endpoint: str = "/health"
    website_crawling_health_endpoint: str = "/api/v1/scraping/health"
    docling_health_endpoint: str = "/health"

    # Port Configuration
    health_monitoring_port: int = 8006

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
