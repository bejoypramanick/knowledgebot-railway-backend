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
    chatbot_provider: str = "google"
    chatbot_model: str = "gemini-2.0-flash-lite"
    
    # Embedding Configuration
    embedding_provider: str = "google"
    embedding_model: str = "gemini-embedding-001"

    # API Keys (provide via Railway env vars)
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    
    # RAG Optimization Flags
    enable_reranking: bool = False
    enable_context_compression: bool = False
    enable_semantic_caching: bool = True
    
    # Citation Configuration
    enable_citations: bool = True  # Enable DB lookup for inline citation URLs
    
    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None
    
    # Also support DATABASE_URL for backward compatibility
    database_url: Optional[str] = None
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False,
        'extra': 'ignore'
    }


settings = Settings()
