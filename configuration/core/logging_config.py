"""
Railway-compatible logging configuration
Ensures logs are properly formatted and visible in Railway deployment
"""
import logging
import os
import sys


def setup_railway_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """
    Configure logging for Railway deployment with proper formatting and output.
    
    Railway captures stdout/stderr, so we need to:
    1. Configure logging to output to stdout
    2. Use Railway-compatible log format
    3. Set appropriate log levels
    4. Ensure all loggers propagate to root
    
    Args:
        service_name: Name of the service for log identification
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logger instance
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure root logger - this is crucial for Railway
    # logging.basicConfig - using OTel formatter instead - using OTel formatter instead(
        level=numeric_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,  # Force output to stdout for Railway
        force=True  # Override any existing configuration
    )
    
    # Get service-specific logger
    logger = logging.getLogger(service_name)
    logger.setLevel(numeric_level)
    
    # Logger will use root logger's handler configured via basicConfig
    # No additional handler needed to prevent duplicates
    
    # Log initialization
    logger.info(f"🚀 Railway logging initialized for service: {service_name}")
    logger.info(f"📊 Log level set to: {level}")
    
    return logger

def configure_all_loggers(level: str = "INFO") -> None:
    """
    Configure all common loggers used in the application for Railway.
    
    This ensures consistent logging across all modules.
    """
    # Common logger names used throughout the application
    logger_names = [
        'api_gateway',
        'configuration', 
        'chatbot_orchestration',
        'knowledgebase_ingestion',
        'website_crawling',
        'shared',
        'token_alerts',
        'token_metrics',
        'rate_limiter',
        'uvicorn',
        'uvicorn.error',
        'uvicorn.access',
        'fastapi',
        'httpx',
        'asyncpg'
    ]
    
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.propagate = False  # Disable propagation to prevent duplicate logs
        
        # Remove existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
    
    # Configure root logger last
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Add stdout handler to root logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    print(f"✅ Configured {len(logger_names)} loggers for Railway deployment")

def get_railway_logger(name: str) -> logging.Logger:
    """
    Get a Railway-compatible logger instance.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # If no handlers exist, configure basic logging
    if not logger.handlers:
        setup_railway_logging(name)
    
    return logger

# Railway-specific environment detection
def is_railway_environment() -> bool:
    """Check if running in Railway environment."""
    return (
        os.getenv('RAILWAY_ENVIRONMENT') is not None or
        os.getenv('RAILWAY_SERVICE_NAME') is not None or
        os.getenv('RAILWAY_PROJECT_NAME') is not None
    )

def get_log_level_from_env() -> str:
    """Get log level from environment variable with fallback."""
    return os.getenv('LOG_LEVEL', 'INFO').upper()

def auto_configure_logging(service_name: str) -> logging.Logger:
    """
    Automatically configure logging based on environment.
    
    - Railway: Configure for stdout output
    - Local: Use standard configuration
    
    Args:
        service_name: Name of the service
    
    Returns:
        Configured logger
    """
    log_level = get_log_level_from_env()
    
    if is_railway_environment():
        logger = setup_railway_logging(service_name, log_level)
        configure_all_loggers(log_level)
        logger.info(f"🚂 Railway environment detected - logging configured for deployment")
    else:
        # Local development - use standard logging
        # logging.basicConfig - using OTel formatter instead - using OTel formatter instead(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logger = logging.getLogger(service_name)
        logger.info(f"💻 Local development environment detected")
    
    return logger
