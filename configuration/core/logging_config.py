"""
Railway-compatible logging configuration
Ensures logs are properly formatted and visible in Railway deployment
"""
import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional


# Context variable for correlation ID
correlation_id_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIDFormatter(logging.Formatter):
    """
    Custom formatter that automatically includes correlation ID in log messages.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def format(self, record):
        # Get correlation ID from context
        correlation_id = correlation_id_context.get()
        
        # Add correlation ID to the record if available
        if correlation_id:
            record.correlation_id = correlation_id
            # Modify the message to include correlation ID
            if hasattr(record, 'msg') and record.msg:
                if isinstance(record.msg, str) and not record.msg.startswith(f'[{correlation_id}]'):
                    record.msg = f'[{correlation_id}] {record.msg}'
        else:
            record.correlation_id = 'no-correlation-id'
        
        return super().format(record)


def set_correlation_id(correlation_id: str):
    """Set correlation ID in context for current request."""
    correlation_id_context.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """Get correlation ID from context."""
    return correlation_id_context.get()


def setup_railway_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """
    Configure logging for Railway deployment with proper formatting and output.
    
    Railway captures stdout/stderr, so we need to:
    1. Configure logging to output to stdout
    2. Use Railway-compatible log format with correlation ID
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
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,  # Force output to stdout for Railway
        force=True  # Override any existing configuration
    )
    
    # Get service-specific logger
    logger = logging.getLogger(service_name)
    logger.setLevel(numeric_level)
    
    # Replace the root handler with our correlation ID formatter
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.setFormatter(CorrelationIDFormatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    
    # Log initialization
    logger.info(f"🚀 Railway logging initialized for service: {service_name}")
    logger.info(f"📊 Log level set to: {level}")
    
    return logger

def configure_all_loggers(level: str = "INFO") -> None:
    """
    Configure all common loggers used in the application for Railway.
    
    This ensures consistent logging across all modules with correlation ID support.
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
    
    # Add stdout handler to root logger with correlation ID formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = CorrelationIDFormatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    print(f"✅ Configured {len(logger_names)} loggers for Railway deployment with correlation ID support")

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
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logger = logging.getLogger(service_name)
        logger.info(f"💻 Local development environment detected")
    
    return logger
