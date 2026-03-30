"""Configuration settings for Celery Web Worker service."""
from typing import Optional

from pydantic import Field
from shared.base_settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    """Celery Web Worker specific settings (extends common BaseServiceSettings)."""

    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_crawling_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"
    kreuzberg_service_url: str = "http://localhost:8000"

    # Kreuzberg Service Configuration
    kreuzberg_enabled: bool = Field(default=True, env="KREUZBERG_ENABLED")  # Set to False to disable kreuzberg and use raw uploads
    kreuzberg_api_url: str = Field(default="http://localhost:8000", env="KREUZBERG_API_URL")


settings = Settings()
