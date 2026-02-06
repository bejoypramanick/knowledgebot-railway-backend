import os
import uuid
import boto3
from typing import Optional, Tuple
from botocore.exceptions import ClientError, NoCredentialsError
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("railway_storage", "configuration")

class RailwayStorageService:
    """Service for handling Railway storage (S3-compatible) operations"""
    
    def __init__(self):
        # Railway automatically provides these environment variables when storage is attached
        self.bucket_name = os.getenv('RAILWAY_BUCKET_NAME') or os.getenv('RAILWAY_VOLUME_NAME', 'widget-images')
        self.region = os.getenv('RAILWAY_REGION', 'us-east-1')
        self.endpoint_url = os.getenv('RAILWAY_STORAGE_URL') or os.getenv('AWS_S3_ENDPOINT_URL')
        self.access_key = os.getenv('RAILWAY_STORAGE_ACCESS_KEY') or os.getenv('AWS_ACCESS_KEY_ID')
        self.secret_key = os.getenv('RAILWAY_STORAGE_SECRET_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
        
        # Initialize S3 client
        self._s3_client = None
        self._init_s3_client()
    
    def _init_s3_client(self):
        """Initialize S3 client with Railway storage credentials"""
        try:
            # Log detected environment variables (without exposing sensitive data)
            logger.info(f"🔍 Railway storage configuration detected:")
            logger.info(f"  - Bucket name: {self.bucket_name}")
            logger.info(f"  - Region: {self.region}")
            logger.info(f"  - Endpoint URL: {'✓ Configured' if self.endpoint_url else '✗ Missing'}")
            logger.info(f"  - Access key: {'✓ Configured' if self.access_key else '✗ Missing'}")
            logger.info(f"  - Secret key: {'✓ Configured' if self.secret_key else '✗ Missing'}")
            
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
    
    async def upload_image(self, image_data: bytes, filename: str, content_type: str = 'image/jpeg', image_type: str = 'profile') -> Tuple[str, str]:
        """
        Upload image to Railway storage
        
        Args:
            image_data: Raw image data
            filename: Original filename
            content_type: MIME type of the image
            image_type: Type of image ('profile', 'chatIcon', 'headerIcon') for consistent naming
            
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
            # Use consistent folder structure for Agent Icon and Bubble Icon to ensure unique paths
            if image_type == 'profile':
                # Agent Icon - use dedicated folder with original filename
                unique_filename = f"agent-icon/{filename}"
                # Adjust content type based on actual file extension
                if filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif filename.lower().endswith('.gif'):
                    content_type = 'image/gif'
                elif filename.lower().endswith('.webp'):
                    content_type = 'image/webp'
                elif filename.lower().endswith('.svg'):
                    content_type = 'image/svg+xml'
                elif filename.lower().endswith('.png'):
                    content_type = 'image/png'
            elif image_type == 'chatIcon':
                # Bubble Icon - use dedicated folder with original filename
                unique_filename = f"bubble-icon/{filename}"
                # Adjust content type based on actual file extension
                if filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif filename.lower().endswith('.gif'):
                    content_type = 'image/gif'
                elif filename.lower().endswith('.webp'):
                    content_type = 'image/webp'
                elif filename.lower().endswith('.svg'):
                    content_type = 'image/svg+xml'
                elif filename.lower().endswith('.png'):
                    content_type = 'image/png'
            else:
                # For other types, generate unique filename
                file_extension = filename.split('.')[-1] if '.' in filename else 'jpg'
                unique_filename = f"{uuid.uuid4()}.{file_extension}"
            
            # Upload to Railway storage
            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=unique_filename,
                Body=image_data,
                ContentType=content_type,
                # Note: Railway storage might not support ACLs, so we'll handle access differently
            )
            
            # Generate public URL - Railway storage uses different URL format
            if 'digitaloceanspaces.com' in self.endpoint_url:
                # DigitalOcean Spaces format
                storage_url = f"https://{self.bucket_name}.{self.endpoint_url.replace('https://', '')}/{unique_filename}"
            elif 'r2.cloudflarestorage.com' in self.endpoint_url:
                # Cloudflare R2 format
                storage_url = f"https://pub-{self.bucket_name}.{self.endpoint_url.replace('https://', '')}/{unique_filename}"
            else:
                # Generic S3 format - try to make it public by adding query parameters if needed
                storage_url = f"{self.endpoint_url}/{self.bucket_name}/{unique_filename}"
                
                # For Railway storage, we might need to use a different approach
                # Let's try to generate a presigned URL that lasts for a week (maximum allowed)
                try:
                    presigned_url = self._s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': self.bucket_name, 'Key': unique_filename},
                        ExpiresIn=604800  # 7 days (maximum allowed by Railway)
                    )
                    storage_url = presigned_url
                    logger.info("✅ Using presigned URL for Railway storage (7 days)")
                except Exception as presign_error:
                    logger.warning(f"⚠️ Could not generate presigned URL: {presign_error}")
                    # Fall back to direct URL
            
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
        
        # Try to generate a presigned URL first (most reliable for Railway)
        try:
            presigned_url = self._s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': storage_filename},
                ExpiresIn=604800  # 7 days (maximum allowed by Railway)
            )
            logger.info("✅ Generated presigned URL for image access (7 days)")
            return presigned_url
        except Exception as presign_error:
            logger.warning(f"⚠️ Could not generate presigned URL: {presign_error}")
            
            # Fall back to direct URL format
            if 'digitaloceanspaces.com' in self.endpoint_url:
                # DigitalOcean Spaces format
                return f"https://{self.bucket_name}.{self.endpoint_url.replace('https://', '')}/{storage_filename}"
            elif 'r2.cloudflarestorage.com' in self.endpoint_url:
                # Cloudflare R2 format
                return f"https://pub-{self.bucket_name}.{self.endpoint_url.replace('https://', '')}/{storage_filename}"
            else:
                # Generic S3 format
                return f"{self.endpoint_url}/{self.bucket_name}/{storage_filename}"

# Global storage service instance
railway_storage = RailwayStorageService()
