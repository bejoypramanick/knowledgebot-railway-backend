"""Shared configuration settings for celery-file-worker."""
from typing import Optional

from pydantic import Field
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

    # Redis Configuration (used by celery_app.py to connect to Celery broker)
    file_redis_url: Optional[str] = None  # FILE_REDIS_URL from Railway (required)

    # Kreuzberg Configuration
    kreuzberg_enabled: bool = Field(default=True, env="KREUZBERG_ENABLED")
    kreuzberg_api_url: str = Field(default="http://localhost:8000", env="KREUZBERG_API_URL")

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
