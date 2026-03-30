"""Configuration settings for Knowledgebase Ingestion service."""
from typing import Optional

from shared.base_settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    """Knowledgebase Ingestion specific settings (extends common BaseServiceSettings)."""

    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_crawling_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"

    # Railway Storage Configuration (S3-compatible)
    railway_bucket_name: Optional[str] = None  # RAILWAY_BUCKET_NAME (shared bucket for uploads)
    railway_region: Optional[str] = "us-east-1"
    railway_storage_url: Optional[str] = None
    railway_storage_access_key: Optional[str] = None
    railway_storage_secret_key: Optional[str] = None


settings = Settings()
