"""Shared configuration settings for all services."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys (optional - services only require what they need)
    gemini_api_key: Optional[str] = None
    
    # Service URLs
    knowledgebase_ingestion_url: str = "http://localhost:8001"
    website_scraping_url: str = "http://localhost:8002"
    chatbot_orchestration_url: str = "http://localhost:8003"
    
    # API Gateway
    api_gateway_port: int = 8000
    api_gateway_host: str = "0.0.0.0"
    
    # Chatbot Configuration
    chatbot_model: str = "gemini-2.0-flash-exp"
    chatbot_temperature: float = 0.7
    chatbot_max_tokens: int = 2000
    
    # Human-in-the-Loop
    human_in_the_loop_enabled: bool = False
    human_in_the_loop_webhook_url: Optional[str] = None
    
    # Gemini FileSearch
    gemini_filesearch_project_id: Optional[str] = None
    gemini_filesearch_location: str = "us-central1"
    
    # Railway PostgreSQL Configuration (connection URL only)
    railway_postgres_url: Optional[str] = None
    
    # User Context (for tracking uploads)
    default_user_email: str = "globistaan@gmail.com"
    
    model_config = {
        'env_file': ".env",
        'case_sensitive': False
    }


settings = Settings()
