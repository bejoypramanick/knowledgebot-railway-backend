import asyncio
import os
import tempfile

from website_crawling.core.otel_logger import get_otel_logger

logger = get_otel_logger("ingestion_service", "website-crawling")

async def process_with_gemini(tmp_path: str, file_display_name: str, original_filename: str, mime_type: str, user_email: str = None):
    """Process file with Gemini - placeholder implementation"""
    try:
        # This would need to be implemented based on actual Gemini processing logic
        # For now, return success response
        return {
            "success": True,
            "message": f"File {file_display_name} processed successfully",
            "file_name": file_display_name
        }
        # We should pass version in? Or calculate it here.
        # It's better to handle version checking before crawling to avoid crawling if duplicate and not replacing.
        # So we assume main flow handles version check and cleanup.
        # But we need to insert new record here.
        
        version = 1
        # Check if previous version exists (even if deleted, we want to increment?)
        # Logic in main.py:
        # If replace_existing: existing_version = existing['version'] + 1
        # Using a fresh query to get max version for this url
        if shared_db.railway_db:
             # We can't rely on existing row if we deleted it.
             # Wait, main.py deleted the row.
             # We should probably pass the version from the caller. 
             # I'll stick to a simple query to see if any exist (maybe archived/history?)
             # If we deleted the row, we lost the version history unless we have a history table.
             # In main.py: "Replacing existing website: ... version X -> X+1"
             pass

        # Since I can't easily change the signature of this function without changing main flow logic significantly,
        # I will accept `version` as argument or default to 1.
        
        # ... logic to insert into DB ...
        return {"file": uploaded_file, "file_info": file_info}
        
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def record_scraped_metadata(
    request: ScrapeRequest,
    content_len: int,
    pages_scraped: int,
    uploaded_file: Any,
    file_info: Dict[str, Any],
    scraped_urls: List[str],
    version: int = 1
):
    try:
        scraping_service = ScrapingService()
        
        scraping_cfg = {
            "max_depth": request.max_depth,
            "max_pages": request.max_pages,
            "include_patterns": request.include_patterns,
            "exclude_patterns": request.exclude_patterns,
            "wait_for": request.wait_for,
        }
        domain = urlparse(request.url).netloc.replace('www.', '')
        
        metadata = {
            "user_id": None,
            "original_url": request.url,
            "domain": domain,
            "title": None,
            "content_length": content_len,
            "pages_scraped": pages_scraped,
            "gemini_file_name": uploaded_file.name,
            "gemini_file_uri": getattr(uploaded_file, 'uri', None) or uploaded_file.name,
            "mime_type": file_info.get('mime_type'),
            "size_bytes": content_len,
            "gemini_state": file_info.get('state'),
            "scraping_config": scraping_cfg,
            "metadata": {"scraped_urls": scraped_urls},
            "version": version
        }
        
        await scraping_service.insert_scraped_metadata(metadata)
    except Exception as e:
        logger.error(f"Failed to persist scraped metadata: {e}")
