"""
Consolidated Knowledgebase Ingestion Router
All knowledgebase ingestion endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Optional
import logging
import json
import asyncio

from ..service.file_service import FileService
from ..service.ingestion_service import (
    process_single_file_upload,
    process_single_file_delete,
    delete_file_logic,
    nuke_filestore_and_database,
    delete_website_hierarchy,
    upload_file_celery
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
file_service = FileService()

def extract_user_from_request(request: Request) -> tuple[str, str]:
    """Extract user information from request headers forwarded by API Gateway"""
    user_email = request.headers.get("X-User-Email", "unknown@example.com")
    user_id = request.headers.get("X-User-UID", "unknown")
    return user_email, user_id

# =================================
# FILE UPLOAD ENDPOINTS
# =================================

@router.get("/files")
async def list_files(request: Request = None):
    """List all files and websites in hierarchical structure (backward compatible)"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get unified knowledgebase (files + hierarchical websites)
        knowledgebase = await file_service.get_all_knowledgebase()
        
        # Return in format that's backward compatible but includes websites
        return {
            "success": True,
            "files": knowledgebase["files"],  # Original files list
            "websites": knowledgebase["websites"],  # Add hierarchical websites
            "summary": knowledgebase["summary"],  # Add summary info
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/knowledgebase")
async def list_knowledgebase(request: Request = None):
    """List all knowledgebase items (files + websites) with hierarchical structure for websites"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        knowledgebase = await file_service.get_all_knowledgebase()
        
        return {
            "success": True,
            "knowledgebase": knowledgebase,
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error listing knowledgebase: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/async")
async def upload_file_async_endpoint(
    file: UploadFile = File(...),
    request: Request = None,
    display_name: Optional[str] = Form(None)
):
    """
    Async file upload endpoint with Celery - returns immediately with pending status.
    Actual processing happens in Celery worker. Frontend should poll /status/{id} to track progress.
    """
    try:
        user_email, user_id = extract_user_from_request(request)

        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        result = await upload_file_celery(
            file=file,
            display_name=display_name,
            user_email=user_email
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in async file upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_processing_status(request: Request = None):
    """Get processing status for all pending/processing items (files and websites)"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Get all non-completed files
            files = await conn.fetch(
                """SELECT id, original_filename, processing_status, error_message, created_at, updated_at
                   FROM file_uploads
                   WHERE processing_status IN ('pending', 'processing')
                   ORDER BY updated_at DESC"""
            )

            # Get all non-completed websites
            websites = await conn.fetch(
                """SELECT id, original_url, processing_status, error_message, created_at, updated_at
                   FROM scraped_websites
                   WHERE processing_status IN ('pending', 'processing')
                   ORDER BY updated_at DESC"""
            )

            return {
                "success": True,
                "files": [
                    {
                        "id": str(f['id']),
                        "type": "file",
                        "name": f['original_filename'],
                        "processing_status": f['processing_status'],
                        "error_message": f['error_message'],
                        "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                        "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
                    }
                    for f in files
                ],
                "websites": [
                    {
                        "id": str(w['id']),
                        "type": "website",
                        "name": w['original_url'],
                        "processing_status": w['processing_status'],
                        "error_message": w['error_message'],
                        "created_at": w['created_at'].isoformat() if w['created_at'] else None,
                        "updated_at": w['updated_at'].isoformat() if w['updated_at'] else None
                    }
                    for w in websites
                ]
            }
    except Exception as e:
        logger.error(f"Error getting processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single file or website"""
    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Try to find in file_uploads first
            file_record = await conn.fetchrow(
                """SELECT id, original_filename, processing_status, error_message, created_at, updated_at
                   FROM file_uploads WHERE id = $1""",
                int(item_id)
            )

            if file_record:
                return {
                    "success": True,
                    "type": "file",
                    "id": str(file_record['id']),
                    "name": file_record['original_filename'],
                    "processing_status": file_record['processing_status'],
                    "error_message": file_record['error_message'],
                    "created_at": file_record['created_at'].isoformat() if file_record['created_at'] else None,
                    "updated_at": file_record['updated_at'].isoformat() if file_record['updated_at'] else None
                }

            # Try to find in scraped_websites
            website_record = await conn.fetchrow(
                """SELECT id, original_url, processing_status, error_message, created_at, updated_at
                   FROM scraped_websites WHERE id = $1""",
                int(item_id)
            )

            if website_record:
                return {
                    "success": True,
                    "type": "website",
                    "id": str(website_record['id']),
                    "name": website_record['original_url'],
                    "processing_status": website_record['processing_status'],
                    "error_message": website_record['error_message'],
                    "created_at": website_record['created_at'].isoformat() if website_record['created_at'] else None,
                    "updated_at": website_record['updated_at'].isoformat() if website_record['updated_at'] else None
                }

            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_task(item_id: str, request: Request = None):
    """
    Cancel a pending or processing file/website task.
    Sets Redis cancellation flag and marks as cancelled in database.
    """
    try:
        from shared.db import get_db_connection
        from shared.redis_message_queue import redis_message_queue

        async with get_db_connection() as conn:
            # Try file_uploads first
            file_record = await conn.fetchrow(
                "SELECT id, processing_status, celery_task_id FROM file_uploads WHERE id = $1",
                int(item_id)
            )

            if file_record:
                if file_record['processing_status'] not in ('pending', 'processing'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot cancel file with status '{file_record['processing_status']}'"
                    )

                celery_task_id = file_record['celery_task_id']

                # ATOMIC TRANSACTION: Either both succeed or both fail
                async with conn.transaction():
                    # Step 1: Set Redis cancellation flag (if it exists)
                    if celery_task_id:
                        try:
                            redis_message_queue.set_task_cancelled(celery_task_id)
                            logger.info(f"🔴 [REDIS_CANCEL] Set cancellation flag for task {celery_task_id}")
                        except Exception as e:
                            # If flag setting fails, raise exception to trigger transaction rollback
                            logger.error(f"❌ [ATOMIC_TX] Cancel flag failed for task {celery_task_id}: {e}")
                            raise HTTPException(status_code=500, detail=f"Failed to set cancellation flag: {e}")

                    # Step 2: Update database (same transaction)
                    try:
                        await conn.execute(
                            "UPDATE file_uploads SET processing_status = 'cancelled' WHERE id = $1",
                            int(item_id)
                        )
                        logger.info(f"✅ [ATOMIC_TX] Updated DB: file {item_id} marked as cancelled")
                    except Exception as e:
                        # If DB update fails, transaction rolls back
                        logger.error(f"❌ [ATOMIC_TX] DB update failed for file {item_id}: {e}")
                        raise HTTPException(status_code=500, detail=f"Failed to update cancellation status: {e}")

                # If we reach here, transaction is committed - both operations succeeded
                logger.info(f"✅ [ATOMIC_COMMIT] Cancelled file task: {item_id} (celery_task_id: {celery_task_id})")
                return {
                    "success": True,
                    "type": "file",
                    "item_id": item_id,
                    "celery_task_id": celery_task_id,
                    "message": "File processing cancelled successfully"
                }

            # Try scraped_websites
            website_record = await conn.fetchrow(
                "SELECT id, processing_status, celery_task_id FROM scraped_websites WHERE id = $1",
                int(item_id)
            )

            if website_record:
                if website_record['processing_status'] not in ('pending', 'processing'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot cancel website with status '{website_record['processing_status']}'"
                    )

                celery_task_id = website_record['celery_task_id']

                # ATOMIC TRANSACTION: Either both succeed or both fail
                async with conn.transaction():
                    # Step 1: Set Redis cancellation flag (if it exists)
                    if celery_task_id:
                        try:
                            redis_message_queue.set_task_cancelled(celery_task_id)
                            logger.info(f"🔴 [REDIS_CANCEL] Set cancellation flag for task {celery_task_id}")
                        except Exception as e:
                            # If flag setting fails, raise exception to trigger transaction rollback
                            logger.error(f"❌ [ATOMIC_TX] Cancel flag failed for task {celery_task_id}: {e}")
                            raise HTTPException(status_code=500, detail=f"Failed to set cancellation flag: {e}")

                    # Step 2: Update database (same transaction)
                    try:
                        await conn.execute(
                            "UPDATE scraped_websites SET processing_status = 'cancelled' WHERE id = $1::int",
                            int(item_id)
                        )
                        logger.info(f"✅ [ATOMIC_TX] Updated DB: website {item_id} marked as cancelled")
                    except Exception as e:
                        # If DB update fails, transaction rolls back
                        logger.error(f"❌ [ATOMIC_TX] DB update failed for website {item_id}: {e}")
                        raise HTTPException(status_code=500, detail=f"Failed to update cancellation status: {e}")

                # If we reach here, transaction is committed - both operations succeeded
                logger.info(f"✅ [ATOMIC_COMMIT] Cancelled website task: {item_id} (celery_task_id: {celery_task_id})")
                return {
                    "success": True,
                    "type": "website",
                    "item_id": item_id,
                    "celery_task_id": celery_task_id,
                    "message": "Website scraping cancelled successfully"
                }

            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_tasks(request: Request = None):
    """
    Cancel all pending and processing tasks (files and websites).
    Clears Redis queues and sets cancellation flags for all in-flight tasks.
    """
    try:
        from shared.db import get_db_connection
        from shared.redis_message_queue import redis_message_queue

        async with get_db_connection() as conn:
            # ATOMIC TRANSACTION: Either all tasks cancel or none cancel
            async with conn.transaction():
                # Step 1: Get all pending/processing tasks to set cancellation flags
                try:
                    file_tasks = await conn.fetch(
                        "SELECT celery_task_id FROM file_uploads WHERE processing_status IN ('pending', 'processing')"
                    )
                    tasks_flagged = 0
                    for task in file_tasks:
                        if task['celery_task_id']:
                            redis_message_queue.set_task_cancelled(task['celery_task_id'])
                            tasks_flagged += 1
                    logger.info(f"✅ [REDIS_CANCEL] Set cancellation flags for {tasks_flagged} file tasks")
                except Exception as e:
                    logger.warning(f"⚠️ Error setting file task cancellation flags: {e}")

                try:
                    website_tasks = await conn.fetch(
                        "SELECT celery_task_id FROM scraped_websites WHERE processing_status IN ('pending', 'processing')"
                    )
                    tasks_flagged = 0
                    for task in website_tasks:
                        if task['celery_task_id']:
                            redis_message_queue.set_task_cancelled(task['celery_task_id'])
                            tasks_flagged += 1
                    logger.info(f"✅ [REDIS_CANCEL] Set cancellation flags for {tasks_flagged} web tasks")
                except Exception as e:
                    logger.warning(f"⚠️ Error setting web task cancellation flags: {e}")

                # Step 2: Mark all pending/processing tasks as cancelled in database
                try:
                    files_result = await conn.execute(
                        """UPDATE file_uploads
                           SET processing_status = 'cancelled'
                           WHERE processing_status IN ('pending', 'processing')"""
                    )
                    files_cancelled = int(files_result.split()[-1]) if files_result else 0
                    logger.info(f"✅ [ATOMIC_TX] Updated DB: {files_cancelled} files marked as cancelled")
                except Exception as e:
                    logger.error(f"❌ [ATOMIC_TX] Failed to update file statuses: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to update file statuses: {e}")

                try:
                    websites_result = await conn.execute(
                        """UPDATE scraped_websites
                           SET processing_status = 'cancelled'
                           WHERE processing_status IN ('pending', 'processing')"""
                    )
                    websites_cancelled = int(websites_result.split()[-1]) if websites_result else 0
                    logger.info(f"✅ [ATOMIC_TX] Updated DB: {websites_cancelled} websites marked as cancelled")
                except Exception as e:
                    logger.error(f"❌ [ATOMIC_TX] Failed to update website statuses: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to update website statuses: {e}")

                # Step 3: Purge all pending queues to clear queued tasks
                try:
                    redis_message_queue.clear_file_task_queue()
                    logger.critical("✅ [2/2a] File task queue purged")
                except Exception as e:
                    logger.warning(f"⚠️ Error purging file task queue: {e}")

                try:
                    redis_message_queue.clear_web_task_queue()
                    logger.critical("✅ [2/2b] Web task queue purged")
                except Exception as e:
                    logger.warning(f"⚠️ Error purging web task queue: {e}")

                logger.critical("✅✅✅ ALL TASKS MARKED FOR CANCELLATION ✅✅✅")

                # If we reach here, transaction is committed - all operations succeeded
                return {
                    "success": True,
                    "message": "All pending tasks cancelled successfully",
                    "files_cancelled": files_cancelled,
                    "websites_cancelled": websites_cancelled
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling all tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# REAL-TIME UPDATES (SSE)
# =================================

@router.get("/stream")
async def stream_status_updates(request: Request):
    """
    Server-Sent Events stream for real-time status updates.
    Frontend can listen to this stream to get live updates as tasks progress.

    Usage:
    const eventSource = new EventSource('/api/v1/knowledgebase/stream');
    eventSource.onmessage = (event) => {
      const update = JSON.parse(event.data);
      // Update UI with new status
    };
    """
    async def generate():
        """Generate SSE stream with status updates"""
        from shared.db import get_db_connection

        # Track last sent status to avoid duplicates
        last_status = {}

        try:
            while True:
                try:
                    async with get_db_connection() as conn:
                        # Get all non-completed files
                        files = await conn.fetch(
                            """SELECT id, original_filename, processing_status, error_message, updated_at
                               FROM file_uploads
                               WHERE processing_status IN ('pending', 'processing', 'cancelled')
                               ORDER BY updated_at DESC"""
                        )

                        # Get all non-completed websites
                        websites = await conn.fetch(
                            """SELECT id, original_url, processing_status, error_message, updated_at
                               FROM scraped_websites
                               WHERE processing_status IN ('pending', 'processing', 'cancelled')
                               ORDER BY updated_at DESC"""
                        )

                        current_status = {
                            "files": [
                                {
                                    "id": str(f['id']),
                                    "type": "file",
                                    "name": f['original_filename'],
                                    "status": f['processing_status'],
                                    "error": f['error_message'],
                                    "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
                                }
                                for f in files
                            ],
                            "websites": [
                                {
                                    "id": str(w['id']),
                                    "type": "website",
                                    "name": w['original_url'],
                                    "status": w['processing_status'],
                                    "error": w['error_message'],
                                    "updated_at": w['updated_at'].isoformat() if w['updated_at'] else None
                                }
                                for w in websites
                            ],
                            "timestamp": asyncio.get_event_loop().time()
                        }

                        # Only send if status changed
                        if current_status != last_status:
                            last_status = current_status
                            yield f"data: {json.dumps(current_status)}\n\n"

                except Exception as e:
                    logger.error(f"Error in stream: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Update every 2 seconds
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            logger.info("Stream cancelled by client")
            return
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.get("/upload/constraints")
async def get_upload_constraints(request: Request = None):
    """Get upload constraints"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Import constants for consistency
        from ..utils.constants import MAX_FILE_SIZE_BYTES, ALLOWED_FILE_EXTENSIONS

        return {
            "success": True,
            # Top-level fields for frontend compatibility
            "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
            "allowed_extensions": ALLOWED_FILE_EXTENSIONS,
            "max_file_size_display": f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB",
            # Nested constraints for backwards compatibility
            "constraints": {
                "max_file_size": MAX_FILE_SIZE_BYTES,
                "allowed_extensions": ALLOWED_FILE_EXTENSIONS,
                "allowed_types": [
                    "application/pdf",
                    "text/plain",
                    "text/markdown",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ],
                "max_files_per_user": 100
            },
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error getting upload constraints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request = None):
    """
    Delete an uploaded file with transactional safety.

    This endpoint is for uploaded files only (not websites/sitemaps).
    Use /web/{id} endpoint for websites and sitemaps.

    Transaction Safety:
    - FileStore deletion attempted first
    - Database deletion happens in a transaction
    - If FileStore fails, database is not touched
    - If database transaction fails, it rolls back automatically
    """
    try:
        if not file_id:
            raise HTTPException(status_code=400, detail="file_id is required")

        # Use the service layer for file deletion
        logger.info(f"📄 Deleting uploaded file: {file_id}")
        result = await delete_file_logic(file_id)

        return {
            "success": result.get("success", True),
            "message": result.get("message", "File deleted successfully"),
            "details": result.get("details"),
            "transaction_status": result.get("transaction_status", "unknown")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/web/{website_id}")
async def delete_web_item(website_id: str, request: Request = None):
    """
    Delete a website or sitemap and all its child pages with cascade delete.

    This endpoint is for websites and sitemaps (not uploaded files).
    Automatically deletes all child pages when parent is deleted.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        logger.info(f"🌐 User {user_email} requesting deletion of website/sitemap {website_id}")

        # Use hierarchy deletion with cascade delete
        result = await delete_website_hierarchy(website_id)

        return {
            "success": result.get("success", True),
            "message": result.get("message", "Website/sitemap deleted successfully"),
            "details": result.get("details"),
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website/sitemap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/websites/{website_id}/hierarchy")
async def delete_website_hierarchy_deprecated(website_id: str, request: Request = None):
    """
    Delete a website and all its child pages with transactional safety.
    
    Transaction Safety:
    - FileSearch deletion attempted first for all pages
    - Database deletion happens only if FileSearch mostly succeeds
    - Uses recursive hierarchy to find all child pages
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        logger.info(f"🌳 User {user_email} requesting hierarchical deletion of website {website_id}")
        
        # Use local ingestion service function for hierarchical deletion
        result = await delete_website_hierarchy(website_id)
        
        return {
            "success": result.get("success", True),
            "message": result.get("message", "Website hierarchy deleted successfully"),
            "details": result.get("details"),
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website hierarchy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# WEBSITE SCRAPING ENDPOINTS
# =================================

@router.post("/webcrawl/async")
async def scrape_website_async_endpoint(request: Request = None):
    """
    Async website scraping endpoint with Celery - returns immediately with pending status.
    Actual processing happens in Celery worker. Frontend should poll /status/{id} to track progress.

    Mirrors the old website_crawling endpoint exactly so frontend doesn't break.
    """
    try:
        body = await request.json() if request else {}

        # Support both single URL and multiple URLs
        url_input = body.get("url") or body.get("urls") or ""
        if not url_input:
            raise HTTPException(status_code=400, detail="URL or URLs parameter is required")

        # Parse URLs - handle both single URL and comma-separated list
        if isinstance(url_input, list):
            urls = url_input
        else:
            urls = [u.strip() for u in str(url_input).split(",") if u.strip()]

        if not urls:
            raise HTTPException(status_code=400, detail="At least one valid URL is required")

        # Validate URLs
        for url in urls:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail=f"Invalid URL format: {url}")

        # Get crawling parameters from frontend
        max_depth = body.get("max_depth", 2)
        replace_existing = body.get("replace_existing", False)
        include_patterns = body.get("include_patterns", []) or []
        exclude_patterns = body.get("exclude_patterns", []) or []

        logger.info(f"🎯 Starting async batch scrape for {len(urls)} URL(s)")
        all_results = []
        from shared.db import get_db_connection
        from shared.service_client import service_client

        # Process each URL
        for idx, url in enumerate(urls, 1):
            try:
                # Classify URL type
                if url.endswith("sitemap.xml"):
                    url_type = "sitemap"
                    crawl_depth = 1
                elif url.count("/") <= 3:  # Simple heuristic: single page if few slashes
                    url_type = "single_page"
                    crawl_depth = max(0, max_depth)
                else:
                    url_type = "website"
                    crawl_depth = max_depth

                logger.info(f"[{idx}/{len(urls)}] Queueing {url_type}: {url}")

                # Use generous internal page cap
                max_pages = 1000

                # Scrape options
                options = {
                    "url": url,
                    "max_pages": max_pages,
                    "max_depth": min(crawl_depth, 5),
                    "replace_existing": replace_existing,
                    "max_concurrent": min(int(body.get("max_concurrent", 10)), 50),
                    "extract_links": body.get("extract_links", True),
                    "extract_images": body.get("extract_images", False),
                    "respect_robots_txt": body.get("respect_robots_txt", True),
                    "user_agent": body.get("user_agent", "KnowledgeBot-Crawler/1.0"),
                    "timeout": body.get("timeout", 30),
                    "include_patterns": include_patterns,
                    "exclude_patterns": exclude_patterns
                }

                # Check for duplicate URL in database
                async with get_db_connection() as conn:
                    existing = await conn.fetchrow(
                        "SELECT id, processing_status FROM scraped_websites WHERE original_url = $1",
                        url
                    )

                    if existing:
                        logger.warning(f"⚠️ URL already exists: {url} (ID: {existing['id']}, Status: {existing['processing_status']})")
                        all_results.append({
                            "url": url,
                            "type": url_type,
                            "success": False,
                            "duplicate": True,
                            "where_exists": ["scraped_websites"],
                            "existing_id": existing['id'],
                            "existing_status": existing['processing_status'],
                            "error": f"URL already exists with status '{existing['processing_status']}'"
                        })
                        continue

                    # Create website record with status='pending'
                    website_record = await conn.fetchval(
                        """INSERT INTO scraped_websites
                           (original_url, processing_status, created_at, updated_at)
                           VALUES ($1, 'pending', NOW(), NOW())
                           RETURNING id""",
                        url
                    )

                    website_id = website_record if website_record else None

                    if not website_id:
                        logger.error(f"Failed to create website record for {url}")
                        all_results.append({
                            "url": url,
                            "type": url_type,
                            "success": False,
                            "error": "Failed to create website record in database"
                        })
                        continue

                    logger.info(f"✅ Created website record ID {website_id} for {url}")

                    # Queue task via Redis message queue
                    try:
                        import uuid
                        from shared.redis_message_queue import redis_message_queue

                        # Generate task ID locally
                        task_id = str(uuid.uuid4())

                        # Publish to Redis message queue
                        success = redis_message_queue.publish_web_task(
                            website_id=website_id,
                            url=url,
                            max_depth=options.get('max_depth', 2),
                            max_pages=options.get('max_pages', 100),
                            max_concurrent=options.get('max_concurrent', 10),
                            delay_between_requests=options.get('delay_between_requests', 0.0),
                            user_email=options.get('user_email', 'admin'),
                            celery_task_id=task_id,
                            **{k: v for k, v in options.items() if k not in ['max_depth', 'max_pages', 'max_concurrent', 'delay_between_requests', 'user_email']}
                        )

                        if success:
                            logger.info(f"✅ Queued website task to Redis: {task_id}")

                            # Update database with task ID
                            await conn.execute(
                                "UPDATE scraped_websites SET celery_task_id = $1 WHERE id = $2",
                                task_id,
                                website_id
                            )

                            all_results.append({
                                "url": url,
                                "type": url_type,
                                "success": True,
                                "duplicate": False,
                                "website_id": website_id,
                                "task_id": task_id
                            })
                        else:
                            error_msg = "Failed to queue task to Redis"
                            logger.error(f"Failed to queue task for {url}: {error_msg}")
                            all_results.append({
                                "url": url,
                                "type": url_type,
                                "success": False,
                                "error": error_msg
                            })
                    except Exception as e:
                        logger.error(f"Error queueing task for {url}: {e}")
                        all_results.append({
                            "url": url,
                            "type": url_type,
                            "success": False,
                            "error": str(e)
                        })

            except Exception as e:
                logger.error(f"❌ Error queueing {url}: {e}")
                all_results.append({
                    "url": url,
                    "type": "unknown",
                    "success": False,
                    "error": str(e)
                })

        queued = [r for r in all_results if r.get("success")]
        failed = [r for r in all_results if not r.get("success")]
        logger.info(f"✅ Async batch scrape queued: {len(queued)}/{len(urls)} accepted, {len(failed)} failed")

        return {
            "success": len(queued) > 0 or len(failed) == 0,
            "data": all_results,
            "queued_count": len(queued),
            "failed_count": len(failed),
            "message": f"Queued {len(queued)} URL(s) for scraping" + (f", {len(failed)} failed" if failed else "")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in async scrape endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete-all")
async def delete_all_files(request: Request = None):
    """
    Delete all files and websites: Remove all documents from FileSearch store and all database records.
    This is a destructive operation and should only be called with explicit admin confirmation.
    
    Transaction Safety:
    - If FileStore deletion fails, database is NOT touched
    - Database deletion happens in a transaction - rolls back if it fails
    - Returns detailed status of what succeeded/failed
    """
    try:
        # Log the delete all for audit purposes
        user_email = request.headers.get("X-User-Email", "unknown") if request else "unknown"
        logger.critical(f"🚨 DELETE ALL INITIATED by {user_email}")

        # Execute the deletion with transactional safety
        result = await nuke_filestore_and_database()

        transaction_status = result.get("transaction_status", "unknown")
        success = result.get("success", False)

        if success:
            logger.critical(f"🚨 DELETE ALL SUCCESSFUL - All data removed (transaction: {transaction_status})")
            # Return 200 with success details
            return {
                "success": True,
                "message": result.get("message"),
                "details": result.get("details"),
                "transaction_status": transaction_status
            }
        else:
            # Transaction failed or was aborted - return error
            logger.critical(f"🚨 DELETE ALL FAILED - Transaction status: {transaction_status}")
            logger.critical(f"   Message: {result.get('message')}")

            # Return 500 error with detailed message
            raise HTTPException(
                status_code=500,
                detail=f"{result.get('message')} (Transaction: {transaction_status})"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during delete all operation: {e}")
        raise HTTPException(status_code=500, detail=f"Delete all operation failed with error: {str(e)}")

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "service": "knowledgebase_ingestion",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "file_service": "healthy",
                "storage": "connected",
                "database": "connected"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
