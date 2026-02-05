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
        logger.info(f"🔍 Looking up FileSearch store by display_name: '{display_name}'")
        logger.info(f"   Client type: {type(client)}")

        # Check if client has file_search_stores API
        if not hasattr(client, 'file_search_stores'):
            logger.error(f"❌ Client does not have 'file_search_stores' API!")
            logger.error(f"   Available attributes: {[attr for attr in dir(client) if not attr.startswith('_')]}")
            return None

        # List all FileSearch stores
        logger.info("📋 Attempting to list FileSearch stores...")
        stores = list(client.file_search_stores.list())
        logger.info(f"📋 Found {len(stores)} FileSearch store(s) to search")

        if not stores:
            logger.warning(f"⚠️ No FileSearch stores found at all!")
            return None

        # Search for store with matching display_name
        for idx, store in enumerate(stores):
            store_display_name = getattr(store, 'display_name', None)
            store_name = getattr(store, 'name', 'N/A')
            logger.info(f"   [{idx+1}] store.name={store_name}")
            logger.info(f"       store.display_name='{store_display_name}'")
            logger.info(f"       Match? {store_display_name == display_name}")

            if store_display_name == display_name:
                logger.info(f"✅ FOUND! FileSearch store: {store_name} (display_name: {display_name})")
                _store_cache[display_name] = store_name
                return store_name

        # Store not found
        logger.error(f"❌ FileSearch store NOT FOUND with display_name: '{display_name}'")
        available = [f"'{getattr(s, 'display_name', 'N/A')}'" for s in stores]
        logger.error(f"   Available display_names: {available}")
        return None

    except Exception as e:
        logger.error(f"❌ EXCEPTION during FileSearch store lookup: {e}", exc_info=True)
        logger.error(f"   Exception type: {type(e).__name__}")
        return None


def clear_store_cache():
    """Clear the FileSearch store cache."""
    global _store_cache
    logger.debug("🧹 Clearing FileSearch store cache")
    _store_cache.clear()


def get_cached_store_id(display_name: str = "knowledgebot-search-store") -> Optional[str]:
    """Get a cached FileSearch store ID without making an API call."""
    return _store_cache.get(display_name)
