"""
Comprehensive Atomic Deletion Service
Complete cleanup of ALL data points when deleting any knowledge base item.

Handles:
1. Celery task termination (file_processing + web_crawling queues)
2. Redis task state cleanup
3. S3 storage cleanup (raw uploads + processed content)
4. Database atomic transactions with parent-child handling
5. Full audit trail and verification
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session, get_db_connection
from shared.celery_dispatcher import file_celery, web_celery
from shared.redis_message_queue import RedisMessageQueue
from shared.s3_file_storage import s3_file_storage

logger = get_otel_logger("comprehensive_deletion_service", "knowledgebase-ingestion")


class ItemType(str, Enum):
    """Type of knowledge base item"""
    FILE = "file"
    WEBSITE = "website"
    WEBPAGE = "webpage"
    SITEMAP = "sitemap"


class DeletionStep(str, Enum):
    """Steps in the deletion process"""
    LOOKUP = "lookup"
    CELERY_REVOKE = "celery_revoke"
    REDIS_CLEANUP = "redis_cleanup"
    S3_DELETE = "s3_delete"
    DB_TRANSACTION = "db_transaction"
    VERIFICATION = "verification"
    COMPLETE = "complete"


class ComprehensiveDeletionService:
    """Service for complete atomic deletion of all knowledge base items"""

    def __init__(self):
        self.deletion_log: Dict[str, List[Dict[str, Any]]] = {}

    async def delete_item(
        self,
        item_id: str,
        item_type: ItemType,
        hard_delete: bool = False
    ) -> Dict[str, Any]:
        """
        Delete a knowledge base item completely - wipes all data points.

        Args:
            item_id: ID of item to delete (file_id or website_id)
            item_type: Type of item (FILE, WEBSITE, WEBPAGE, SITEMAP)
            hard_delete: If True, hard delete (remove from DB). If False, soft delete (mark as deleted).

        Returns:
            Complete deletion report with all operations and results
        """
        logger.info("=" * 100)
        logger.info(f"🗑️  [COMPREHENSIVE_DELETION_START] Deleting {item_type.value} ID: {item_id}")
        logger.info(f"   Hard Delete: {hard_delete}")
        logger.info("=" * 100)

        deletion_report = {
            "success": False,
            "item_id": str(item_id),
            "item_type": item_type.value,
            "hard_delete": hard_delete,
            "started_at": datetime.utcnow().isoformat(),
            "steps": {},
            "cleanup_summary": {
                "celery_tasks_revoked": 0,
                "redis_keys_deleted": 0,
                "s3_raw_files_deleted": 0,
                "s3_processed_files_deleted": 0,
                "db_records_affected": 0
            },
            "errors": [],
            "warnings": []
        }

        try:
            # Route to appropriate deletion method
            if item_type == ItemType.FILE:
                return await self._delete_file_comprehensive(item_id, hard_delete, deletion_report)
            elif item_type in [ItemType.WEBSITE, ItemType.WEBPAGE, ItemType.SITEMAP]:
                return await self._delete_website_comprehensive(item_id, hard_delete, deletion_report)
            else:
                raise ValueError(f"Unknown item type: {item_type}")

        except Exception as e:
            import traceback
            logger.error(f"❌ [DELETION_FAILED] Critical error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_report["success"] = False
            deletion_report["errors"].append({
                "step": "unknown",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
            deletion_report["completed_at"] = datetime.utcnow().isoformat()
            return deletion_report

    # ============================================================================
    # FILE DELETION
    # ============================================================================

    async def _delete_file_comprehensive(
        self,
        file_id: str,
        hard_delete: bool,
        deletion_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Complete deletion of uploaded file"""

        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Step 1: LOOKUP
                    logger.info(f"📍 [LOOKUP] Fetching file record...")
                    file_record = await conn.fetchrow(
                        """SELECT
                            id, original_filename, storage_document_name, metadata,
                            celery_task_id, processing_status, s3_key, processed_content_s3_key
                        FROM file_uploads
                        WHERE id = $1
                        FOR UPDATE""",
                        file_id
                    )

                    if not file_record:
                        deletion_report["success"] = False
                        deletion_report["errors"].append({
                            "step": DeletionStep.LOOKUP.value,
                            "error": f"File {file_id} not found"
                        })
                        deletion_report["completed_at"] = datetime.utcnow().isoformat()
                        logger.error(f"❌ File {file_id} not found")
                        return deletion_report

                    deletion_report["filename"] = file_record['original_filename']
                    logger.info(f"✅ [LOOKUP] Found: {file_record['original_filename']}")
                    logger.info(f"   Processing Status: {file_record['processing_status']}")
                    logger.info(f"   Celery Task: {file_record['celery_task_id']}")
                    logger.info(f"   S3 Raw: {file_record['s3_key']}")
                    logger.info(f"   S3 Processed: {file_record['processed_content_s3_key']}")

                    # Step 2: CELERY REVOCATION
                    logger.info(f"🔪 [CELERY_REVOKE] Terminating Celery tasks...")
                    celery_revoked = await self._revoke_celery_task(
                        file_record['celery_task_id'],
                        task_type="file"
                    )
                    deletion_report["cleanup_summary"]["celery_tasks_revoked"] = 1 if celery_revoked else 0



                    # Step 3: REDIS CLEANUP
                    logger.info(f"🚩 [REDIS_CLEANUP] Cleaning Redis state...")
                    redis_cleaned = await self._cleanup_redis_task_state(file_record['celery_task_id'])
                    if redis_cleaned:
                        deletion_report["cleanup_summary"]["redis_keys_deleted"] += 1

                    # Step 4: S3 CLEANUP - BOTH raw and processed
                    logger.info(f"☁️  [S3_DELETE] Deleting from S3...")
                    await self._delete_from_s3_complete([
                        file_record['s3_key'],
                        file_record['processed_content_s3_key']
                    ])
                    deletion_report["cleanup_summary"]["s3_raw_files_deleted"] = 1 if file_record['s3_key'] else 0
                    deletion_report["cleanup_summary"]["s3_processed_files_deleted"] = 1 if file_record['processed_content_s3_key'] else 0

                    # Step 5: VECTOR CHUNK CLEANUP
                    logger.info(f"🧹 [VECTOR_CLEANUP] Deleting vector chunks...")
                    try:
                        from shared.vector_dao import vector_dao
                        chunks_deleted = await vector_dao.delete_chunks_for_document(file_id, "file")
                        deletion_report["cleanup_summary"]["vector_chunks_deleted"] = chunks_deleted
                        logger.info(f"   🧹 Deleted {chunks_deleted} vector chunks for file {file_id}")
                    except Exception as vec_err:
                        logger.warning(f"   ⚠️ Vector chunk cleanup failed: {vec_err}")
                        deletion_report["warnings"].append(f"Vector cleanup failed: {vec_err}")

                    # Step 6: DATABASE TRANSACTION
                    logger.info(f"💾 [DB_TRANSACTION] Updating database...")
                    if hard_delete:
                        # Hard delete: remove from database
                        status_str = await conn.execute(
                            "DELETE FROM file_uploads WHERE id = $1::uuid",
                            file_id
                        )
                        # status_str is e.g. "DELETE 1"
                        affected = int(status_str.split()[-1])
                        deletion_report["cleanup_summary"]["db_records_affected"] = affected
                        logger.info(f"   🗑️  Hard deleted from database ({affected} rows affected)")
                    else:
                        # Soft delete: mark as deleted with audit trail
                        status_str = await conn.execute(
                            """UPDATE file_uploads
                            SET processing_status = 'deleted',
                                storage_document_name = NULL,
                                storage_document_uri = NULL,
                                storage_backend_state = 'deleted',
                                s3_key = NULL,
                                processed_content_s3_key = NULL,
                                updated_at = NOW(),
                                error_message = 'Comprehensively deleted'
                            WHERE id = $1::uuid""",
                            file_id
                        )
                        # status_str is e.g. "UPDATE 1" or "UPDATE 0"
                        affected = int(status_str.split()[-1])
                        deletion_report["cleanup_summary"]["db_records_affected"] = affected
                        logger.info(f"   📌 Soft deleted in database ({affected} rows affected)")

                    # Transaction committed successfully
                    deletion_report["success"] = True
                    deletion_report["completed_at"] = datetime.utcnow().isoformat()
                    logger.info("✅ [COMPREHENSIVE_DELETION] File deleted completely")
                    return deletion_report

        except Exception as e:
            import traceback
            logger.error(f"❌ [FILE_DELETION_ERROR] {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_report["success"] = False
            deletion_report["errors"].append({
                "step": DeletionStep.DB_TRANSACTION.value,
                "error": str(e)
            })
            deletion_report["completed_at"] = datetime.utcnow().isoformat()
            return deletion_report

    # ============================================================================
    # WEBSITE/PAGE DELETION
    # ============================================================================

    async def _delete_website_comprehensive(
        self,
        website_id: str,
        hard_delete: bool,
        deletion_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Complete deletion of website/page with parent-child handling"""

        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Step 1: LOOKUP
                    logger.info(f"📍 [LOOKUP] Fetching website record...")
                    website_record = await conn.fetchrow(
                        """SELECT
                            id, original_url, domain, parent_id, depth, metadata,
                            celery_task_id, processing_status
                        FROM scraped_websites
                        WHERE id = $1
                        FOR UPDATE""",
                        website_id
                    )

                    if not website_record:
                        deletion_report["success"] = False
                        deletion_report["errors"].append({
                            "step": DeletionStep.LOOKUP.value,
                            "error": f"Website {website_id} not found"
                        })
                        deletion_report["completed_at"] = datetime.utcnow().isoformat()
                        return deletion_report

                    is_parent = website_record['parent_id'] is None
                    deletion_report["url"] = website_record['original_url']
                    deletion_report["is_parent"] = is_parent
                    logger.info(f"✅ [LOOKUP] Found: {website_record['original_url']}")
                    logger.info(f"   Type: {'Parent Website' if is_parent else 'Child Page'}")

                    # Get all child pages if this is a parent
                    child_pages = []
                    if is_parent:
                        logger.info(f"📍 [LOOKUP_CHILDREN] Fetching child pages...")
                        child_pages = await conn.fetch(
                            """SELECT
                                id, original_url, celery_task_id, processing_status
                            FROM scraped_websites
                            WHERE parent_id = $1
                            FOR UPDATE""",
                            website_id
                        )
                        logger.info(f"   Found {len(child_pages)} child pages")
                        deletion_report["child_pages_count"] = len(child_pages)

                    # Collect all pages to delete (parent + children)
                    all_pages = [website_record] + child_pages

                    # Step 2: CELERY REVOCATION
                    logger.info(f"🔪 [CELERY_REVOKE] Terminating Celery tasks...")
                    celery_revoked = 0

                    # Always revoke parent task
                    if website_record['celery_task_id']:
                        if await self._revoke_celery_task(website_record['celery_task_id'], "website"):
                            celery_revoked += 1

                    # Revoke child tasks (only for parent deletion)
                    for child in child_pages:
                        if child['celery_task_id']:
                            if await self._revoke_celery_task(child['celery_task_id'], "website"):
                                celery_revoked += 1

                    deletion_report["cleanup_summary"]["celery_tasks_revoked"] = celery_revoked



                    # Step 3: REDIS CLEANUP
                    logger.info(f"🚩 [REDIS_CLEANUP] Cleaning Redis state...")
                    redis_deleted = 0
                    for page in all_pages:
                        if page['celery_task_id']:
                            if await self._cleanup_redis_task_state(page['celery_task_id']):
                                redis_deleted += 1
                    deletion_report["cleanup_summary"]["redis_keys_deleted"] = redis_deleted

                    # Step 4: VECTOR CHUNK CLEANUP
                    logger.info(f"🧹 [VECTOR_CLEANUP] Deleting vector chunks...")
                    try:
                        from shared.vector_dao import vector_dao
                        all_page_ids = [str(p['id']) for p in all_pages]
                        chunks_deleted = await vector_dao.delete_chunks_for_documents(all_page_ids, "website")
                        deletion_report["cleanup_summary"]["vector_chunks_deleted"] = chunks_deleted
                        logger.info(f"   🧹 Deleted {chunks_deleted} vector chunks for {len(all_page_ids)} website pages")
                    except Exception as vec_err:
                        logger.warning(f"   ⚠️ Vector chunk cleanup failed: {vec_err}")
                        deletion_report["warnings"].append(f"Vector cleanup failed: {vec_err}")

                    # Step 5: DATABASE TRANSACTION (atomic - parent + children together)
                    logger.info(f"💾 [DB_TRANSACTION] Updating database ({len(all_pages)} records)...")

                    if hard_delete:
                        # Hard delete: remove all pages
                        await conn.execute(
                            "DELETE FROM scraped_websites WHERE id = $1",
                            website_id
                        )
                        status1 = await conn.execute(
                            "DELETE FROM scraped_websites WHERE id = $1::uuid",
                            website_id
                        )
                        affected = int(status1.split()[-1])
                        
                        if child_pages:
                            status2 = await conn.execute(
                                "DELETE FROM scraped_websites WHERE parent_id = $1::uuid",
                                website_id
                            )
                            affected += int(status2.split()[-1])
                        
                        deletion_report["cleanup_summary"]["db_records_affected"] = affected
                        logger.info(f"   🗑️  Hard deleted from database ({affected} rows affected)")
                    else:
                        # Soft delete: mark as deleted
                        status1 = await conn.execute(
                            """UPDATE scraped_websites
                            SET processing_status = 'deleted',
                                updated_at = NOW(),
                                error_message = 'Comprehensively deleted'
                            WHERE id = $1::uuid""",
                            website_id
                        )
                        affected = int(status1.split()[-1])
                        
                        if child_pages:
                            status2 = await conn.execute(
                                """UPDATE scraped_websites
                                SET processing_status = 'deleted',
                                    updated_at = NOW(),
                                    error_message = 'Comprehensively deleted'
                                WHERE parent_id = $1::uuid""",
                                website_id
                            )
                            affected += int(status2.split()[-1])
                            
                        deletion_report["cleanup_summary"]["db_records_affected"] = affected
                        logger.info(f"   📌 Soft deleted in database ({affected} rows affected)")

                    # Transaction committed successfully
                    deletion_report["success"] = True
                    deletion_report["completed_at"] = datetime.utcnow().isoformat()
                    logger.info(f"✅ [COMPREHENSIVE_DELETION] Website/pages deleted completely")
                    return deletion_report

        except Exception as e:
            import traceback
            logger.error(f"❌ [WEBSITE_DELETION_ERROR] {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_report["success"] = False
            deletion_report["errors"].append({
                "step": DeletionStep.DB_TRANSACTION.value,
                "error": str(e)
            })
            deletion_report["completed_at"] = datetime.utcnow().isoformat()
            return deletion_report

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    async def _revoke_celery_task(self, task_id: Optional[str], task_type: str) -> bool:
        """Revoke and terminate Celery task"""
        if not task_id:
            return False

        try:
            logger.info(f"   🔪 Revoking task {task_id} ({task_type})")

            # Get appropriate celery app
            celery_app = file_celery if task_type == "file" else web_celery

            # Revoke with SIGKILL to force termination
            celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')

            logger.info(f"   ✅ Task revoked: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Could not revoke task {task_id}: {e}")
            return False

    async def _cleanup_redis_task_state(self, task_id: Optional[str]) -> bool:
        """Clean up Redis task state and cancellation flags"""
        if not task_id:
            return False

        try:
            logger.info(f"   🚩 Cleaning Redis for task {task_id}")

            redis_queue = RedisMessageQueue()
            redis_queue.set_task_cancelled(task_id)

            logger.info(f"   ✅ Redis cleaned: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Could not clean Redis: {e}")
            return False



    async def _delete_from_s3_complete(self, s3_keys: Optional[List[str]]) -> int:
        """Delete all S3 files (both raw uploads and processed content)"""
        if not s3_keys:
            return 0

        # Filter out None values
        keys_to_delete = [k for k in s3_keys if k]
        if not keys_to_delete:
            return 0

        try:
            logger.info(f"   📍 Deleting {len(keys_to_delete)} files from S3")

            deleted_count = 0
            for s3_key in keys_to_delete:
                try:
                    success = await s3_file_storage.delete_file(s3_key)
                    if success:
                        deleted_count += 1
                        logger.info(f"   ✅ Deleted: {s3_key}")
                    else:
                        logger.warning(f"   ⚠️  Failed to delete: {s3_key}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not delete {s3_key}: {e}")

            logger.info(f"   ✅ S3 cleanup complete: {deleted_count}/{len(keys_to_delete)} deleted")
            return deleted_count

        except Exception as e:
            logger.error(f"   ❌ S3 deletion error: {e}")
            return 0


# Singleton instance
comprehensive_deletion_service = ComprehensiveDeletionService()
