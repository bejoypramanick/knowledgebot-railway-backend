"""Logging utilities for Docling Service."""
import logging

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for the service with the given name.
    
    This provides backward compatibility for modules that might still 
    attempt to import this from docling_service.utils.logging.
    """
    return logging.getLogger(name)

# Ensure standard logging is available if someone does 'from docling_service.utils.logging import logging'
# (though that would be weird)
# logging = logging
