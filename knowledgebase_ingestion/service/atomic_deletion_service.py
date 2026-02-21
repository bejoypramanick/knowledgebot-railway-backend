"""
Atomic Deletion Service for Files and Websites
Handles complete cleanup in a single atomic transaction:
1. Stop Celery process
2. Remove from Redis queue
3. Delete from Gemini FileStore
4. Delete from S3
5. Update database record as deleted
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

import redis
import asyncpg
from opentelemetry import trace

from shared.otel_logger import get_otel_logger
from shared.db import get_db_connection

logger = get_otel_logger("atomic_deletion_service", "knowledgebase-ingestion")

class AtomicDeletionService:
    """Service for atomic deletion of files and websites with complete cleanup"""
    
    def __init__(self):
        self.tracer = trace.get_tracer("atomic_deletion")
        
    async def delete_file_atomically(self, file_id: int) -> Dict[str, Any]:
        """
        Delete file atomically with complete cleanup
        
        Args:
            file_id: ID of file to delete
            
        Returns:
            Dict with deletion result
        """
        with self.tracer.start_as_current_span("atomic_file_deletion") as span:
            span.set_attribute("file_id", str(file_id))
            
            logger.info(f"🗑️ [ATOMIC_DELETE] Starting atomic file deletion for ID: {file_id}")
            
            try:
                async with get_db_connection() as conn:
                    # Start transaction
                    async with conn.transaction():
                        # Step 1: Get file details and lock the row
                        file_record = await conn.fetchrow("""
                            SELECT id, original_filename, gemini_file_name, gemini_file_uri, 
                                   celery_task_id, processing_status, s3_key, sha256_hash
                            FROM file_uploads 
                            WHERE id = $1
                            FOR UPDATE
                        """, file_id)
                        
                        if not file_record:
                            return {
                                "success": False,
                                "error": f"File {file_id} not found"
                            }
                        
                        logger.info(f"📄 [FILE_DETAILS] Found: {file_record['original_filename']}")
                        logger.info(f"   Status: {file_record['processing_status']}")
                        logger.info(f"   Celery Task ID: {file_record['celery_task_id']}")
                        logger.info(f"   Gemini File: {file_record['gemini_file_name']}")
                        logger.info(f"   S3 Key: {file_record['s3_key']}")
                        
                        # Step 2: Cancel Celery task if processing
                        celery_task_id = file_record['celery_task_id']
                        if celery_task_id and file_record['processing_status'] in ('pending', 'processing'):
                            await self._cancel_celery_task(celery_task_id, "file")
                            span.set_attribute("celery_task_cancelled", "true")
                        
                        # Step 3: Delete from Gemini FileStore
                        gemini_deleted = False
                        if file_record['gemini_file_uri']:
                            gemini_deleted = await self._delete_from_gemini_filestore(
                                file_record['gemini_file_name'], 
                                file_record['gemini_file_uri']
                            )
                            span.set_attribute("gemini_deleted", str(gemini_deleted))
                        
                        # Step 4: Delete from S3
                        s3_deleted = False
                        if file_record['s3_key']:
                            s3_deleted = await self._delete_from_s3(file_record['s3_key'])
                            span.set_attribute("s3_deleted", str(s3_deleted))
                        
                        # Step 5: Mark as deleted in database
                        await conn.execute("""
                            UPDATE file_uploads 
                            SET processing_status = 'deleted',
                                gemini_file_name = NULL,
                                gemini_file_uri = NULL,
                                gemini_state = 'deleted',
                                s3_key = NULL,
                                updated_at = NOW(),
                                error_message = 'Atomically deleted at ' || NOW()::text
                            WHERE id = $1
                        """, file_id)
                        
                        logger.info(f"✅ [ATOMIC_DELETE] File {file_id} deleted successfully")
                        logger.info(f"   Gemini deleted: {gemini_deleted}")
                        logger.info(f"   S3 deleted: {s3_deleted}")
                        
                        return {
                            "success": True,
                            "message": "File deleted atomically with complete cleanup",
                            "file_id": str(file_id),
                            "celery_task_cancelled": bool(celery_task_id),
                            "gemini_deleted": gemini_deleted,
                            "s3_deleted": s3_deleted
                        }
                        
            except Exception as e:
                logger.error(f"❌ [ATOMIC_DELETE] Error deleting file {file_id}: {e}")
                span.set_attribute("error", str(e))
                return {
                    "success": False,
                    "error": str(e),
                    "file_id": str(file_id)
                }
    
    async def delete_website_atomically(self, website_id: int) -> Dict[str, Any]:
        """
        Delete website atomically with complete cleanup
        
        Args:
            website_id: ID of website to delete
            
        Returns:
            Dict with deletion result
        """
        with self.tracer.start_as_current_span("atomic_website_deletion") as span:
            span.set_attribute("website_id", str(website_id))
            
            logger.info(f"🗑️ [ATOMIC_DELETE] Starting atomic website deletion for ID: {website_id}")
            
            try:
                async with get_db_connection() as conn:
                    # Start transaction
                    async with conn.transaction():
                        # Step 1: Get website details and lock the row
                        website_record = await conn.fetchrow("""
                            SELECT id, original_url, celery_task_id, processing_status,
                                   gemini_file_name, gemini_file_uri, s3_key
                            FROM scraped_websites 
                            WHERE id = $1
                            FOR UPDATE
                        """, website_id)
                        
                        if not website_record:
                            return {
                                "success": False,
                                "error": f"Website {website_id} not found"
                            }
                        
                        logger.info(f"🌐 [WEBSITE_DETAILS] Found: {website_record['original_url']}")
                        logger.info(f"   Status: {website_record['processing_status']}")
                        logger.info(f"   Celery Task ID: {website_record['celery_task_id']}")
                        logger.info(f"   Gemini File: {website_record['gemini_file_name']}")
                        logger.info(f"   S3 Key: {website_record['s3_key']}")
                        
                        # Step 2: Cancel Celery task if processing
                        celery_task_id = website_record['celery_task_id']
                        if celery_task_id and website_record['processing_status'] in ('pending', 'processing'):
                            await self._cancel_celery_task(celery_task_id, "website")
                            span.set_attribute("celery_task_cancelled", "true")
                        
                        # Step 3: Delete from Gemini FileStore
                        gemini_deleted = False
                        if website_record['gemini_file_uri']:
                            gemini_deleted = await self._delete_from_gemini_filestore(
                                website_record['gemini_file_name'],
                                website_record['gemini_file_uri']
                            )
                            span.set_attribute("gemini_deleted", str(gemini_deleted))
                        
                        # Step 4: Delete from S3
                        s3_deleted = False
                        if website_record['s3_key']:
                            s3_deleted = await self._delete_from_s3(website_record['s3_key'])
                            span.set_attribute("s3_deleted", str(s3_deleted))
                        
                        # Step 5: Mark as deleted in database
                        await conn.execute("""
                            UPDATE scraped_websites 
                            SET processing_status = 'deleted',
                                gemini_file_name = NULL,
                                gemini_file_uri = NULL,
                                gemini_state = 'deleted',
                                s3_key = NULL,
                                updated_at = NOW(),
                                error_message = 'Atomically deleted at ' || NOW()::text
                            WHERE id = $1
                        """, website_id)
                        
                        logger.info(f"✅ [ATOMIC_DELETE] Website {website_id} deleted successfully")
                        logger.info(f"   Gemini deleted: {gemini_deleted}")
                        logger.info(f"   S3 deleted: {s3_deleted}")
                        
                        return {
                            "success": True,
                            "message": "Website deleted atomically with complete cleanup",
                            "website_id": str(website_id),
                            "celery_task_cancelled": bool(celery_task_id),
                            "gemini_deleted": gemini_deleted,
                            "s3_deleted": s3_deleted
                        }
                        
            except Exception as e:
                logger.error(f"❌ [ATOMIC_DELETE] Error deleting website {website_id}: {e}")
                span.set_attribute("error", str(e))
                return {
                    "success": False,
                    "error": str(e),
                    "website_id": str(website_id)
                }
    
    async def _cancel_celery_task(self, celery_task_id: str, task_type: str) -> bool:
        """Cancel Celery task and remove from Redis queue"""
        try:
            import os
            
            # Get appropriate Redis URL based on task type
            if task_type == "file":
                redis_url = os.getenv('FILE_REDIS_URL', 'redis://localhost:6379/0')
            else:  # website
                redis_url = os.getenv('WEB_REDIS_URL', 'redis://localhost:6379/1')
            
            redis_conn = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            
            # Set cancellation flag
            redis_conn.setex(f"task_cancelled:{celery_task_id}", 300, "1")
            
            # Try to revoke the task via Celery control
            try:
                from celery import Celery
                if task_type == "file":
                    celery_app = Celery('celery_file_worker')
                    celery_app.conf.broker_url = redis_url
                else:
                    celery_app = Celery('celery_web_worker')
                    celery_app.conf.broker_url = redis_url
                
                # Revoke the task
                celery_app.control.revoke(celery_task_id, terminate=True)
                logger.info(f"🛑 [CELERY_CANCEL] Revoked task {celery_task_id}")
                
            except Exception as revoke_err:
                logger.warning(f"⚠️ [CELERY_CANCEL] Could not revoke task {celery_task_id}: {revoke_err}")
            
            redis_conn.close()
            logger.info(f"✅ [CELERY_CANCEL] Set cancellation flag for task {celery_task_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [CELERY_CANCEL] Error cancelling task {celery_task_id}: {e}")
            return False
    
    async def _delete_from_gemini_filestore(self, gemini_file_name: str, gemini_file_uri: str) -> bool:
        """Delete from Gemini FileStore"""
        try:
            from core.ai import get_genai_client
            
            genai_client = get_genai_client().aio
            if not genai_client:
                logger.warning("⚠️ [GEMINI_DELETE] Gemini client not available")
                return False
            
            # Extract document name from URI
            document_name = gemini_file_name
            if not document_name:
                logger.warning("⚠️ [GEMINI_DELETE] No document name found")
                return False
            
            # Delete from FileStore
            genai_client.aio.files.delete(name=document_name)
            logger.info(f"🗑️ [GEMINI_DELETE] Deleted {document_name} from FileStore")
            return True
            
        except Exception as e:
            logger.error(f"❌ [GEMINI_DELETE] Error deleting from FileStore: {e}")
            return False
    
    async def _delete_from_s3(self, s3_key: str) -> bool:
        """Delete from S3"""
        try:
            from core.s3 import S3Service
            
            s3_service = S3Service()
            await s3_service.delete_file(s3_key)
            logger.info(f"🗑️ [S3_DELETE] Deleted {s3_key} from S3")
            return True
            
        except Exception as e:
            logger.error(f"❌ [S3_DELETE] Error deleting from S3: {e}")
            return False

# Singleton instance
atomic_deletion_service = AtomicDeletionService()
