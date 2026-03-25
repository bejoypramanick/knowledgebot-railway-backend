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
    chatbot_model: str = "gemini-2.5-flash-lite"

    # Railway Storage Configuration (S3-compatible)
    railway_bucket_name: Optional[str] = None  # RAILWAY_BUCKET_NAME (shared bucket for uploads)
    railway_region: Optional[str] = "us-east-1"
    railway_storage_url: Optional[str] = None
    railway_storage_access_key: Optional[str] = None
    railway_storage_secret_key: Optional[str] = None

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
