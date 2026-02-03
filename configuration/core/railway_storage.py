import os
import uuid
import boto3
from typing import Optional, Tuple
from botocore.exceptions import ClientError, NoCredentialsError
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("railway_storage", "configuration")

class RailwayStorageService:
    """Service for handling Railway storage (S3-compatible) operations"""
    
    def __init__(self):
        self.bucket_name = os.getenv('RAILWAY_BUCKET_NAME', 'widget-images')
        self.region = os.getenv('RAILWAY_REGION', 'us-east-1')
        self.endpoint_url = os.getenv('RAILWAY_STORAGE_URL')
        self.access_key = os.getenv('RAILWAY_STORAGE_ACCESS_KEY')
        self.secret_key = os.getenv('RAILWAY_STORAGE_SECRET_KEY')
        
        # Initialize S3 client
        self._s3_client = None
        self._init_s3_client()
    
    def _init_s3_client(self):
        """Initialize S3 client with Railway storage credentials"""
        try:
            if self.endpoint_url and self.access_key and self.secret_key:
                self._s3_client = boto3.client(
                    's3',
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region
                )
                logger.info("✅ Railway storage client initialized successfully")
            else:
                logger.warning("⚠️ Railway storage credentials not found, using fallback mode")
                self._s3_client = None
        except Exception as e:
            logger.error(f"❌ Failed to initialize Railway storage client: {e}")
            self._s3_client = None
    
    def is_available(self) -> bool:
        """Check if Railway storage is available"""
        return self._s3_client is not None
    
    async def upload_image(self, image_data: bytes, filename: str, content_type: str = 'image/jpeg') -> Tuple[str, str]:
        """
        Upload image to Railway storage
        
        Args:
            image_data: Raw image data
            filename: Original filename
            content_type: MIME type of the image
            
        Returns:
            Tuple of (storage_url, storage_filename)
        """
        if not self.is_available():
            # Fallback: return base64 data URL
            import base64
            base64_data = base64.b64encode(image_data).decode('utf-8')
            data_url = f"data:{content_type};base64,{base64_data}"
            return data_url, filename
        
        try:
            # Generate unique filename
            file_extension = filename.split('.')[-1] if '.' in filename else 'jpg'
            unique_filename = f"{uuid.uuid4()}.{file_extension}"
            
            # Upload to Railway storage
            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=unique_filename,
                Body=image_data,
                ContentType=content_type,
                ACL='public-read'  # Make publicly accessible
            )
            
            # Generate public URL
            storage_url = f"{self.endpoint_url}/{self.bucket_name}/{unique_filename}"
            
            logger.info(f"✅ Image uploaded successfully: {unique_filename}")
            return storage_url, unique_filename
            
        except ClientError as e:
            logger.error(f"❌ Failed to upload image to Railway storage: {e}")
            # Fallback to base64
            import base64
            base64_data = base64.b64encode(image_data).decode('utf-8')
            data_url = f"data:{content_type};base64,{base64_data}"
            return data_url, filename
        except Exception as e:
            logger.error(f"❌ Unexpected error uploading image: {e}")
            raise
    
    async def delete_image(self, storage_filename: str) -> bool:
        """
        Delete image from Railway storage
        
        Args:
            storage_filename: Filename in storage
            
        Returns:
            True if deletion was successful
        """
        if not self.is_available():
            logger.warning("⚠️ Railway storage not available, cannot delete image")
            return False
        
        try:
            self._s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=storage_filename
            )
            logger.info(f"✅ Image deleted successfully: {storage_filename}")
            return True
            
        except ClientError as e:
            logger.error(f"❌ Failed to delete image from Railway storage: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error deleting image: {e}")
            return False
    
    def get_public_url(self, storage_filename: str) -> str:
        """
        Get public URL for stored image
        
        Args:
            storage_filename: Filename in storage
            
        Returns:
            Public URL for the image
        """
        if not self.is_available():
            logger.warning("⚠️ Railway storage not available, cannot generate public URL")
            return ""
        
        return f"{self.endpoint_url}/{self.bucket_name}/{storage_filename}"

# Global storage service instance
railway_storage = RailwayStorageService()
