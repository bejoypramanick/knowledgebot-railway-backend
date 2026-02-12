"""
Shared FileSearch store utilities for all services.
Simple lookup of FileSearch stores by display_name.
"""
from typing import Optional
import logging
from google.genai import Client

logger = logging.getLogger(__name__)


def get_file_search_store_by_display_name(
    client: Client,
    display_name: str
) -> Optional[str]:
    """
    Look up a FileSearch store by display_name and return its full store ID.

    Args:
        client: Google Generative AI Client instance
        display_name: Display name of the store to find

    Returns:
        Full store ID (e.g., "fileSearchStores/xyz123") if found, None otherwise
    """
    try:
        logger.info(f"🔍 Looking up FileSearch store by display_name: '{display_name}'")

        # Check if client has file_search_stores API
        if not hasattr(client, 'file_search_stores'):
            logger.error(f"❌ Client does not have 'file_search_stores' API!")
            return None

        # List all FileSearch stores
        logger.info("📋 Listing FileSearch stores...")
        stores = list(client.file_search_stores.list())
        logger.info(f"📋 Found {len(stores)} FileSearch store(s)")

        if not stores:
            logger.warning(f"⚠️ No FileSearch stores found")
            return None

        # Search for store with matching display_name
        for idx, store in enumerate(stores):
            store_display_name = getattr(store, 'display_name', None)
            store_id = getattr(store, 'name', 'N/A')
            logger.info(f"   [{idx+1}] {store_id} - display_name: '{store_display_name}'")

            if store_display_name == display_name:
                logger.info(f"✅ Found store: {store_id}")
                return store_id

        # Store not found
        logger.error(f"❌ FileSearch store NOT FOUND with display_name: '{display_name}'")
        return None

    except Exception as e:
        logger.error(f"❌ Error looking up FileSearch store: {e}")
        return None
