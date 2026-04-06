"""Configuration settings for Celery File Worker service."""
from typing import Optional

from pydantic import Field
from shared.base_settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    """Celery File Worker specific settings (extends common BaseServiceSettings)."""

    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_crawling_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"

    # Redis Configuration
    redis_url: Optional[str] = None
    file_task_queue_redis_db: int = 0

    # Kreuzberg Configuration
    kreuzberg_enabled: bool = Field(default=True, env="KREUZBERG_ENABLED")
    kreuzberg_api_url: str = Field(default="http://localhost:8000", env="KREUZBERG_API_URL")


settings = Settings()
