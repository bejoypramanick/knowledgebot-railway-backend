import json
from typing import Any, Dict, Optional

from shared.db import get_db_connection
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def find_existing_scraping(self, url: str) -> Optional[Dict[str, Any]]:
        """Find existing scraping record by URL."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
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
        async with get_db_connection() as conn:
            await conn.execute(
                "DELETE FROM scraped_websites WHERE id = $1",
                record_id
            )

    async def insert_scraped_metadata(self, metadata: Dict[str, Any]):
        """Persist scraped website metadata."""
        async with get_db_connection() as conn:
            await conn.execute(
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
