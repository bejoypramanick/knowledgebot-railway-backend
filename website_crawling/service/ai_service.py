"""
AI Service for Website Crawling
Handles uploading scraped content to Gemini FileSearch
"""
import asyncio
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from google.genai import types

from website_crawling.core.otel_logger import get_otel_logger
from website_crawling.core.ai import get_genai_client
from website_crawling.service.website_service import WebsiteService

logger = get_otel_logger("ai_service", "website-crawling")


async def upload_content_to_gemini(
    content: str,
    url: str,
    title: str,
    user_email: str = None
) -> Dict[str, Any]:
    """
    Upload scraped content to Gemini FileSearch.

    Args:
        content: The scraped text content
        url: Original URL that was scraped
        title: Page title
        user_email: User email for metadata

    Returns:
        Dict with upload result including file name and state
    """
    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("Gemini client not available - returning placeholder response")
        return {
            "success": False,
            "error": "Gemini client not configured",
            "file_name": None,
            "state": "FAILED"
        }

    tmp_path = None
    try:
        # Create a temporary file with the content
        domain = urlparse(url).netloc.replace('www.', '')
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:50]
        filename = f"{domain}_{safe_title}.txt".replace(' ', '_')

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(f"# {title}\n")
            f.write(f"URL: {url}\n")
            f.write(f"Scraped: {datetime.utcnow().isoformat()}\n")
            f.write("---\n\n")
            f.write(content)
            tmp_path = f.name

        display_name = f"{title} | {url}"

        logger.info(f"🤖 [GEMINI] Uploading scraped content - Display: {display_name}")

        # Upload to Gemini
        uploaded_file = genai_client.files.upload(
            file=tmp_path,
            config=types.UploadFileConfig(
                display_name=display_name,
                mime_type="text/plain"
            )
        )

        # Poll for processing completion
        final_state = uploaded_file.state.name if hasattr(uploaded_file.state, 'name') else str(uploaded_file.state)
        gemini_processed_at = None

        for i in range(15):  # Poll for up to 30 seconds
            current_file = genai_client.files.get(name=uploaded_file.name)
            final_state = current_file.state.name if hasattr(current_file.state, 'name') else str(current_file.state)
            logger.info(f"🔄 [GEMINI] Polling state (Attempt {i+1}/15): {final_state}")

            if final_state == "ACTIVE":
                gemini_processed_at = datetime.utcnow()
                logger.info("⚡ [GEMINI] Processing complete - File is now ACTIVE")
                break
            elif final_state == "FAILED":
                logger.error(f"❌ [GEMINI] Processing FAILED for {uploaded_file.name}")
                break

            await asyncio.sleep(2)

        return {
            "success": final_state == "ACTIVE",
            "file_name": uploaded_file.name,
            "file_uri": getattr(uploaded_file, 'uri', None),
            "state": final_state,
            "processed_at": gemini_processed_at.isoformat() if gemini_processed_at else None,
            "display_name": display_name
        }

    except Exception as e:
        logger.error(f"❌ Error uploading content to Gemini: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_name": None,
            "state": "FAILED"
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass


async def record_scraped_metadata(
    url: str,
    domain: str,
    title: str,
    content_length: int,
    pages_scraped: int,
    gemini_file_name: str,
    gemini_file_uri: str,
    gemini_state: str,
    scraped_urls: List[str],
    scraping_config: Dict[str, Any],
    version: int = 1,
    user_id: str = None
) -> Optional[str]:
    """
    Record scraped website metadata to database.

    Returns:
        Record ID if successful, None otherwise
    """
    try:
        website_service = WebsiteService()

        metadata = {
            "user_role_id": user_id,
            "url": url,
            "domain": domain,
            "title": title,
            "description": f"Scraped from {url}",
            "content_length": content_length,
            "pages_scraped": pages_scraped,
            "status": gemini_state if gemini_state else "pending",
            "gemini_file_name": gemini_file_name,
            "gemini_file_uri": gemini_file_uri
        }

        record_id = await website_service.insert_scraped_metadata(metadata)
        logger.info(f"✅ Scraped metadata recorded: {record_id}")
        return record_id

    except Exception as e:
        logger.error(f"❌ Failed to persist scraped metadata: {e}")
        return None
