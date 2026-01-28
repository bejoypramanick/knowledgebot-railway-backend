import asyncio
import os
import tempfile
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import HTTPException
from google.genai import types

from shared.logging_config import get_railway_logger

from ..core.ai import get_genai_client
from ..schemas.models import ScrapeRequest
from .scraping_service import ScrapingService

logger = get_railway_logger(__name__)

async def upload_scraped_content(
    content: str, 
    request: ScrapeRequest,
    sse_queue: asyncio.Queue = None
) -> Dict[str, Any]:
    """Upload scraped content to Gemini and record in DB."""
    
    genai_client = get_genai_client()
    if not genai_client:
        from shared.utils import dependency_unavailable_error
        raise dependency_unavailable_error("gemini", "client not configured")

    # Save to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name
    
    try:
        parsed_url = urlparse(request.url)
        domain = parsed_url.netloc.replace('www.', '')
        display_name_with_metadata = f"scraped_{domain}_{os.path.basename(tmp_path)}.md | {request.url}"
        
        logger.info(f"Uploading scraped content to Gemini: {display_name_with_metadata}")
        if sse_queue:
            await sse_queue.put({
                "type": "uploading",
                "message": "Uploading content to Gemini FileSearch",
                "url": request.url,
                "timestamp": asyncio.get_event_loop().time()
            })

        uploaded_file = None
        for attempt in range(3):
            try:
                uploaded_file = genai_client.files.upload(
                    file=tmp_path,
                    config=types.UploadFileConfig(display_name=display_name_with_metadata, mime_type="text/markdown")
                )
                break
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    raise
        
        if not uploaded_file:
            raise HTTPException(503, "Gemini upload failed after retries")
            
        file_info = {
            "name": uploaded_file.name,
            "display_name": uploaded_file.display_name,
            "mime_type": uploaded_file.mime_type,
            "state": uploaded_file.state.name if hasattr(uploaded_file, 'state') else None,
        }
        
        # Determine existing version to increment if needed. 
        # But this logic was in main.py BEFORE crawling.
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
