"""
Railway Storage Service for temporary processing files
Unified interface for uploading, downloading, and deleting files during processing
Uses Railway's S3-compatible storage (no AWS S3 fallback)
"""
import os
import uuid
import boto3
from typing import Optional, Tuple
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger("s3_file_storage")


class S3FileStorage:
    """Handle Railway S3-compatible file operations for file and website processing"""

    def __init__(self, bucket_name: str = None):
        # Use provided bucket or fall back to environment variables
        self.bucket_name = bucket_name or os.getenv('PROCESSING_FILES_BUCKET', 'knowledgebot-files')
        self.region = os.getenv('RAILWAY_REGION', 'us-east-1')
        self.endpoint_url = os.getenv('RAILWAY_STORAGE_URL')
        self.access_key = os.getenv('RAILWAY_STORAGE_ACCESS_KEY')
        self.secret_key = os.getenv('RAILWAY_STORAGE_SECRET_KEY')

        self._s3_client = None
        self._init_s3_client()

    def _init_s3_client(self):
        """Initialize Railway storage client"""
        try:
            # Verify all required Railway storage environment variables are set
            if not self.endpoint_url:
                logger.error("❌ RAILWAY_STORAGE_URL environment variable not set")
                self._s3_client = None
                return
            if not self.access_key:
                logger.error("❌ RAILWAY_STORAGE_ACCESS_KEY environment variable not set")
                self._s3_client = None
                return
            if not self.secret_key:
                logger.error("❌ RAILWAY_STORAGE_SECRET_KEY environment variable not set")
                self._s3_client = None
                return

            # Initialize Railway S3-compatible client
            self._s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region
            )
            logger.info(f"✅ Railway storage initialized (bucket: {self.bucket_name}, endpoint: {self.endpoint_url})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Railway storage client: {e}")
            self._s3_client = None

    def is_available(self) -> bool:
        """Check if S3 storage is available"""
        return self._s3_client is not None

    async def upload_file(
        self,
        file_data: bytes,
        original_filename: str,
        file_type: str = "temp"
    ) -> Tuple[bool, str]:
        """
        Upload file to Railway storage

        Args:
            file_data: Raw file bytes
            original_filename: Original filename
            file_type: Type of file ('upload', 'scraped', 'temp')

        Returns:
            Tuple of (success, s3_key/error_message)
        """
        if not self.is_available():
            return False, "Railway storage not available - check RAILWAY_STORAGE_* environment variables"

        try:
            # Create organized key structure: {file_type}/{timestamp}_{uuid}_{filename}
            file_extension = original_filename.split('.')[-1] if '.' in original_filename else 'tmp'
            timestamp = int(__import__('time').time())
            unique_id = str(uuid.uuid4())[:8]
            s3_key = f"processing/{file_type}/{timestamp}_{unique_id}_{original_filename}"

            logger.info(f"📤 Uploading {file_type} file to S3: {s3_key}")

            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_data,
                ContentType=self._get_content_type(original_filename)
            )

            logger.info(f"✅ File uploaded to S3: {s3_key}")
            return True, s3_key

        except ClientError as e:
            error_msg = f"S3 upload failed: {e}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected upload error: {e}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg

    async def download_file(self, s3_key: str) -> Tuple[bool, bytes]:
        """
        Download file from Railway storage

        Args:
            s3_key: S3 object key

        Returns:
            Tuple of (success, file_bytes/error_message)
        """
        if not self.is_available():
            return False, b"Railway storage not available - check RAILWAY_STORAGE_* environment variables"

        try:
            logger.info(f"📥 Downloading file from S3: {s3_key}")

            response = self._s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            file_data = response['Body'].read()

            logger.info(f"✅ Downloaded {len(file_data)} bytes from S3")
            return True, file_data

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                error_msg = f"File not found in S3: {s3_key}"
                logger.warning(f"⚠️ {error_msg}")
            else:
                error_msg = f"S3 download failed: {e}"
                logger.error(f"❌ {error_msg}")
            return False, error_msg.encode()
        except Exception as e:
            error_msg = f"Unexpected download error: {e}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg.encode()

    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from Railway storage

        Args:
            s3_key: S3 object key

        Returns:
            True if deletion was successful
        """
        if not self.is_available():
            logger.warning("⚠️ Railway storage not available, cannot delete file")
            return False

        try:
            logger.info(f"🗑️ Deleting file from S3: {s3_key}")

            self._s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)

            logger.info(f"✅ File deleted from S3: {s3_key}")
            return True

        except ClientError as e:
            logger.error(f"❌ Failed to delete file from S3: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error deleting file: {e}")
            return False

    async def delete_files_batch(self, s3_keys: list) -> Tuple[int, int]:
        """
        Delete multiple files from Railway storage in batch

        Args:
            s3_keys: List of S3 object keys

        Returns:
            Tuple of (deleted_count, failed_count)
        """
        if not self.is_available():
            logger.warning("⚠️ Railway storage not available, cannot delete files")
            return 0, len(s3_keys)

        deleted = 0
        failed = 0

        try:
            # S3 batch delete is limited to 1000 objects per request
            for i in range(0, len(s3_keys), 1000):
                batch = s3_keys[i : i + 1000]
                objects_to_delete = [{'Key': key} for key in batch]

                response = self._s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': objects_to_delete}
                )

                deleted += len(response.get('Deleted', []))
                failed += len(response.get('Errors', []))

                if response.get('Errors'):
                    for error in response.get('Errors', []):
                        logger.warning(f"⚠️ Failed to delete {error['Key']}: {error['Message']}")

            logger.info(f"✅ Batch delete complete: {deleted} deleted, {failed} failed")
            return deleted, failed

        except Exception as e:
            logger.error(f"❌ Batch delete failed: {e}")
            return 0, len(s3_keys)

    def _get_content_type(self, filename: str) -> str:
        """Determine content type from filename"""
        extension = filename.lower().split('.')[-1] if '.' in filename else 'bin'

        content_types = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'doc': 'application/msword',
            'txt': 'text/plain',
            'md': 'text/markdown',
            'html': 'text/html',
            'htm': 'text/html',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'csv': 'text/csv',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'py': 'text/x-python',
            'js': 'application/javascript',
            'json': 'application/json',
            'zip': 'application/zip'
        }

        return content_types.get(extension, 'application/octet-stream')


# Global storage instance
s3_file_storage = S3FileStorage()
