"""
Shared FileSearch store utilities for all services.
Provides dynamic lookup of FileSearch stores by display_name.
"""
from typing import Optional
import logging
from google.genai import Client

logger = logging.getLogger(__name__)

# Cache for resolved store IDs (display_name -> store_id)
_store_cache: dict = {}


def get_file_search_store_by_display_name(
    client: Client,
    display_name: str = "knowledgebot-search-store"
) -> Optional[str]:
    """
    Look up a FileSearch store by display_name and return its full store ID.

    Uses caching to avoid repeated API calls.

    Args:
        client: Google Generative AI Client instance
        display_name: Display name of the store to find (default: "knowledgebot-search-store")

    Returns:
        Full store ID (e.g., "fileSearchStores/xyz123") if found, None otherwise
    """
    # Check cache first
    if display_name in _store_cache:
        logger.info(f"📦 FileSearch store found in cache: {display_name} -> {_store_cache[display_name]}")
        return _store_cache[display_name]

    try:
        logger.info(f"🔍 Looking up FileSearch store by display_name: {display_name}")

        # List all FileSearch stores
        stores = list(client.file_search_stores.list())
        logger.info(f"📋 Found {len(stores)} FileSearch store(s) to search")

        # Search for store with matching display_name
        for idx, store in enumerate(stores):
            store_display_name = getattr(store, 'display_name', None)
            logger.info(f"   [{idx+1}] {store.name} | display_name: {store_display_name}")

            if store_display_name == display_name:
                logger.info(f"✅ Found FileSearch store: {store.name} (display_name: {display_name})")
                _store_cache[display_name] = store.name
                return store.name

        # Store not found
        logger.warning(f"⚠️ FileSearch store not found with display_name: {display_name}")
        if stores:
            available = [getattr(s, 'display_name', 'N/A') for s in stores]
            logger.warning(f"   Available store display_names: {available}")
        else:
            logger.warning(f"   No FileSearch stores available at all!")
        return None

    except Exception as e:
        logger.error(f"❌ Error looking up FileSearch store: {e}", exc_info=True)
        return None


def clear_store_cache():
    """Clear the FileSearch store cache."""
    global _store_cache
    logger.debug("🧹 Clearing FileSearch store cache")
    _store_cache.clear()


def get_cached_store_id(display_name: str = "knowledgebot-search-store") -> Optional[str]:
    """Get a cached FileSearch store ID without making an API call."""
    return _store_cache.get(display_name)
