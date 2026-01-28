import json
from typing import Any, Dict, Optional

from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ScrapingDAO:
    def __init__(self, database):
        self.db = database

    async def find_existing_scraping(self, url: str) -> Optional[Dict[str, Any]]:
        """Find existing scraping record by URL."""
        if not self.db:
            return None
            
        return await self.db.fetchrow(
            """
            SELECT id, version, gemini_file_name
            FROM scraped_websites
            WHERE original_url = $1
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            url
        )

    async def delete_scraping_record(self, record_id: str):
        """Delete a scraping record."""
        if not self.db:
            return
            
        await self.db.execute(
            "DELETE FROM scraped_websites WHERE id = $1",
            record_id
        )

    async def insert_scraped_metadata(self, metadata: Dict[str, Any]):
        """Persist scraped website metadata."""
        if not self.db:
            return
            
        await self.db.execute(
            """
            INSERT INTO scraped_websites (
                user_id, original_url, domain, title,
                content_length, pages_scraped,
                gemini_file_name, gemini_file_uri, mime_type, size_bytes,
                gemini_state, scraping_config, metadata, version
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            """,
            metadata.get('user_id'),
            metadata['original_url'],
            metadata['domain'],
            metadata.get('title'),
            metadata['content_length'],
            metadata['pages_scraped'],
            metadata['gemini_file_name'],
            metadata['gemini_file_uri'],
            metadata['mime_type'],
            metadata['size_bytes'],
            metadata['gemini_state'],
            json.dumps(metadata['scraping_config']),
            json.dumps(metadata['metadata']),
            metadata['version']
        )
