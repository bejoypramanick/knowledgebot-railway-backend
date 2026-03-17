"""
S3 Client for Debug Attachments
Provides S3 client functionality for uploading debug attachments
"""

import os
import boto3
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "chatbot-orchestration")

_s3_client = None

def get_s3_client():
    """
    Get S3 client for debug attachment uploads.
    Uses Railway Storage S3-compatible service.
    
    Returns:
        boto3 S3 client if configured, None otherwise
    """
    global _s3_client
    
    if _s3_client is not None:
        return _s3_client
    
    try:
        # Get Railway Storage credentials
        endpoint_url = os.getenv('RAILWAY_STORAGE_URL')
        access_key = os.getenv('RAILWAY_STORAGE_ACCESS_KEY')
        secret_key = os.getenv('RAILWAY_STORAGE_SECRET_KEY')
        
        if not endpoint_url:
            logger.warning("📁 RAILWAY_STORAGE_URL not set - S3 client not available")
            return None
            
        if not access_key:
            logger.warning("📁 RAILWAY_STORAGE_ACCESS_KEY not set - S3 client not available")
            return None
            
        if not secret_key:
            logger.warning("📁 RAILWAY_STORAGE_SECRET_KEY not set - S3 client not available")
            return None
        
        # Initialize S3 client
        _s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='us-east-1'  # Required by boto3 but not used by Railway
        )
        
        logger.info("✅ S3 client initialized successfully for debug attachments")
        return _s3_client
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize S3 client: {e}")
        return None

def get_bucket_name() -> str:
    """Get the S3 bucket name for debug attachments"""
    # Try Railway bucket name first, then fallback to generic S3 bucket name
    return os.getenv('RAILWAY_STORAGE_BUCKET_NAME') or os.getenv('S3_BUCKET_NAME', 'default-bucket')