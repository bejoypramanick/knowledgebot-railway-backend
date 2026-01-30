"""Shared configuration settings for all services."""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys (optional - services only require what they need)
    gemini_api_key: Optional[str] = None
    
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
    
    # Service URLs for routing - read from Railway environment variables
    configuration_service_url: str = ""
    chatbot_orchestration_url: str = ""
    knowledgebase_ingestion_url: str = ""
    website_crawling_url: str = ""
    
    # Firebase Configuration
    firebase_project_id: Optional[str] = None
    firebase_credentials_path: Optional[str] = None
    
    # Redis Configuration
    redis_url: Optional[str] = None
    
    # Logging Configuration
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
