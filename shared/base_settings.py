"""
Base Settings for All Knowledgebot Services

Centralises common configuration fields to reduce duplication across 6+ service config.py files.
Each service extends BaseServiceSettings with only service-specific fields.

Common fields:
  - Database: railway_postgres_url, database_url
  - API Keys: gemini_api_key
  - Server: api_gateway_port, api_gateway_host
  - Chatbot: chatbot_model, embedding_model
  - Logging: log_level
  - Model Config: env_file, case_sensitive, extra='ignore'
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class BaseServiceSettings(BaseSettings):
    """Common settings for all knowledgebot services."""

    # API Keys (optional - services only require what they need)
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Server Configuration
    api_gateway_port: int = 8000
    api_gateway_host: str = "0.0.0.0"

    # Database Configuration
    # IMPORTANT: Use railway.internal for internal network, not public URLs
    railway_postgres_url: Optional[str] = None
    database_url: Optional[str] = None  # Backward compatibility

    # Chatbot Configuration
    chatbot_model: str = "gemini-2.5-flash-lite"
    chatbot_provider: str = "google"

    # Embedding Configuration
    embedding_model: str = "gemini-embedding-001"
    embedding_provider: str = "google"

    # Logging Configuration
    log_level: str = "INFO"

    # Model Configuration (applies to all services)
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown env vars
    )

    @property
    def effective_database_url(self) -> Optional[str]:
        """Return the effective database URL, preferring railway_postgres_url."""
        return self.railway_postgres_url or self.database_url
