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
    chatbot_model: str = "gemini-2.0-flash-exp"

    # Gemini FileSearch Store Configuration (required from Railway env)
    gemini_file_search_store_name: Optional[str] = None  # FileSearch store display name - MUST be set in Railway env

    # Redis Configuration (used by celery_app.py to connect to Celery broker)
    file_redis_url: Optional[str] = None  # FILE_REDIS_URL from Railway (required)

    # Docling RQ Configuration (separate Redis DB to avoid collisions)
    docling_redis_url: str = Field(..., validation_alias="DOCLING_SERVE_ENG_RQ_REDIS_URL")  # DOCLING_SERVE_ENG_RQ_REDIS_URL from Railway (required - Redis for docling-serve RQ queue)
    docling_rq_queue_name: str = "convert"  # DOCLING_RQ_QUEUE_NAME from Railway (default: "convert" - must match docling-serve worker queue)
    docling_enabled: bool = True  # Set to False to disable docling and use raw uploads
    docling_timeout_seconds: int = 3600  # Processing timeout (default 1 hour = 3600 seconds - configurable via DOCLING_TIMEOUT_SECONDS env var)
    docling_rq_job_timeout_minutes: int = 60  # RQ job timeout in minutes (default 1 hour - matches polling timeout)
    docling_poll_initial_delay: int = 2  # Initial polling interval in seconds
    docling_poll_max_interval: int = 60  # Maximum polling interval in seconds (increased from 30 for longer jobs)
    docling_fallback_to_raw: bool = True  # Fallback to raw upload if docling fails/times out

    def get_docling_redis_url(self) -> str:
        """
        Get docling-serve RQ Redis URL (must be explicitly set in environment).

        This is the Redis instance where docling-serve listens for RQ jobs.

        Raises:
            ValueError: If DOCLING_SERVE_ENG_RQ_REDIS_URL is not set
        """
        if not self.docling_redis_url:
            raise ValueError(
                "DOCLING_SERVE_ENG_RQ_REDIS_URL environment variable is required. "
                "Set it to: redis://redis-XXXXX.railway.internal:6379/2"
            )
        return self.docling_redis_url

    # Railway Storage Configuration (S3-compatible) for docling result storage
    # Docling-serve will upload results directly to Railway Storage using these settings
    railway_bucket_name: Optional[str] = None  # RAILWAY_BUCKET_NAME (bucket for docling outputs)
    railway_region: Optional[str] = None  # RAILWAY_REGION (region for storage)
    railway_storage_url: Optional[str] = None  # RAILWAY_STORAGE_URL (S3-compatible endpoint)
    railway_storage_access_key: Optional[str] = None  # RAILWAY_STORAGE_ACCESS_KEY (for auth)
    railway_storage_secret_key: Optional[str] = None  # RAILWAY_STORAGE_SECRET_KEY (for auth)
    s3_docling_prefix: str = "docling-results"  # S3 key prefix for docling outputs (optional)

    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None

    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
