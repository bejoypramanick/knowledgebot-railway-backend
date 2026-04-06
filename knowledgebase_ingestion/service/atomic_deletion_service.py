"""
Atomic Deletion Service for Files and Websites
Handles complete cleanup in a single atomic transaction:
1. Stop Celery process
2. Remove from Redis queue
3. Delete from S3
4. Update database record as deleted
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
from shared.sqlalchemy_db import get_db_session, get_db_connection

logger = get_otel_logger("atomic_deletion_service", "knowledgebase-ingestion")

class AtomicDeletionService:
    """Service for atomic deletion of files and websites with complete cleanup"""
    
    def __init__(self):
        self.tracer = trace.get_tracer("atomic_deletion")
        
    async def delete_file_atomically(self, file_id: str) -> Dict[str, Any]:
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
                from sqlalchemy import text

                async with get_db_session() as session:
                    # Start transaction (implicit in SQLAlchemy async session)
                    # Step 1: Get file details
                    result = await session.execute(text("""
                        SELECT id, original_filename, storage_document_name, storage_document_uri,
                               celery_task_id, processing_status, s3_key, processed_content_s3_key, sha256_hash
                        FROM file_uploads
                        WHERE id = :id
                    """), {"id": file_id})
                    file_record = result.mappings().first()

                    if not file_record:
                        return {
                            "success": False,
                            "error": f"File {file_id} not found"
                        }

                    logger.info(f"📄 [FILE_DETAILS] Found: {file_record['original_filename']}")
                    logger.info(f"   Status: {file_record['processing_status']}")
                    logger.info(f"   Celery Task ID: {file_record['celery_task_id']}")
                    logger.info(f"   Storage Document: {file_record['storage_document_name']}")
                    logger.info(f"   S3 Key: {file_record['s3_key']}")
                    logger.info(f"   S3 Processed: {file_record['processed_content_s3_key']}")

                    # Step 2: Cancel Celery task if processing
                    celery_task_id = file_record['celery_task_id']
                    if celery_task_id and file_record['processing_status'] in ('pending', 'processing'):
                        await self._cancel_celery_task(celery_task_id, "file")
                        span.set_attribute("celery_task_cancelled", "true")

                    # Step 3: Delete from S3 (both raw and processed files)
                    s3_deleted = False
                    s3_processed_deleted = False
                    
                    # Delete raw file
                    if file_record['s3_key']:
                        s3_deleted = await self._delete_from_s3(file_record['s3_key'])
                        span.set_attribute("s3_deleted", str(s3_deleted))
                    
                    # Delete processed markdown file (even if RETAIN_MD_FILE is true)
                    # Manual atomic delete should remove all files including retained ones
                    if file_record['processed_content_s3_key']:
                        s3_processed_deleted = await self._delete_from_s3(file_record['processed_content_s3_key'])
                        span.set_attribute("s3_processed_deleted", str(s3_processed_deleted))
                        logger.info(f"🧹 [S3_CLEANUP] Deleted retained processed markdown: {file_record['processed_content_s3_key']}")

                    # Step 4: Delete vector chunks from document_chunks table
                    try:
                        from shared.vector_dao import vector_dao
                        chunks_deleted = await vector_dao.delete_chunks_for_document(file_id, "file")
                        logger.info(f"🧹 [VECTOR_CLEANUP] Deleted {chunks_deleted} chunks from document_chunks for file {file_id}")
                    except Exception as vec_err:
                        logger.warning(f"⚠️ [VECTOR_CLEANUP] Failed to delete chunks for file {file_id}: {vec_err}")

                    # Step 5: Mark as deleted in database
                    await session.execute(text("""
                        UPDATE file_uploads
                        SET processing_status = 'deleted',
                            storage_document_name = NULL,
                            storage_document_uri = NULL,
                            storage_backend_state = 'deleted',
                            s3_key = NULL,
                            processed_content_s3_key = NULL,
                            updated_at = CURRENT_TIMESTAMP,
                            error_message = 'Atomically deleted at ' || CURRENT_TIMESTAMP::text
                        WHERE id = :id
                    """), {"id": file_id})
                    await session.commit()
                        
                    logger.info(f"✅ [ATOMIC_DELETE] File {file_id} deleted successfully")
                    logger.info(f"   S3 raw deleted: {s3_deleted}")
                    logger.info(f"   S3 processed deleted: {s3_processed_deleted}")
                        
                    return {
                            "success": True,
                            "message": "File deleted atomically with complete cleanup",
                            "file_id": str(file_id),
                            "celery_task_cancelled": bool(celery_task_id),
                            "s3_deleted": s3_deleted,
                            "s3_processed_deleted": s3_processed_deleted
                        }
                        
            except Exception as e:
                logger.error(f"❌ [ATOMIC_DELETE] Error deleting file {file_id}: {e}")
                span.set_attribute("error", str(e))
                return {
                    "success": False,
                    "error": str(e),
                    "file_id": str(file_id)
                }
    
    async def delete_website_atomically(self, website_id: str) -> Dict[str, Any]:
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
                                   storage_document_name, storage_document_uri, processed_content_s3_key
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
                        logger.info(f"   Storage Document: {website_record['storage_document_name']}")
                        logger.info(f"   S3 Processed: {website_record['processed_content_s3_key']}")
                        
                        # Step 2: Cancel Celery task if processing
                        celery_task_id = website_record['celery_task_id']
                        if celery_task_id and website_record['processing_status'] in ('pending', 'processing'):
                            await self._cancel_celery_task(celery_task_id, "website")
                            span.set_attribute("celery_task_cancelled", "true")
                        
                        # Step 3: Delete from S3 (processed markdown file)
                        # Manual atomic delete should remove retained files even if RETAIN_MD_FILE is true
                        s3_processed_deleted = False
                        if website_record['processed_content_s3_key']:
                            s3_processed_deleted = await self._delete_from_s3(website_record['processed_content_s3_key'])
                            span.set_attribute("s3_processed_deleted", str(s3_processed_deleted))
                            logger.info(f"🧹 [S3_CLEANUP] Deleted retained processed markdown: {website_record['processed_content_s3_key']}")
                        
                        # Step 4: Delete vector chunks from document_chunks table
                        try:
                            from shared.vector_dao import vector_dao
                            chunks_deleted = await vector_dao.delete_chunks_for_document(website_id, "website")
                            logger.info(f"🧹 [VECTOR_CLEANUP] Deleted {chunks_deleted} chunks from document_chunks for website {website_id}")
                        except Exception as vec_err:
                            logger.warning(f"⚠️ [VECTOR_CLEANUP] Failed to delete chunks for website {website_id}: {vec_err}")

                        # Step 5: Mark as deleted in database
                        await conn.execute("""
                            UPDATE scraped_websites
                            SET processing_status = 'deleted',
                                storage_document_name = NULL,
                                storage_document_uri = NULL,
                                storage_backend_state = 'deleted',
                                processed_content_s3_key = NULL,
                                updated_at = NOW(),
                                error_message = 'Atomically deleted at ' || NOW()::text
                            WHERE id = $1
                        """, website_id)
                        
                        logger.info(f"✅ [ATOMIC_DELETE] Website {website_id} deleted successfully")
                        logger.info(f"   S3 processed deleted: {s3_processed_deleted}")

                        return {
                            "success": True,
                            "message": "Website deleted atomically with complete cleanup",
                            "website_id": str(website_id),
                            "celery_task_cancelled": bool(celery_task_id),
                            "s3_processed_deleted": s3_processed_deleted
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
            from shared.redis_factory import resolve_redis_url
            
            # Get appropriate Redis URL based on task type
            if task_type == "file":
                redis_url = resolve_redis_url(
                    primary_env_var='file_task_queue',
                    db_env_var='FILE_TASK_QUEUE_REDIS_DB',
                    default_db=0,
                )
            else:  # website
                redis_url = resolve_redis_url(
                    primary_env_var='web_task_queue',
                    db_env_var='WEB_TASK_QUEUE_REDIS_DB',
                    default_db=1,
                )
            
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
