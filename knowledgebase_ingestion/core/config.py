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
    docling_service_url: str = "http://localhost:8004"
    
    # API Gateway
    api_gateway_port: int = 8000
    api_gateway_host: str = "0.0.0.0"
    
    # Chatbot Configuration
    chatbot_model: str = "gemini-2.0-flash-exp"

    # Docling Service Configuration (plug-and-play)
    docling_enabled: bool = True  # Set to False to disable docling and use raw uploads
    docling_timeout_seconds: int = 300  # Processing timeout (5 minutes)
    docling_fallback_to_raw: bool = True  # Fallback to raw upload if docling fails/times out

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
