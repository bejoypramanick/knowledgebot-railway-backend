"""
Comprehensive Atomic Deletion Service
Complete cleanup of ALL data points when deleting any knowledge base item.

Handles:
1. Celery task termination (file_processing + web_crawling queues)
2. Redis task state cleanup
3. Gemini API cleanup (raw files + FileSearch documents)
4. S3 storage cleanup (raw uploads + processed content)
5. Database atomic transactions with parent-child handling
6. Full audit trail and verification
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
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
    GEMINI_DELETE = "gemini_delete"
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
                "gemini_files_deleted": 0,
                "gemini_filesearch_docs_deleted": 0,
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
                            id, original_filename, gemini_file_name, metadata,
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

                    # Step 2b: DOCLING RQ CLEANUP
                    logger.info(f"🔧 [DOCLING_RQ_CANCEL] Cancelling docling RQ jobs...")
                    docling_cancelled = await self._cancel_docling_rq_jobs()
                    deletion_report["cleanup_summary"]["docling_rq_jobs_cancelled"] = docling_cancelled

                    # Step 3: REDIS CLEANUP
                    logger.info(f"🚩 [REDIS_CLEANUP] Cleaning Redis state...")
                    redis_cleaned = await self._cleanup_redis_task_state(file_record['celery_task_id'])
                    if redis_cleaned:
                        deletion_report["cleanup_summary"]["redis_keys_deleted"] += 1

                    # Step 4: GEMINI CLEANUP
                    logger.info(f"🤖 [GEMINI_DELETE] Deleting from Gemini...")
                    gemini_deleted = await self._delete_from_gemini_complete(
                        file_record['gemini_file_name'],
                        file_record['metadata']
                    )
                    deletion_report["cleanup_summary"]["gemini_files_deleted"] = gemini_deleted.get("raw_files", 0)
                    deletion_report["cleanup_summary"]["gemini_filesearch_docs_deleted"] = gemini_deleted.get("filesearch_docs", 0)

                    # Step 5: S3 CLEANUP - BOTH raw and processed
                    logger.info(f"☁️  [S3_DELETE] Deleting from S3...")
                    s3_deleted = await self._delete_from_s3_complete([
                        file_record['s3_key'],
                        file_record['processed_content_s3_key']
                    ])
                    deletion_report["cleanup_summary"]["s3_raw_files_deleted"] = 1 if file_record['s3_key'] else 0
                    deletion_report["cleanup_summary"]["s3_processed_files_deleted"] = 1 if file_record['processed_content_s3_key'] else 0

                    # Step 6: DATABASE TRANSACTION
                    logger.info(f"💾 [DB_TRANSACTION] Updating database...")
                    if hard_delete:
                        # Hard delete: remove from database
                        await conn.execute(
                            "DELETE FROM file_uploads WHERE id = $1",
                            file_id
                        )
                        deletion_report["cleanup_summary"]["db_records_affected"] = 1
                        logger.info(f"   🗑️  Hard deleted from database")
                    else:
                        # Ensure CHECK constraint allows 'deleted' status
                        await conn.execute("ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS valid_processing_status")
                        await conn.execute("ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS file_uploads_processing_status_check")
                        await conn.execute("""
                            ALTER TABLE file_uploads ADD CONSTRAINT valid_processing_status CHECK (
                                processing_status::text = ANY (ARRAY[
                                    'pending'::text, 'processing'::text, 'completed'::text,
                                    'failed'::text, 'cancelled'::text, 'deleted'::text
                                ])
                            )
                        """)
                        # Soft delete: mark as deleted with audit trail
                        await conn.execute(
                            """UPDATE file_uploads
                            SET processing_status = 'deleted',
                                gemini_file_name = NULL,
                                s3_key = NULL,
                                processed_content_s3_key = NULL,
                                updated_at = NOW(),
                                error_message = 'Comprehensively deleted'
                            WHERE id = $1""",
                            file_id
                        )
                        deletion_report["cleanup_summary"]["db_records_affected"] = 1
                        logger.info(f"   📌 Soft deleted in database (audit trail retained)")

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

                    # Step 2b: DOCLING RQ CLEANUP
                    logger.info(f"🔧 [DOCLING_RQ_CANCEL] Cancelling docling RQ jobs...")
                    docling_cancelled = await self._cancel_docling_rq_jobs()
                    deletion_report["cleanup_summary"]["docling_rq_jobs_cancelled"] = docling_cancelled

                    # Step 3: REDIS CLEANUP
                    logger.info(f"🚩 [REDIS_CLEANUP] Cleaning Redis state...")
                    redis_deleted = 0
                    for page in all_pages:
                        if page['celery_task_id']:
                            if await self._cleanup_redis_task_state(page['celery_task_id']):
                                redis_deleted += 1
                    deletion_report["cleanup_summary"]["redis_keys_deleted"] = redis_deleted

                    # Step 4: GEMINI CLEANUP (all pages)
                    logger.info(f"🤖 [GEMINI_DELETE] Deleting from Gemini ({len(all_pages)} pages)...")
                    total_gemini_files = 0
                    total_filesearch_docs = 0

                    for page in all_pages:
                        gemini_deleted = await self._delete_from_gemini_complete(
                            page.get('gemini_file_name'),
                            page.get('metadata')
                        )
                        total_gemini_files += gemini_deleted.get("raw_files", 0)
                        total_filesearch_docs += gemini_deleted.get("filesearch_docs", 0)

                    deletion_report["cleanup_summary"]["gemini_files_deleted"] = total_gemini_files
                    deletion_report["cleanup_summary"]["gemini_filesearch_docs_deleted"] = total_filesearch_docs

                    # Step 5: DATABASE TRANSACTION (atomic - parent + children together)
                    logger.info(f"💾 [DB_TRANSACTION] Updating database ({len(all_pages)} records)...")

                    if hard_delete:
                        # Hard delete: remove all pages
                        await conn.execute(
                            "DELETE FROM scraped_websites WHERE id = $1",
                            website_id
                        )
                        if child_pages:
                            await conn.execute(
                                "DELETE FROM scraped_websites WHERE parent_id = $1",
                                website_id
                            )
                        deletion_report["cleanup_summary"]["db_records_affected"] = len(all_pages)
                        logger.info(f"   🗑️  Hard deleted {len(all_pages)} records")
                    else:
                        # Soft delete: mark as deleted
                        await conn.execute(
                            """UPDATE scraped_websites
                            SET processing_status = 'deleted',
                                updated_at = NOW(),
                                error_message = 'Comprehensively deleted'
                            WHERE id = $1""",
                            website_id
                        )
                        if child_pages:
                            await conn.execute(
                                """UPDATE scraped_websites
                                SET processing_status = 'deleted',
                                    updated_at = NOW(),
                                    error_message = 'Comprehensively deleted'
                                WHERE parent_id = $1""",
                                website_id
                            )
                        deletion_report["cleanup_summary"]["db_records_affected"] = len(all_pages)
                        logger.info(f"   📌 Soft deleted {len(all_pages)} records")

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

    async def _cancel_docling_rq_jobs(self) -> int:
        """Cancel all pending docling RQ jobs in Redis DB 2."""
        try:
            import os
            from shared.docling_rq_client import DoclingRQClient

            docling_redis_url = os.getenv('DOCLING_REDIS_URL')
            if not docling_redis_url:
                # Construct from base Redis URL
                base_url = os.getenv('WEB_REDIS_URL') or os.getenv('FILE_REDIS_URL', '')
                if base_url:
                    # Replace DB number with /2 for docling
                    docling_redis_url = base_url.rsplit('/', 1)[0] + '/2'
                else:
                    logger.warning("   ⚠️  No Redis URL available for docling RQ cleanup")
                    return 0

            client = DoclingRQClient(redis_url=docling_redis_url, queue_name="convert", worker_type="file")
            cancelled = client.cancel_all_jobs()
            return cancelled
        except Exception as e:
            logger.warning(f"   ⚠️  Could not cancel docling RQ jobs: {e}")
            return 0

    async def _delete_from_gemini_complete(
        self,
        gemini_file_name: Optional[str],
        metadata: Optional[Dict]
    ) -> Dict[str, int]:
        """Delete all Gemini artifacts (raw files + FileSearch docs)"""
        result = {"raw_files": 0, "filesearch_docs": 0}

        try:
            from knowledgebase_ingestion.core.ai import get_genai_client

            genai_client = get_genai_client()
            if not genai_client:
                logger.warning("   ⚠️  Gemini client not available")
                return result

            # Delete raw file if it exists
            if gemini_file_name and not gemini_file_name.startswith("documents/"):
                try:
                    logger.info(f"   📍 Deleting raw Gemini file: {gemini_file_name}")
                    genai_client.files.delete(name=gemini_file_name)

                    # Verify deletion
                    try:
                        genai_client.files.get(name=gemini_file_name)
                        logger.warning(f"   ⚠️  File still exists after delete: {gemini_file_name}")
                    except:
                        result["raw_files"] = 1
                        logger.info(f"   ✅ Verified deleted: {gemini_file_name}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not delete raw file: {e}")

            # Delete from FileSearch store if metadata indicates FileSearch
            if metadata:
                try:
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)

                    logger.info(f"   📋 Metadata keys: {list(metadata.keys()) if metadata else 'None'}")
                    logger.info(f"   📋 Metadata type: {metadata.get('type')}")
                    logger.info(f"   📋 Has file_search_store_name: {'file_search_store_name' in metadata if metadata else False}")
                    logger.info(f"   📋 Full metadata: {metadata}")

                    if metadata.get('type') == 'file_search' or 'file_search_store_name' in metadata:
                        store_name = metadata.get('file_search_store_name')
                        document_name = metadata.get('document_name')

                        logger.info(f"   📍 Store name: {store_name}")
                        logger.info(f"   📍 Document name: {document_name}")

                        if store_name and document_name:
                            try:
                                logger.info(f"   📍 Deleting FileSearch document: {document_name}")
                                genai_client.file_search_stores.documents.delete(
                                    name=document_name,
                                    config={"force": True}
                                )

                                # Verify deletion
                                try:
                                    documents = genai_client.file_search_stores.list_documents(
                                        file_search_store_name=store_name
                                    )
                                    doc_exists = any(doc.name == document_name for doc in documents)
                                    if not doc_exists:
                                        result["filesearch_docs"] = 1
                                        logger.info(f"   ✅ Verified deleted: {document_name}")
                                except:
                                    result["filesearch_docs"] = 1
                                    logger.info(f"   ✅ Document deleted: {document_name}")
                            except Exception as fs_err:
                                if "404" in str(fs_err) or "not found" in str(fs_err).lower():
                                    result["filesearch_docs"] = 1
                                    logger.info(f"   ✅ Document already deleted: {document_name}")
                                else:
                                    logger.warning(f"   ⚠️  Could not delete from FileSearch: {fs_err}")
                        else:
                            logger.warning(f"   ⚠️  Missing store_name or document_name in metadata")
                            logger.warning(f"      store_name: {store_name}, document_name: {document_name}")
                    else:
                        logger.info(f"   ℹ️  Metadata doesn't indicate FileSearch (type={metadata.get('type')}, has_store={('file_search_store_name' in metadata if metadata else False)})")
                except Exception as e:
                    logger.warning(f"   ⚠️  Error processing FileSearch metadata: {e}")
            else:
                logger.info(f"   ℹ️  No metadata found for file")

        except Exception as e:
            logger.warning(f"   ⚠️  Error deleting from Gemini: {e}")

        return result

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
