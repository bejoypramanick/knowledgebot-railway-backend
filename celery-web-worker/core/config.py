"""Shared configuration settings for celery-web-worker."""
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

    # Gemini FileSearch Store Configuration (required from Railway env)
    gemini_file_search_store_name: Optional[str] = None  # FileSearch store display name - MUST be set in Railway env

    # Docling Service Configuration (plug-and-play)
    docling_enabled: bool = True  # Set to False to disable docling and use raw uploads
    docling_timeout_seconds: int = 1800  # Processing timeout (30 minutes - handles queue wait time)
    docling_fallback_to_raw: bool = True  # Fallback to raw upload if docling fails/times out
    docling_redis_url: str  # DOCLING_SERVE_ENG_RQ_REDIS_URL from Railway (required - Redis for docling-serve RQ queue)
    docling_rq_queue_name: str = "convert"  # Redis Queue name for docling jobs (must match docling-serve worker queue)
    docling_serve_eng_rq_sub_channel: str = "docling-results-web"  # DOCLING_SERVE_ENG_RQ_WEB_SUB_CHANNEL from Railway (Redis pub/sub channel for web worker results)
    docling_rq_job_timeout_minutes: int = 60  # RQ job timeout in minutes
    docling_poll_initial_delay: int = 2  # Initial polling delay in seconds
    docling_poll_max_interval: int = 60  # Max polling interval in seconds
    s3_docling_prefix: str = "docling-results"  # S3 key prefix for docling outputs (from S3_DOCLING_PREFIX env var)

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }

    def get_docling_redis_url(self) -> str:
        """
        Get the docling-specific Redis URL (DB 2).

        Returns:
            Redis connection URL for docling queue
        """
        if not self.docling_redis_url:
            raise ValueError(
                "DOCLING_REDIS_URL environment variable not set. "
                "Required for docling document processing via Redis Queue (DB 2)."
            )

        return self.docling_redis_url


settings = Settings()
