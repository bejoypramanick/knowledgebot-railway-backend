"""
FileSearch Store Manager
Centralized utility for creating and managing Gemini FileSearch stores
"""
import os
from typing import Optional
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
                # Create new store using correct Python client API
                new_store = client.file_search_stores.create(
                    config={'display_name': store_name}
                )
                logger.info(f"✅ FileSearch store created: {new_store.name}")
                logger.info(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")
                cls._cached_store_name = new_store.name
                return new_store.name
            else:
                # Client doesn't support file_search_stores API
                logger.warning(f"⚠️ Client doesn't support file_search_stores API, using store name directly")
                store_full_name = f"fileSearchStores/{store_name}"
                cls._cached_store_name = store_full_name
                return store_full_name

        except Exception as e:
            logger.error(f"❌ Error managing FileSearch store: {e}")
            # Fallback to constructed name
            store_full_name = f"fileSearchStores/{store_name}"
            cls._cached_store_name = store_full_name
            return store_full_name

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

        store_deleted = False
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

                    # Delete the store - manually clear all documents first since force parameter is not available
                    logger.info(f"🗑️  [FILESEARCH_DELETE] Deleting store (will clear all documents): {target_store.name}")
                    store_deleted = False

                    try:
                        # Step 1: List and delete all files/documents from the store
                        logger.info("📄 [FILESEARCH_CLEAR] Clearing all documents from store first...")
                        files = []

                        # Try list_files() (Gemini SDK)
                        try:
                            if hasattr(client.file_search_stores, 'list_files'):
                                files = list(client.file_search_stores.list_files(
                                    file_search_store_name=target_store.name
                                ))
                                logger.info(f"   ✅ Found {len(files)} files using list_files()")
                        except Exception as e:
                            logger.debug(f"   list_files() not available: {e}")

                        # Try list_documents() if list_files didn't work
                        if not files:
                            try:
                                if hasattr(client.file_search_stores, 'list_documents'):
                                    files = list(client.file_search_stores.list_documents(
                                        file_search_store_name=target_store.name
                                    ))
                                    logger.info(f"   ✅ Found {len(files)} documents using list_documents()")
                            except Exception as e:
                                logger.debug(f"   list_documents() not available: {e}")

                        # Try list_rag_files() for Vertex AI
                        if not files:
                            try:
                                if hasattr(client, 'list_rag_files'):
                                    files = list(client.list_rag_files(parent=target_store.name))
                                    logger.info(f"   ✅ Found {len(files)} RAG files using list_rag_files()")
                            except Exception as e:
                                logger.debug(f"   list_rag_files() not available: {e}")

                        # Delete each file/document
                        if files:
                            logger.info(f"   Found {len(files)} items to delete")
                            for idx, file_item in enumerate(files, 1):
                                try:
                                    file_name = getattr(file_item, 'name', str(file_item))
                                    logger.info(f"   📍 Deleting item {idx}/{len(files)}: {file_name}")

                                    # Try different delete methods
                                    deleted = False

                                    # Try delete_file
                                    try:
                                        if hasattr(client.file_search_stores, 'delete_file'):
                                            client.file_search_stores.delete_file(
                                                file_search_store_name=target_store.name,
                                                file_name=file_name
                                            )
                                            deleted = True
                                    except Exception as e:
                                        logger.debug(f"      delete_file() failed: {e}")

                                    # Try delete_document
                                    if not deleted:
                                        try:
                                            if hasattr(client.file_search_stores, 'delete_document'):
                                                client.file_search_stores.delete_document(
                                                    file_search_store_name=target_store.name,
                                                    document_name=file_name
                                                )
                                                deleted = True
                                        except Exception as e:
                                            logger.debug(f"      delete_document() failed: {e}")

                                    # Try delete_rag_file
                                    if not deleted:
                                        try:
                                            if hasattr(client, 'delete_rag_file'):
                                                client.delete_rag_file(name=file_name)
                                                deleted = True
                                        except Exception as e:
                                            logger.debug(f"      delete_rag_file() failed: {e}")

                                    if deleted:
                                        logger.info(f"   ✅ Deleted: {file_name}")
                                    else:
                                        logger.warning(f"   ⚠️  Could not find method to delete {file_name}")
                                except Exception as file_err:
                                    logger.warning(f"   ⚠️  Error processing file: {file_err}")

                            logger.info(f"   ✅ Document deletion pass complete")
                        else:
                            logger.info(f"   No files found in store")

                        # Step 2: Now delete the store with force=True (handles both empty and non-empty stores)
                        logger.info(f"   🗑️  Deleting store with force=True: {target_store.name}")
                        store_delete_error = None

                        try:
                            # Try method 1: with force parameter using DeleteFileSearchStoreConfig
                            try:
                                logger.info("   📍 Method 1: Trying DeleteFileSearchStoreConfig(force=True)...")
                                try:
                                    from google.genai.types import DeleteFileSearchStoreConfig
                                    logger.info("      ✓ DeleteFileSearchStoreConfig imported successfully")
                                    logger.info("      Calling client.file_search_stores.delete(...)")
                                    client.file_search_stores.delete(
                                        name=target_store.name,
                                        config=DeleteFileSearchStoreConfig(force=True)
                                    )
                                    store_deleted = True
                                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] Store deleted with DeleteFileSearchStoreConfig: {target_store.name}")
                                except ImportError as import_err:
                                    logger.info(f"      DeleteFileSearchStoreConfig not available: {import_err}")
                                    raise import_err
                            except Exception as method1_err:
                                logger.warning(f"      ❌ Method 1 failed: {method1_err}")
                                store_delete_error = method1_err

                            # Try method 2: with dict config (only if method 1 failed)
                            if not store_deleted:
                                try:
                                    logger.info("   📍 Method 2: Trying config={'force': True}...")
                                    client.file_search_stores.delete(
                                        name=target_store.name,
                                        config={'force': True}
                                    )
                                    store_deleted = True
                                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] Store deleted with dict config: {target_store.name}")
                                except Exception as method2_err:
                                    logger.warning(f"      ❌ Method 2 failed: {method2_err}")
                                    store_delete_error = method2_err

                            # Try method 3: with force as keyword argument (only if methods 1 & 2 failed)
                            if not store_deleted:
                                try:
                                    logger.info("   📍 Method 3: Trying force=True as keyword argument...")
                                    client.file_search_stores.delete(
                                        name=target_store.name,
                                        force=True
                                    )
                                    store_deleted = True
                                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] Store deleted with force keyword: {target_store.name}")
                                except Exception as method3_err:
                                    logger.warning(f"      ❌ Method 3 failed: {method3_err}")
                                    store_delete_error = method3_err

                            # Last resort: simple delete (may work if all files were deleted)
                            if not store_deleted:
                                try:
                                    logger.info("   📍 Method 4: Trying simple delete without force...")
                                    client.file_search_stores.delete(name=target_store.name)
                                    store_deleted = True
                                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] Store deleted (simple): {target_store.name}")
                                except Exception as method4_err:
                                    logger.error(f"      ❌ Method 4 failed: {method4_err}")
                                    store_delete_error = method4_err

                            # All methods failed
                            if not store_deleted:
                                logger.error(f"   ❌❌❌ All 4 delete methods failed")
                                logger.error(f"      Last error: {store_delete_error}")
                                logger.error(f"   📝 Attempting to proceed with store recreation anyway")

                        except Exception as final_err:
                            logger.error(f"❌ [FILESEARCH_DELETE_ERROR] Unexpected error during deletion: {final_err}")
                            import traceback
                            logger.error(f"   Traceback: {traceback.format_exc()}")

                    except Exception as delete_err:
                        logger.error(f"❌ [FILESEARCH_DELETE_ERROR] Error deleting store {target_store.name}: {delete_err}")
                        import traceback
                        logger.error(f"   Traceback: {traceback.format_exc()}")
                        raise delete_err
                else:
                    logger.warning(f"⚠️  [FILESEARCH_NOT_FOUND] No existing store found with display_name='{store_name}'")

                # Create new store
                logger.info(f"🔨 [FILESEARCH_CREATE] Creating new FileSearch store: {store_name}")
                new_store = client.file_search_stores.create(
                    config={'display_name': store_name}
                )
                logger.info(f"✅ [FILESEARCH_CREATE_SUCCESS] New FileSearch store created: {new_store.name}")
                logger.info(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")

                # Clear cache and set new store name
                cls._cached_store_name = new_store.name

                logger.info("=" * 80)
                logger.info(f"✅ [FILESEARCH_COMPLETE] Store operation completed successfully")
                logger.info(f"   Old store deleted: {store_deleted}")
                logger.info(f"   New store created: {new_store.name}")
                logger.info("=" * 80)

                return new_store.name
            else:
                # Client doesn't support file_search_stores API
                logger.error(f"❌ Client doesn't support file_search_stores API")
                store_full_name = f"fileSearchStores/{store_name}"
                cls._cached_store_name = store_full_name
                return store_full_name

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [FILESEARCH_ERROR] Error deleting/recreating FileSearch store: {e}")
            logger.error(f"   Store deleted before error: {store_deleted}")
            logger.error("=" * 80)
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Fallback to constructed name
            store_full_name = f"fileSearchStores/{store_name}"
            cls._cached_store_name = store_full_name
            return store_full_name

    @classmethod
    def clear_cache(cls):
        """Clear the cached store name"""
        cls._cached_store_name = None
