"""
FileSearch Store Manager
Centralized utility for creating and managing Gemini FileSearch stores
"""
import os
from typing import Optional
from google.genai import Client

class FileSearchStoreManager:
    """Manages Gemini FileSearch store creation and retrieval"""

    _cached_store_name: Optional[str] = None

    @classmethod
    def get_or_create_store(cls, client: Client, store_name: str = None) -> str:
        """
        Get existing FileSearch store or create a new one.

        Args:
            client: Gemini Client instance
            store_name: Optional store name (defaults to env var)

        Returns:
            Full store name in format: fileSearchStores/{store-id}
        """
        # Use cached store name if available
        if cls._cached_store_name:
            return cls._cached_store_name

        # Get store name from parameter or environment
        if not store_name:
            store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        try:
            # Try to list existing stores
            if hasattr(client, 'file_search_stores'):
                stores = list(client.file_search_stores.list())

                # Look for existing store by display name
                for store in stores:
                    if hasattr(store, 'display_name') and store.display_name == store_name:
                        cls._cached_store_name = store.name
                        print(f"✅ Found existing FileSearch store: {store.name}")
                        return store.name

                # Store not found, create it
                print(f"🔨 Creating new FileSearch store: {store_name}")
                # Create new store using correct Python client API
                new_store = client.file_search_stores.create(
                    display_name=store_name
                )
                print(f"✅ FileSearch store created: {new_store.name}")
                print(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")
                cls._cached_store_name = new_store.name
                return new_store.name
            else:
                # Client doesn't support file_search_stores API
                print(f"⚠️ Client doesn't support file_search_stores API, using store name directly")
                store_full_name = f"fileSearchStores/{store_name}"
                cls._cached_store_name = store_full_name
                return store_full_name

        except Exception as e:
            print(f"❌ Error managing FileSearch store: {e}")
            # Fallback to constructed name
            store_full_name = f"fileSearchStores/{store_name}"
            cls._cached_store_name = store_full_name
            return store_full_name

    @classmethod
    def clear_cache(cls):
        """Clear the cached store name"""
        cls._cached_store_name = None
