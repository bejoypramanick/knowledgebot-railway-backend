"""
FileSearch Store Initializer
Automatically creates Gemini FileSearch store on service startup
"""
import os
import logging
from typing import Optional

logger = logging.getLogger("website_crawling")


async def initialize_file_search_store() -> Optional[str]:
    """
    Initialize FileSearch store on service startup.
    Creates the store if it doesn't exist.

    Returns:
        Store name if successful, None otherwise
    """
    try:
        from website_crawling.core.ai import get_genai_client

        # Get Gemini client
        client = get_genai_client()
        if not client:
            logger.warning("⚠️ Gemini client not available - skipping FileSearch store initialization")
            return None

        # Get store name from environment
        store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        # Check if file_search_stores API is available
        if not hasattr(client, 'file_search_stores'):
            logger.warning("⚠️ file_search_stores API not available - skipping initialization")
            logger.info(f"   Using store name directly: fileSearchStores/{store_name}")
            return f"fileSearchStores/{store_name}"

        logger.info(f"🔍 Checking FileSearch store: {store_name}")

        # List existing stores
        stores = list(client.file_search_stores.list())

        # Check if our store exists
        existing_store = None
        for store in stores:
            if hasattr(store, 'display_name') and store.display_name == store_name:
                existing_store = store
                break

        if existing_store:
            logger.info(f"✅ FileSearch store already exists: {existing_store.name}")
            return existing_store.name
        else:
            # Create new store
            logger.info(f"🔨 Creating FileSearch store: {store_name}")
            # The Gemini API creates stores with auto-generated names
            # display_name cannot be set during creation
            new_store = client.file_search_stores.create()
            logger.info(f"✅ FileSearch store created successfully: {new_store.name}")
            logger.info(f"   Note: Store was created with auto-generated name. Display name: {getattr(new_store, 'display_name', 'N/A')}")
            return new_store.name

    except Exception as e:
        logger.error(f"❌ Error initializing FileSearch store: {e}")
        logger.warning("⚠️ Service will continue but scraped content uploads may fail")
        return None
