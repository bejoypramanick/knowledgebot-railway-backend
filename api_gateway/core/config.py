"""Shared configuration settings for all services."""
from typing import Optional
import os
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
    # Railway internal services all run on port 8080
    configuration_service_url: str = os.getenv("CONFIGURATION_SERVICE_URL", "http://configuration.railway.internal:8080")
    chatbot_orchestration_url: str = os.getenv("CHATBOT_ORCHESTRATION_URL", "http://chatbot-orchestration.railway.internal:8080")
    knowledgebase_ingestion_url: str = os.getenv("KNOWLEDGEBASE_INGESTION_URL", "http://knowledge-base.railway.internal:8080")
    admin_service_url: str = os.getenv("ADMIN_SERVICE_URL", "http://localhost:8000")
    
    # Firebase Configuration
    firebase_project_id: Optional[str] = None
    firebase_credentials_path: Optional[str] = None
    
    # Redis Configuration
    redis_url: Optional[str] = None
    
    # Logging Configuration
    log_level: str = "INFO"
    
    # Session Configuration
    session_cookie_name: str = "session"
    session_max_age: int = 60 * 60 * 24 * 7  # 7 days
    session_domain: str = ".globistaan.com"
    strict_session_check: bool = True  # Enforce IP/User-Agent validation
    
    # CSRF Protection - Allowed Origins
    allowed_origins: list = [
        "https://digibot-dev.globistaan.com",
        "https://digibot.globistaan.com",
        "https://dailogue.globistaan.com",
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
