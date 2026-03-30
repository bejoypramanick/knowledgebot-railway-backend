"""Configuration settings for Chatbot Orchestration service."""

from typing import Optional

from shared.base_settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    """Chatbot Orchestration specific settings (extends common BaseServiceSettings)."""

    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_crawling_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"

    # RAG Optimization Flags
    enable_reranking: bool = False
    enable_context_compression: bool = False
    enable_semantic_caching: bool = True

    # Citation Configuration
    enable_citations: bool = True  # Enable DB lookup for inline citation URLs


settings = Settings()
