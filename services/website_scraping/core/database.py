import logging
from typing import Optional, Dict, Any
from shared import db as shared_db
from services.website_scraping.core.ai import get_genai_client
from services.website_scraping.dao.scraping_dao import ScrapingDAO

logger = logging.getLogger(__name__)

async def get_existing_website(url: str, domain: str) -> Optional[Dict[str, Any]]:
    if not shared_db.railway_db:
        return None
    try:
        dao = ScrapingDAO(shared_db.railway_db)
        return await dao.find_existing_scraping(url)
    except Exception as e:
        logger.error(f"Error checking existing website: {e}")
        return None

async def delete_website_record(record_id: str):
    if shared_db.railway_db:
        dao = ScrapingDAO(shared_db.railway_db)
        await dao.delete_scraping_record(record_id)

async def delete_gemini_file(file_name: str):
    genai_client = get_genai_client()
    if genai_client and file_name:
        try:
            genai_client.files.delete(name=file_name)
        except Exception:
             pass
