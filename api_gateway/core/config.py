"""Shared configuration settings for all services."""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys (optional - services only require what they need)
    gemini_api_key: Optional[str] = None
    
    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_crawling_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"
    
    # API Gateway
    api_gateway_port: int = 8000
    api_gateway_host: str = "0.0.0.0"
    
    # Chatbot Configuration
    chatbot_model: str = "gemini-2.0-flash-exp"
    
    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None
    
    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None
    
    # Service Identity
    service_identity: str = "api-gateway"
    
    # Service URLs for routing - Railway provides these as environment variables
    configuration_service_url: str = "http://configuration-service.railway.internal:8004"
    chatbot_orchestration_url: str = "http://chatbot-orchestration.railway.internal:8003"
    knowledgebase_ingestion_url: str = "http://knowledgebase-ingestion.railway.internal:8001"
    website_crawling_url: str = "http://website-crawling.railway.internal:8002"
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()

# Service Identity for logging and identification
SERVICE_IDENTITY = settings.service_identity

# Service URLs
CONFIGURATION_SERVICE_URL = settings.configuration_service_url
CHATBOT_ORCHESTRATION_URL = settings.chatbot_orchestration_url
KNOWLEDGEBASE_INGESTION_URL = settings.knowledgebase_ingestion_url
WEBSITE_CRAWLING_URL = settings.website_crawling_url
