"""
FileSearch Store Manager
Centralized utility for creating and managing Gemini FileSearch stores
"""
import os
from typing import Optional, Dict, Any
from google.genai import Client
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_search_store_manager", "knowledgebase-ingestion")

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
                        logger.info(f"✅ Found existing FileSearch store: {store.name}")
                        return store.name

                # Store not found, create it
                logger.info(f"🔨 Creating new FileSearch store: {store_name}")
                store = client.file_search_stores.create(
                    config={'display_name': store_name}
                )
                store_full_name = store.name
                cls._cached_store_name = store_full_name
                logger.info(f"✅ Created new FileSearch store: {store_full_name}")
                return store_full_name

        except Exception as e:
            logger.error(f"❌ Error managing FileSearch store: {e}")
            # Fallback to constructed name
            store_full_name = f"fileSearchStores/{store_name}"
            cls._cached_store_name = store_full_name
            return store_full_name

    @classmethod
    def delete_all_stores_with_display_name(cls, client: Client, base_display_name: str = None) -> Dict[str, Any]:
        """
        Delete ALL FileSearch stores that match the base display name pattern.
        This handles multiple stores created during development/testing.
        
        Args:
            client: Gemini Client instance
            base_display_name: Base display name (defaults to env var)
            
        Returns:
            Dict with deletion results
        """
        logger.info("=" * 80)
        logger.info(f"🗑️ [DELETE_ALL_STORES] Deleting all stores matching '{base_display_name}'")
        logger.info("=" * 80)
        
        # Get store name from parameter or environment
        if not base_display_name:
            base_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")
        
        deleted_stores = []
        errors = []
        
        try:
            # List all stores
            if hasattr(client, 'file_search_stores'):
                stores = list(client.file_search_stores.list())
                logger.info(f"📋 [STORE_LIST] Found {len(stores)} total FileSearch stores")
                
                # Find all stores that match our base display name pattern
                matching_stores = []
                for idx, store in enumerate(stores, 1):
                    store_display_name = getattr(store, 'display_name', 'N/A')
                    logger.info(f"   Store {idx}: {store.name} (display_name: {store_display_name})")
                    
                    # Check if this store matches our pattern
                    if (store_display_name == base_display_name or 
                        store_display_name.startswith(base_display_name) or
                        base_display_name in store_display_name):
                        matching_stores.append(store)
                        logger.info(f"   ✅ Match: {store.name} matches pattern '{base_display_name}'")
                
                logger.info(f"🎯 [STORE_MATCH] Found {len(matching_stores)} stores to delete")
                
                # Delete each matching store
                for store in matching_stores:
                    try:
                        logger.info(f"🗑️ [DELETE_STORE] Deleting store: {store.name}")
                        
                        # Delete the entire store with force=True to clear all documents
                        client.file_search_stores.delete(name=store.name, config={"force": True})
                        deleted_stores.append(store.name)
                        logger.info(f"   ✅ Deleted store: {store.name}")
                        
                    except Exception as delete_err:
                        error_msg = f"Failed to delete store {store.name}: {delete_err}"
                        logger.error(f"   ❌ {error_msg}")
                        errors.append(error_msg)
                
        except Exception as e:
            error_msg = f"Error listing/deleting stores: {e}"
            logger.error(f"❌ [DELETE_ALL_ERROR] {error_msg}")
            errors.append(error_msg)
        
        result = {
            "stores_deleted": len(deleted_stores),
            "deleted_store_names": deleted_stores,
            "errors": errors,
            "success": len(errors) == 0
        }
        
        logger.info("=" * 80)
        if result["success"]:
            logger.info(f"✅ [DELETE_ALL_SUCCESS] Deleted {len(deleted_stores)} FileSearch stores")
            for store_name in deleted_stores:
                logger.info(f"   - Deleted: {store_name}")
        else:
            logger.error(f"❌ [DELETE_ALL_FAILED] Failed to delete {len(errors)} stores")
            for error in errors:
                logger.error(f"   - Error: {error}")
        logger.info("=" * 80)
        
        return result

    @classmethod
    def delete_and_recreate_store(cls, client: Client, store_name: str = None) -> str:
        """
        Delete existing FileSearch store and create a new one.
        This effectively clears all documents from the store.

        Uses force=True flag to delete the store and all its documents in one operation.
        This is cleaner and more efficient than manually deleting documents.

        Steps:
        1. Find the existing store
        2. Delete the store with force=True (automatically clears all documents)
        3. Create a new empty store

        Args:
            client: Gemini Client instance
            store_name: Optional store name (defaults to env var)

        Returns:
            Full store name of the new store in format: fileSearchStores/{store-id}
        """
        logger.info("=" * 80)
        logger.info("🗑️  [FILESEARCH_DELETE_RECREATE] Starting FileSearch store deletion and recreation")
        logger.info("=" * 80)

        # Get store name from parameter or environment
        if not store_name:
            store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        try:
            # Try to find and delete existing store
            if hasattr(client, 'file_search_stores'):
                logger.info(f"📋 [FILESEARCH_LIST] Listing all FileSearch stores to find '{store_name}'...")
                stores = list(client.file_search_stores.list())
                logger.info(f"   Found {len(stores)} total FileSearch stores")

                # Look for existing store by display name
                target_store = None
                for idx, store in enumerate(stores, 1):
                    store_display_name = getattr(store, 'display_name', 'N/A')
                    logger.info(f"   Store {idx}: {store.name} (display_name: {store_display_name})")

                    if hasattr(store, 'display_name') and store.display_name == store_name:
                        target_store = store
                        break

                if target_store:
                    logger.info(f"✅ Found matching store: {target_store.name}")

                    # Delete the store with force=True to clear all documents
                    logger.info(f"🗑️ [FILESEARCH_DELETE] Deleting store with force=True: {target_store.name}")
                    client.file_search_stores.delete(name=target_store.name, config={"force": True})
                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] Store deleted successfully: {target_store.name}")
                else:
                    logger.warning(f"⚠️ No matching store found for pattern: {store_name}")

        except Exception as e:
            logger.error(f"❌ [FILESEARCH_DELETE_ERROR] Error deleting store: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            raise e

        # Create new store
        logger.info(f"🔨 [FILESEARCH_CREATE] Creating new FileSearch store: {store_name}")
        try:
            new_store = client.file_search_stores.create(
                config={'display_name': store_name}
            )
            new_store_name = new_store.name
            logger.info(f"✅ [FILESEARCH_CREATE_SUCCESS] Created new store: {new_store_name}")
            
            # Clear cache
            cls._cached_store_name = None
            
            return new_store_name
        except Exception as e:
            logger.error(f"❌ [FILESEARCH_CREATE_ERROR] Failed to create new store: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            raise e
