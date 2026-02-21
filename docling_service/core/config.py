"""Configuration for Docling Service."""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service Configuration
    docling_port: int = 8004
    docling_host: str = "0.0.0.0"

    # Docling Processing Configuration
    docling_model_name: str = "granite-docling-258m"  # Larger model for better quality, despite slower performance
    docling_max_file_size_mb: int = 10  # Reduced from 50MB to prevent OOM crashes
    docling_processing_timeout_seconds: int = 1800

    # Processing Configuration
    docling_max_workers: int = 2

    # Database (for logging and health checks)
    railway_postgres_url: Optional[str] = None
    database_url: Optional[str] = None

    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
