"""
Website Crawler Service
Handles website crawling operations
"""

from website_crawling.core.otel_logger import get_otel_logger

logger = get_otel_logger("crawler_service", "website-crawling")
