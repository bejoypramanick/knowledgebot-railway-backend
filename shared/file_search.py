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
        Full store ID (e.g., "fileSearchStores/xyz123") if found, None if store
        genuinely does not exist.

    Raises:
        Exception: If the Gemini API call fails (network error, timeout, permission
        error, etc.). Callers must distinguish API errors from "not found" — if this
        raises, the store existence is UNKNOWN and callers should NOT assume it is
        absent or proceed with dependent operations.
    """
    logger.info(f"🔍 Looking up FileSearch store by display_name: '{display_name}'")
    logger.info(f"🔍 Client type: {type(client)}")
    logger.info(f"🔍 Client has file_search_stores: {hasattr(client, 'file_search_stores')}")

    # Check if client has file_search_stores API
    if not hasattr(client, 'file_search_stores'):
        raise RuntimeError("Gemini client does not have 'file_search_stores' API")

    # List all FileSearch stores — let exceptions propagate so callers know the
    # lookup itself failed (rather than silently treating it as "not found").
    logger.info("📋 Listing FileSearch stores...")
    
    # Handle pagination properly - the list() method returns a pager that needs iteration
    stores = []
    try:
        pager = client.file_search_stores.list()
        for store in pager:
            stores.append(store)
    except Exception as e:
        logger.error(f"❌ Error listing FileSearch stores: {e}")
        raise
    
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

    # Store genuinely not found in the list
    logger.warning(f"⚠️ FileSearch store NOT FOUND with display_name: '{display_name}'")
    return None
