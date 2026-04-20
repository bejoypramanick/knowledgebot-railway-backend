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
import re

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
        self, item_id: str, item_type: ItemType, hard_delete: bool = False
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
        logger.info(
            f"🗑️  [COMPREHENSIVE_DELETION_START] Deleting {item_type.value} ID: {item_id}"
        )
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
                "db_records_affected": 0,
            },
            "errors": [],
            "warnings": [],
        }

        try:
            # Route to appropriate deletion method
            if item_type == ItemType.FILE:
                result = await self._delete_file_comprehensive(
                    item_id, hard_delete, deletion_report
                )
            elif item_type in [ItemType.WEBSITE, ItemType.WEBPAGE, ItemType.SITEMAP]:
                result = await self._delete_website_comprehensive(
                    item_id, hard_delete, deletion_report
                )
            else:
                raise ValueError(f"Unknown item type: {item_type}")

            if result.get("success"):
                # Global UI cache invalidation (DB7)
                # This MUST happen after the DB transaction has committed
                await self._invalidate_kb_ui_cache(result)

            return result

        except Exception as e:
            import traceback

            logger.error(f"❌ [DELETION_FAILED] Critical error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_report["success"] = False
            deletion_report["errors"].append(
                {
                    "step": "unknown",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            deletion_report["completed_at"] = datetime.utcnow().isoformat()
            return deletion_report

    async def _invalidate_kb_ui_cache(self, deletion_report: Dict[str, Any]) -> None:
        """Invalidate Redis UI cache after a successful individual KB delete."""
        try:
            from shared.redis_ui_cache import invalidate_all_kb_caches

            deleted = await invalidate_all_kb_caches()
            deletion_report["cleanup_summary"]["kb_ui_cache_keys_deleted"] = deleted
            logger.info(f"🧹 [KB_UI_CACHE] Invalidated {deleted} KB UI cache keys")
        except Exception as cache_err:
            warning = f"KB UI cache invalidation failed: {cache_err}"
            deletion_report.setdefault("warnings", []).append(warning)
            logger.warning(f"⚠️ [KB_UI_CACHE] {warning}")

    # ============================================================================
    # FILE DELETION
    # ============================================================================

    async def _delete_file_comprehensive(
        self, file_id: str, hard_delete: bool, deletion_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Complete deletion of uploaded file"""

        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Step 1: LOOKUP
                    logger.info(
                        f"[DELETE_FILE] file_id={file_id} step=LOOKUP start=true"
                    )
                    file_record = await conn.fetchrow(
                        """SELECT
                            id, original_filename, storage_document_name, metadata,
                            celery_task_id, processing_status, s3_key, processed_content_s3_key
                        FROM file_uploads
                        WHERE id = $1
                        FOR UPDATE""",
                        file_id,
                    )

                    if not file_record:
                        deletion_report["success"] = False
                        deletion_report["errors"].append(
                            {
                                "step": DeletionStep.LOOKUP.value,
                                "error": f"File {file_id} not found",
                            }
                        )
                        deletion_report["completed_at"] = datetime.utcnow().isoformat()
                        logger.error(
                            f"[DELETE_FILE] file_id={file_id} step=LOOKUP found=false"
                        )
                        return deletion_report

                    deletion_report["filename"] = file_record["original_filename"]
                    logger.info(
                        f"[DELETE_FILE] file_id={file_id} step=LOOKUP found=true filename={file_record['original_filename']} status={file_record['processing_status']}"
                    )

                    # Step 2: CELERY REVOCATION
                    logger.info(f"🔪 [CELERY_REVOKE] Terminating Celery tasks...")
                    celery_revoked = await self._revoke_celery_task(
                        file_record["celery_task_id"], task_type="file"
                    )
                    deletion_report["cleanup_summary"]["celery_tasks_revoked"] = (
                        1 if celery_revoked else 0
                    )

                    # Step 3: REDIS CLEANUP
                    logger.info(f"🚩 [REDIS_CLEANUP] Cleaning Redis state...")
                    redis_cleaned = await self._cleanup_redis_task_state(
                        file_record["celery_task_id"]
                    )
                    if redis_cleaned:
                        deletion_report["cleanup_summary"]["redis_keys_deleted"] += 1
                    file_redis_keys_deleted = await self._cleanup_file_redis_references(
                        file_id, file_record
                    )
                    deletion_report["cleanup_summary"]["redis_keys_deleted"] += (
                        file_redis_keys_deleted
                    )

                    # Step 4: S3 CLEANUP - BOTH raw and processed
                    logger.info(f"☁️  [S3_DELETE] Deleting from S3...")
                    await self._delete_from_s3_complete(
                        [file_record["s3_key"], file_record["processed_content_s3_key"]]
                    )
                    deletion_report["cleanup_summary"]["s3_raw_files_deleted"] = (
                        1 if file_record["s3_key"] else 0
                    )
                    deletion_report["cleanup_summary"]["s3_processed_files_deleted"] = (
                        1 if file_record["processed_content_s3_key"] else 0
                    )

                    # Step 5: VECTOR CHUNK CLEANUP
                    logger.info(f"🧹 [VECTOR_CLEANUP] Deleting vector chunks...")
                    try:
                        from shared.vector_dao import vector_dao

                        chunks_deleted = await vector_dao.delete_chunks_for_document(
                            file_id, "file"
                        )
                        deletion_report["cleanup_summary"]["vector_chunks_deleted"] = (
                            chunks_deleted
                        )
                        logger.info(
                            f"   🧹 Deleted {chunks_deleted} vector chunks for file {file_id}"
                        )
                    except Exception as vec_err:
                        logger.warning(f"   ⚠️ Vector chunk cleanup failed: {vec_err}")
                        deletion_report["warnings"].append(
                            f"Vector cleanup failed: {vec_err}"
                        )

                    # Step 6: DATABASE TRANSACTION
                    logger.info(
                        f"[DELETE_FILE] file_id={file_id} step=DB_TRANSACTION start=true hard_delete={hard_delete}"
                    )
                    if hard_delete:
                        # Hard delete: remove from database
                        status_str = await conn.execute(
                            "DELETE FROM file_uploads WHERE id = $1", file_id
                        )
                        affected = int(status_str.split()[-1])
                        logger.info(
                            f"[DELETE_FILE] file_id={file_id} step=DB_TRANSACTION operation=DELETE affected={affected}"
                        )
                        deletion_report["cleanup_summary"]["db_records_affected"] = (
                            affected
                        )
                    else:
                        # Soft delete: mark as deleted with audit trail
                        logger.info(
                            f"[DELETE_FILE] file_id={file_id} step=DB_TRANSACTION executing_update=true"
                        )
                        try:
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
                                WHERE id = $1""",
                                file_id,
                            )
                            logger.info(
                                f"[DELETE_FILE] file_id={file_id} step=UPDATE status_raw='{status_str}'"
                            )
                            affected = int(status_str.split()[-1])
                            logger.info(
                                f"[DELETE_FILE] file_id={file_id} step=DB_TRANSACTION operation=UPDATE affected={affected}"
                            )

                            # Verify
                            verify = await conn.fetch(
                                "SELECT id, processing_status FROM file_uploads WHERE id = $1",
                                file_id,
                            )
                            if verify:
                                for v in verify:
                                    logger.info(
                                        f"[DELETE_FILE] file_id={file_id} step=VERIFY id={v['id']} status={v['processing_status']}"
                                    )
                            else:
                                logger.info(
                                    f"[DELETE_FILE] file_id={file_id} step=VERIFY result=NOT_FOUND"
                                )
                        except Exception as update_err:
                            logger.error(
                                f"[DELETE_FILE] file_id={file_id} step=UPDATE error={str(update_err)}"
                            )
                            raise

                        deletion_report["cleanup_summary"]["db_records_affected"] = (
                            affected
                        )

                    # Transaction committed successfully
                    deletion_report["success"] = True
                    deletion_report["completed_at"] = datetime.utcnow().isoformat()
                    logger.info(
                        f"[DELETE_FILE] file_id={file_id} step=DB_TRANSACTION success=true affected={affected}"
                    )
                    return deletion_report

        except Exception as e:
            import traceback

            logger.error(f"❌ [FILE_DELETION_ERROR] {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            deletion_report["success"] = False
            deletion_report["errors"].append(
                {"step": DeletionStep.DB_TRANSACTION.value, "error": str(e)}
            )
            deletion_report["completed_at"] = datetime.utcnow().isoformat()
            return deletion_report

    # ============================================================================
    # WEBSITE/PAGE DELETION
    # ============================================================================

    async def _delete_website_comprehensive(
        self, website_id: str, hard_delete: bool, deletion_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Complete deletion of website/page with parent-child handling"""

        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Step 1: LOOKUP
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=LOOKUP start=true"
                    )
                    website_record = await conn.fetchrow(
                        """SELECT
                            id, original_url, domain, parent_id, depth, metadata,
                            celery_task_id, processing_status
                        FROM scraped_websites
                        WHERE id = $1
                        FOR UPDATE""",
                        website_id,
                    )
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=LOOKUP found={website_record is not None}"
                    )

                    if not website_record:
                        deletion_report["success"] = False
                        deletion_report["errors"].append(
                            {
                                "step": DeletionStep.LOOKUP.value,
                                "error": f"Website {website_id} not found",
                            }
                        )
                        deletion_report["completed_at"] = datetime.utcnow().isoformat()
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} success=false error=NOT_FOUND"
                        )
                        return deletion_report

                    is_parent = website_record["parent_id"] is None
                    deletion_report["url"] = website_record["original_url"]
                    deletion_report["is_parent"] = is_parent
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} url={website_record['original_url']} is_parent={is_parent} status={website_record['processing_status']}"
                    )

                    # Get all child pages if this is a parent
                    child_pages = []
                    if is_parent:
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} step=LOOKUP_CHILDREN start=true"
                        )
                        child_pages = await conn.fetch(
                            """SELECT
                                id, original_url, celery_task_id, processing_status
                            FROM scraped_websites
                            WHERE parent_id = $1
                            FOR UPDATE""",
                            website_id,
                        )
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} step=LOOKUP_CHILDREN child_count={len(child_pages)}"
                        )
                        for cp in child_pages:
                            logger.info(
                                f"[DELETE_WEBSITE] website_id={website_id} child_id={cp['id']} child_status={cp['processing_status']}"
                            )
                        deletion_report["child_pages_count"] = len(child_pages)

                    # Collect all pages to delete (parent + children)
                    all_pages = [website_record] + child_pages

                    # Step 2: CELERY REVOCATION
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=CELERY_REVOKE start=true"
                    )
                    celery_revoked = 0

                    if website_record["celery_task_id"]:
                        if await self._revoke_celery_task(
                            website_record["celery_task_id"], "website"
                        ):
                            celery_revoked += 1

                    for child in child_pages:
                        if child["celery_task_id"]:
                            if await self._revoke_celery_task(
                                child["celery_task_id"], "website"
                            ):
                                celery_revoked += 1

                    deletion_report["cleanup_summary"]["celery_tasks_revoked"] = (
                        celery_revoked
                    )
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=CELERY_REVOKE celery_revoked={celery_revoked}"
                    )

                    # Step 3: REDIS CLEANUP
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=REDIS_CLEANUP start=true"
                    )
                    redis_deleted = 0
                    for page in all_pages:
                        if page["celery_task_id"]:
                            if await self._cleanup_redis_task_state(
                                page["celery_task_id"]
                            ):
                                redis_deleted += 1
                    deletion_report["cleanup_summary"]["redis_keys_deleted"] = (
                        redis_deleted
                    )
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=REDIS_CLEANUP redis_deleted={redis_deleted}"
                    )

                    # Step 4: VECTOR CHUNK CLEANUP
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=VECTOR_CLEANUP start=true"
                    )
                    try:
                        from shared.vector_dao import vector_dao

                        all_page_ids = [str(p["id"]) for p in all_pages]
                        chunks_deleted = await vector_dao.delete_chunks_for_documents(
                            all_page_ids, "website"
                        )
                        deletion_report["cleanup_summary"]["vector_chunks_deleted"] = (
                            chunks_deleted
                        )
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} step=VECTOR_CLEANUP chunks_deleted={chunks_deleted}"
                        )
                    except Exception as vec_err:
                        logger.warning(
                            f"[DELETE_WEBSITE] website_id={website_id} step=VECTOR_CLEANUP error={vec_err}"
                        )
                        deletion_report["warnings"].append(
                            f"Vector cleanup failed: {vec_err}"
                        )

                    # Step 5: DATABASE TRANSACTION (atomic - parent + children together)
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=DB_TRANSACTION start=true hard_delete={hard_delete} page_count={len(all_pages)}"
                    )

                    if hard_delete:
                        status = await conn.execute(
                            "DELETE FROM scraped_websites WHERE id = $1 OR parent_id = $1",
                            website_id,
                        )
                        affected = int(status.split()[-1])
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} step=DB_TRANSACTION operation=DELETE affected={affected}"
                        )
                        deletion_report["cleanup_summary"]["db_records_affected"] = (
                            affected
                        )
                    else:
                        logger.info(
                            f"[DELETE_WEBSITE] website_id={website_id} step=DB_TRANSACTION executing_update=true"
                        )

                        # Debug: show what records would match the WHERE clause
                        try:
                            debug_match = await conn.fetch(
                                "SELECT id, processing_status, parent_id FROM scraped_websites WHERE id = $1 OR parent_id = $1",
                                website_id,
                            )
                            logger.info(
                                f"[DELETE_WEBSITE] website_id={website_id} step=DEBUG matching_records_count={len(debug_match) if debug_match else 0}"
                            )
                            if debug_match:
                                for dm in debug_match:
                                    logger.info(
                                        f"[DELETE_WEBSITE] website_id={website_id} step=DEBUG match_id={dm['id']} parent_id={dm['parent_id']} current_status={dm['processing_status']}"
                                    )
                        except Exception as debug_err:
                            logger.error(
                                f"[DELETE_WEBSITE] website_id={website_id} step=DEBUG error={str(debug_err)}"
                            )

                        try:
                            status = await conn.execute(
                                """UPDATE scraped_websites
                                SET processing_status = 'deleted', updated_at = NOW()
                                WHERE id = $1 OR parent_id = $1""",
                                website_id,
                            )
                            logger.info(
                                f"[DELETE_WEBSITE] website_id={website_id} step=UPDATE status_raw='{status}'"
                            )
                            affected = int(status.split()[-1])
                            logger.info(
                                f"[DELETE_WEBSITE] website_id={website_id} step=DB_TRANSACTION operation=UPDATE affected={affected}"
                            )
                        except Exception as update_err:
                            logger.error(
                                f"[DELETE_WEBSITE] website_id={website_id} step=UPDATE error={str(update_err)}"
                            )
                            raise

                        # Verify the update worked - fetch after update within same transaction
                        try:
                            verify = await conn.fetch(
                                "SELECT id, processing_status, parent_id FROM scraped_websites WHERE id = $1 OR parent_id = $1",
                                website_id,
                            )
                            logger.info(
                                f"[DELETE_WEBSITE] website_id={website_id} step=VERIFY query_result_count={len(verify) if verify else 0}"
                            )
                            if verify:
                                for v in verify:
                                    logger.info(
                                        f"[DELETE_WEBSITE] website_id={website_id} step=VERIFY id={v['id']} parent_id={v['parent_id']} status={v['processing_status']}"
                                    )
                            else:
                                logger.info(
                                    f"[DELETE_WEBSITE] website_id={website_id} step=VERIFY result=NOT_FOUND"
                                )
                        except Exception as verify_err:
                            logger.error(
                                f"[DELETE_WEBSITE] website_id={website_id} step=VERIFY error={str(verify_err)}"
                            )

                        deletion_report["cleanup_summary"]["db_records_affected"] = (
                            affected
                        )

                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} step=DB_TRANSACTION success=true affected={affected}"
                    )
                    deletion_report["success"] = True
                    deletion_report["completed_at"] = datetime.utcnow().isoformat()
                    logger.info(
                        f"[DELETE_WEBSITE] website_id={website_id} final_report success={deletion_report['success']} affected={deletion_report.get('cleanup_summary', {}).get('db_records_affected')} completed_at={deletion_report.get('completed_at')}"
                    )
                    return deletion_report

        except Exception as e:
            import traceback

            logger.error(
                f"[DELETE_WEBSITE] website_id={website_id} step=ERROR error={str(e)}"
            )
            logger.error(f"[DELETE_WEBSITE] traceback={traceback.format_exc()}")
            logger.error(f"[DELETE_WEBSITE] deletion_report_at_error={deletion_report}")
            deletion_report["success"] = False
            deletion_report["errors"].append(
                {"step": DeletionStep.DB_TRANSACTION.value, "error": str(e)}
            )
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
            celery_app.control.revoke(task_id, terminate=True, signal="SIGKILL")

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
            redis_queue.cleanup_file_task_state(task_id, keep_cancel_flag=True)

            logger.info(f"   ✅ Redis cleaned: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Could not clean Redis: {e}")
            return False

    async def _cleanup_file_redis_references(
        self, file_id: str, file_record: Any
    ) -> int:
        """Delete Redis cache/state keys that directly reference an individual file."""
        terms = self._redis_search_terms(
            [
                file_id,
                self._record_value(file_record, "celery_task_id"),
                self._record_value(file_record, "storage_document_name"),
                self._record_value(file_record, "s3_key"),
                self._record_value(file_record, "processed_content_s3_key"),
            ]
        )
        if not terms:
            return 0

        redis_targets = [
            ("file_task_queue", "FILE_TASK_QUEUE_REDIS_DB", 0),
            ("citation_cache", "CITATION_CACHE_REDIS_DB", 4),
            ("ui_data_cache", "UI_CACHE_REDIS_DB", 7),
        ]
        total_deleted = 0

        for purpose, db_env_var, default_db in redis_targets:
            try:
                from shared.redis_factory import create_async_redis_client

                client = await create_async_redis_client(
                    primary_env_var=f"delete_file_{purpose}",
                    db_env_var=db_env_var,
                    default_db=default_db,
                    cache=False,
                )
                try:
                    deleted = await self._delete_redis_keys_matching_terms(
                        client, terms
                    )
                    total_deleted += deleted
                    logger.info(
                        f"   🧹 [REDIS_FILE_CLEANUP] Deleted {deleted} keys from {purpose} "
                        f"for file {file_id}"
                    )
                finally:
                    await client.aclose()
            except Exception as redis_err:
                logger.warning(
                    f"   ⚠️ [REDIS_FILE_CLEANUP] Failed for {purpose} on file {file_id}: {redis_err}"
                )

        try:
            redis_queue = RedisMessageQueue()
            total_deleted += redis_queue.cleanup_file_task_state(
                self._record_value(file_record, "celery_task_id"),
                extra_terms=terms,
            )
        except Exception as queue_err:
            logger.warning(
                f"   ⚠️ [REDIS_FILE_CLEANUP] Queue message cleanup failed for file {file_id}: {queue_err}"
            )

        return total_deleted

    def _record_value(self, record: Any, field: str) -> Optional[Any]:
        try:
            return record[field]
        except Exception:
            return None

    def _redis_search_terms(self, values: List[Optional[Any]]) -> List[str]:
        terms = []
        seen = set()
        for value in values:
            if value is None:
                continue
            text_value = str(value).strip()
            if len(text_value) < 8 or text_value in seen:
                continue
            seen.add(text_value)
            terms.append(text_value)
        return terms

    async def _delete_redis_keys_matching_terms(
        self, client: Any, terms: List[str]
    ) -> int:
        deleted = 0
        key_names = set()
        for term in terms:
            safe_pattern = self._redis_glob_escape(term)
            async for key in client.scan_iter(match=f"*{safe_pattern}*", count=500):
                key_names.add(key)

        if key_names:
            deleted = await client.delete(*key_names)
        return int(deleted or 0)

    def _redis_glob_escape(self, value: str) -> str:
        return re.sub(r"([][?*\\])", r"\\\1", value)

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

            logger.info(
                f"   ✅ S3 cleanup complete: {deleted_count}/{len(keys_to_delete)} deleted"
            )
            return deleted_count

        except Exception as e:
            logger.error(f"   ❌ S3 deletion error: {e}")
            return 0


# Singleton instance
comprehensive_deletion_service = ComprehensiveDeletionService()
