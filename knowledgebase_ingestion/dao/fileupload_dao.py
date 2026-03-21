"""
File Upload Data Access Object
Handles database operations for file uploads only
"""
from typing import Any, Dict, List, Optional
import json

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("fileupload_dao", "knowledgebase-ingestion")

class FileUploadDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get user identifier - check if user exists in users table."""
        query = "SELECT email FROM users WHERE email = :email"
        params = {"email": email}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).scalar()
                logger.log_db_query(query, params, result)
                return result if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def create_file_record(self, record_data: Dict[str, Any]) -> Optional[str]:
        """Insert new file metadata record."""
        logger.info("💾 [FILE_DAO_INSERT] Creating file record in database")

        query = """
            INSERT INTO file_uploads (
                user_role_id, original_filename, display_name, file_size,
                mime_type, file_extension, processing_status, gemini_file_name, gemini_file_uri,
                gemini_state, sha256_hash, s3_key, celery_task_id, char_count, created_at
            ) VALUES (
                :user_role_id, :original_filename, :display_name, :file_size,
                :mime_type, :file_extension, :processing_status, :gemini_file_name, :gemini_file_uri,
                :gemini_state, :sha256_hash, :s3_key, :celery_task_id, :char_count, NOW()
            ) RETURNING id
        """
        params = {
            'user_role_id': record_data.get('user_role_id') or record_data.get('user_id'),
            'original_filename': record_data.get('original_filename'),
            'display_name': record_data.get('file_display_name') or record_data.get('display_name'),
            'file_size': record_data.get('size_bytes') or record_data.get('file_size'),
            'mime_type': record_data.get('mime_type'),
            'file_extension': record_data.get('file_extension'),
            'processing_status': record_data.get('processing_status'),
            'gemini_file_name': record_data.get('gemini_file_name'),
            'gemini_file_uri': record_data.get('gemini_file_uri'),
            'gemini_state': record_data.get('gemini_state'),
            'sha256_hash': record_data.get('sha256_hash'),
            's3_key': record_data.get('s3_key'),
            'celery_task_id': record_data.get('celery_task_id'),
            'char_count': record_data.get('char_count', 0)
        }

        logger.info(f"📝 [FILE_DAO_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [FILE_DAO_PARAMS] Parameters:")
        logger.info(f"    :user_role_id: {params['user_role_id']}")
        logger.info(f"    :original_filename: {params['original_filename']}")
        logger.info(f"    :display_name: {params['display_name']}")
        logger.info(f"    :file_size: {params['file_size']}")
        logger.info(f"    :mime_type: {params['mime_type']}")
        logger.info(f"    :file_extension: {params['file_extension']}")
        logger.info(f"    :processing_status: {params['processing_status']}")
        logger.info(f"    :gemini_file_name: {params['gemini_file_name']}")
        logger.info(f"    :gemini_file_uri: {params['gemini_file_uri']}")
        logger.info(f"    :gemini_state: {params['gemini_state']}")
        logger.info(f"    :sha256_hash: {params['sha256_hash']}")
        logger.info(f"    :s3_key: {params['s3_key']}")
        logger.info(f"    :celery_task_id: {params['celery_task_id']}")
        logger.info(f"    :char_count: {params['char_count']}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).scalar()
                logger.log_db_query(query, params, result)
                await session.commit()

                if result:
                    logger.info(f"✅ [FILE_DAO_INSERT_SUCCESS] File record created with ID: {result}")
                    return str(result)
                else:
                    logger.error(f"❌ [FILE_DAO_INSERT_FAILED] No ID returned from INSERT")
                    return None

        except Exception as e:
            logger.error(f"❌ [FILE_DAO_INSERT_ERROR] Failed to insert file record: {e}")
            logger.log_db_query(query, params, error=e)
            return None

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by ID."""
        query = """
            SELECT id, original_filename, processing_status, error_message,
                   file_size, char_count, mime_type, file_extension, gemini_file_uri, created_at, updated_at
            FROM file_uploads WHERE id = :file_id
        """
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "id": str(result.id),
                        "original_filename": result.original_filename,
                        "processing_status": result.processing_status,
                        "error_message": result.error_message,
                        "mime_type": result.mime_type,
                        "file_extension": result.file_extension,
                        "gemini_file_uri": result.gemini_file_uri,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_all_files(self) -> List[Dict[str, Any]]:
        """Get all files with their status (excludes deleted records)."""
        query = """
            SELECT id, original_filename, processing_status, error_message, mime_type, file_extension, gemini_file_uri, created_at, updated_at
            FROM file_uploads
            WHERE processing_status != 'deleted'
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_inactive_files(self) -> List[Dict[str, Any]]:
        """Get all files that are not pending, processing, queued, and not completed (cancelled, deleted, failed)."""
        query = """
            SELECT id, original_filename, processing_status, error_message,
                   file_size, char_count, mime_type, file_extension, gemini_file_uri, processed_content_s3_key, created_at, updated_at
            FROM file_uploads
            WHERE processing_status NOT IN ('pending', 'processing', 'queued', 'completed')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_active_files(self) -> List[Dict[str, Any]]:
        """Get all files that are pending, processing, queued, or completed."""
        query = """
            SELECT id, original_filename, processing_status, error_message,
                   file_size, char_count, mime_type, file_extension, gemini_file_uri, processed_content_s3_key, created_at, updated_at
            FROM file_uploads
            WHERE processing_status IN ('pending', 'processing', 'queued', 'completed')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_pending_files(self) -> List[Dict[str, Any]]:
        """Get all files with pending or processing status."""
        query = """
            SELECT id, original_filename, processing_status, error_message, mime_type, file_extension, gemini_file_uri, created_at, updated_at
            FROM file_uploads
            WHERE processing_status IN ('pending', 'processing')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def update_file_status(self, file_id: str, status: str, error_message: str = None) -> bool:
        """Update file processing status."""
        logger.info(f"💾 [FILE_DAO_UPDATE] Updating file status for ID: {file_id}")

        query = """
            UPDATE file_uploads
            SET processing_status = :status, error_message = :error_message, updated_at = NOW()
            WHERE id = :file_id
        """
        params = {"file_id": file_id, "status": status, "error_message": error_message}

        logger.info(f"📝 [FILE_DAO_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [FILE_DAO_PARAMS] Parameters:")
        logger.info(f"    :file_id: {params['file_id']}")
        logger.info(f"    :status: {params['status']}")
        logger.info(f"    :error_message: {params['error_message']}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")

                if result.rowcount > 0:
                    logger.info(f"✅ [FILE_DAO_UPDATE_SUCCESS] Status updated to: {status}")
                    return True
                else:
                    logger.warning(f"⚠️  [FILE_DAO_UPDATE_NO_ROWS] No rows updated (file_id {file_id} may not exist)")
                    return False

        except Exception as e:
            logger.error(f"❌ [FILE_DAO_UPDATE_ERROR] Failed to update file status: {e}")
            logger.log_db_query(query, params, error=e)
            return False

    async def update_celery_task_id(self, file_id: str, celery_task_id: str) -> bool:
        """Update file record with real Celery task ID."""
        logger.info(f"💾 [FILE_DAO_UPDATE_TASK_ID] Updating Celery task ID for file ID: {file_id}")

        query = """
            UPDATE file_uploads
            SET celery_task_id = :celery_task_id, updated_at = NOW()
            WHERE id = :file_id
        """
        params = {"file_id": file_id, "celery_task_id": celery_task_id}

        logger.info(f"📝 [FILE_DAO_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [FILE_DAO_PARAMS] Parameters:")
        logger.info(f"    :file_id: {params['file_id']}")
        logger.info(f"    :celery_task_id: {params['celery_task_id']}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")

                if result.rowcount > 0:
                    logger.info(f"✅ [FILE_DAO_UPDATE_SUCCESS] Celery task ID updated to: {celery_task_id}")
                    return True
                else:
                    logger.warning(f"⚠️  [FILE_DAO_UPDATE_NO_ROWS] No rows updated (file_id {file_id} may not exist)")
                    return False

        except Exception as e:
            logger.error(f"❌ [FILE_DAO_UPDATE_ERROR] Failed to update Celery task ID: {e}")
            logger.log_db_query(query, params, error=e)
            return False

    async def cancel_files(self) -> int:
        """Cancel all pending/processing files."""
        logger.info("💾 [FILE_DAO_CANCEL_ALL] Cancelling all pending/processing files")

        query = """
            UPDATE file_uploads
            SET processing_status = 'cancelled', updated_at = NOW()
            WHERE processing_status IN ('pending', 'processing')
        """

        logger.info(f"📝 [FILE_DAO_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [FILE_DAO_FILTER] Target statuses: ['pending', 'processing']")

        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                await session.commit()
                affected_rows = result.rowcount
                logger.log_db_query(query, result=f"UPDATE {affected_rows}")

                if affected_rows > 0:
                    logger.info(f"✅ [FILE_DAO_CANCEL_SUCCESS] Files cancelled: {affected_rows}")
                    return affected_rows
                else:
                    logger.warning(f"⚠️  [FILE_DAO_CANCEL_NO_ROWS] No files to cancel")
                    return 0

        except Exception as e:
            logger.error(f"❌ [FILE_DAO_CANCEL_ERROR] Failed to cancel files: {e}")
            logger.log_db_query(query, error=e)
            return 0

    async def record_api_usage(
        self,
        user_id: Optional[str],
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        api_call_type: str,
        request_metadata: Optional[Dict[str, Any]] = None
    ):
        """Record API usage in the database."""
        query = """
            INSERT INTO token_usage_log
            (user_email, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type, request_metadata, created_at)
            VALUES (:user_email, :provider, :model, :prompt_tokens, :completion_tokens, :total_tokens, :api_call_type, CAST(:request_metadata AS jsonb), NOW())
        """
        params = {
            "user_email": user_id,
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "api_call_type": api_call_type,
            "request_metadata": json.dumps(request_metadata) if request_metadata else None
        }
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "INSERT 1")
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def record_metric(self, metric_data: Dict[str, Any]):
        """Log a metric record."""
        query = """
            INSERT INTO metrics
            (metric_type, metric_name, value, tags, created_at)
            VALUES (:metric_type, :metric_name, :value, CAST(:tags AS jsonb), NOW())
        """
        params = {
            "metric_type": metric_data['metric_type'],
            "metric_name": metric_data.get('metric_name', metric_data['metric_type']),
            "value": metric_data.get('metric_value', metric_data.get('value', 0)),
            "tags": json.dumps(metric_data.get('metadata', {}))
        }
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "INSERT 1")
        except Exception as e:
            logger.log_db_query(query, params, error=e)
