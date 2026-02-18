"""
File Service for Celery File Processing Worker
Handles business logic for file processing operations
"""
import asyncio
import os
import json
from typing import Dict, List, Any, Optional
from ..dao.file_dao import FileDAO
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_service", "celery-file-worker")

class FileService:
    def __init__(self):
        self.file_dao = FileDAO()

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file by ID."""
        return await self.file_dao.get_file_by_id(file_id)

    async def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """Update file processing status."""
        try:
            await self.file_dao.update_file_status(file_id, status, error_message)
            logger.info(f"✅ Updated file {file_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update file {file_id} status: {e}")
            return False

    async def get_files_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get files by processing status."""
        return await self.file_dao.get_files_by_status(status)

    async def delete_file_record(self, file_id: str):
        """Delete file record."""
        try:
            await self.file_dao.delete_file_record(file_id)
            logger.info(f"✅ Deleted file record {file_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete file record {file_id}: {e}")
            return False

    async def create_file_record(self, file_data: Dict[str, Any]) -> Optional[str]:
        """Create new file record."""
        try:
            file_id = await self.file_dao.insert_file_record(file_data)
            if file_id:
                logger.info(f"✅ Created file record {file_id}")
                return file_id
            else:
                logger.error("❌ Failed to create file record")
                return None
        except Exception as e:
            logger.error(f"❌ Error creating file record: {e}")
            return None

    async def is_task_cancelled(self, celery_task_id: str) -> bool:
        """Check if task has been marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            redis_conn = redis_lib.from_url(redis_url)

            cancelled_key = f"task_cancelled:{celery_task_id}"
            result = redis_conn.exists(cancelled_key)
            redis_conn.close()

            return bool(result)
        except Exception as e:
            logger.warning(f"⚠️ Error checking cancellation status: {e}")
            return False

    async def process_file_content(self, file_id: int, tmp_path: str, original_filename: str, 
                              detected_mime_type: str, celery_task_id: str = None):
        """Process file content - moved from tasks.py"""
        try:
            from knowledgebase_ingestion.service.ingestion_service import process_with_gemini
            from knowledgebase_ingestion.service.docling_integration import (
                process_with_docling, should_use_docling_for_file, create_markdown_temp_file
            )
            from shared.html_processor import extract_content_from_html

            markdown_tmp_path = None
            docling_metadata = {}

            # 1. Route HTML files
            if detected_mime_type == 'text/html' or original_filename.lower().endswith(('.html', '.htm')):
                logger.info(f"🌐 [CELERY] Processing HTML file: {original_filename}")
                try:
                    markdown_content, html_metadata = extract_content_from_html(tmp_path)
                    
                    if markdown_content:
                        markdown_tmp_path = await create_markdown_temp_file(markdown_content)
                        tmp_path = markdown_tmp_path
                        original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                        detected_mime_type = 'text/markdown'
                        docling_metadata = html_metadata
                        
                        logger.info(f"✅ [CELERY] HTML converted to markdown: {markdown_tmp_path}")
                except Exception as e:
                    logger.error(f"❌ [CELERY] HTML processing failed: {e}")
                    await self.update_file_status(str(file_id), "failed", f"HTML processing error: {str(e)}")
                    return {"success": False, "error": f"HTML processing error: {str(e)}"}

            # 2. Route to Docling for PDF/DOCX/DOC files
            elif should_use_docling_for_file(detected_mime_type, original_filename):
                logger.info(f"📄 [CELERY] Processing with Docling: {original_filename}")
                try:
                    docling_result = await process_with_docling(tmp_path, original_filename)
                    
                    if docling_result.get("success"):
                        markdown_tmp_path = docling_result.get("markdown_path")
                        docling_metadata = docling_result.get("metadata", {})
                        tmp_path = markdown_tmp_path
                        original_filename = original_filename.rsplit('.', 1)[0] + '.md'
                        detected_mime_type = 'text/markdown'
                        
                        logger.info(f"✅ [CELERY] Docling processed: {markdown_tmp_path}")
                except Exception as e:
                    logger.error(f"❌ [CELERY] Docling processing failed: {e}")
                    await self.update_file_status(str(file_id), "failed", f"Docling processing error: {str(e)}")
                    return {"success": False, "error": f"Docling processing error: {str(e)}"}

            # 3. Route to Gemini for all processed content
            if markdown_tmp_path:
                logger.info(f"🤖 [CELERY] Uploading to Gemini: {original_filename}")
                try:
                    gemini_result = await process_with_gemini(
                        file_id=str(file_id),
                        tmp_path=markdown_tmp_path,
                        original_filename=original_filename,
                        detected_mime_type=detected_mime_type,
                        user_email=None,  # Will be passed separately
                        file_size=0,  # Will be calculated separately
                        sha256_hash="",  # Will be calculated separately
                        celery_task_id=celery_task_id
                    )
                    
                    if gemini_result.get("success"):
                        logger.info(f"✅ [CELERY] Gemini upload successful: {original_filename}")
                        return {"success": True, "gemini_result": gemini_result}
                    else:
                        error_msg = gemini_result.get("error", "Unknown Gemini error")
                        logger.error(f"❌ [CELERY] Gemini upload failed: {error_msg}")
                        await self.update_file_status(str(file_id), "failed", error_msg)
                        return {"success": False, "error": error_msg}
                except Exception as e:
                    logger.error(f"❌ [CELERY] Gemini upload error: {e}")
                    await self.update_file_status(str(file_id), "failed", f"Gemini upload error: {str(e)}")
                    return {"success": False, "error": f"Gemini upload error: {str(e)}"}
            else:
                logger.error(f"❌ [CELERY] No processed content for: {original_filename}")
                await self.update_file_status(str(file_id), "failed", "No processed content available")
                return {"success": False, "error": "No processed content available"}
                
        except Exception as e:
            logger.error(f"❌ [CELERY] Unexpected processing error: {e}")
            await self.update_file_status(str(file_id), "failed", f"Processing error: {str(e)}")
            return {"success": False, "error": f"Processing error: {str(e)}"}
