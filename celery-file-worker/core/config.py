"""Shared configuration settings for celery-file-worker."""
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

    # Gemini FileSearch Store Configuration (required from Railway env)
    gemini_file_search_store_name: Optional[str] = None  # FileSearch store display name - MUST be set in Railway env

    # Redis Configuration
    redis_url: str = "redis://localhost:6379/0"  # DB 0: Celery file queue

    # Docling RQ Configuration (separate Redis DB to avoid collisions)
    docling_redis_url: Optional[str] = None  # DB 2: Docling queue (auto-constructs from redis_url if not set)
    docling_enabled: bool = True  # Set to False to disable docling and use raw uploads
    docling_timeout_seconds: int = 1800  # Processing timeout (30 minutes - handles queue wait time)
    docling_rq_queue_name: str = "docling"  # Redis queue name for docling jobs
    docling_poll_initial_delay: int = 2  # Initial polling interval in seconds
    docling_poll_max_interval: int = 30  # Maximum polling interval in seconds
    docling_fallback_to_raw: bool = True  # Fallback to raw upload if docling fails/times out

    @property
    def get_docling_redis_url(self) -> str:
        """
        Get docling Redis URL, defaulting to DB 2 if not explicitly set.

        This keeps docling messages separate from Celery queues:
        - DB 0: FILE_REDIS_URL (file processing tasks)
        - DB 1: WEB_REDIS_URL (web processing tasks)
        - DB 2: DOCLING_REDIS_URL (docling RQ jobs and results)
        """
        if self.docling_redis_url:
            return self.docling_redis_url

        # Auto-construct from redis_url, replacing /0 with /2
        if self.redis_url:
            if self.redis_url.endswith('/0'):
                return self.redis_url[:-1] + '2'  # Replace /0 with /2
            elif '/' not in self.redis_url.split('://')[-1]:
                # No database specified, append /2
                return self.redis_url + '/2'

        return "redis://localhost:6379/2"  # Default fallback

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
