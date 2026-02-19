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

                    # Delete the store with force=True to automatically clear all documents and chunks
                    logger.info(f"🗑️  [FILESEARCH_DELETE] Deleting store with force=True (will clear all documents): {target_store.name}")
                    try:
                        # Try to delete with force parameter (different SDK versions handle this differently)
                        store_deleted = False

                        # Try method 1: force as direct argument
                        try:
                            logger.info("   Attempting delete with force=True (direct argument)...")
                            client.file_search_stores.delete(
                                name=target_store.name,
                                force=True
                            )
                            store_deleted = True
                            logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] FileSearch store deleted with force=True: {target_store.name}")
                            logger.info(f"   All documents and metadata automatically cleared")
                        except TypeError as te:
                            logger.warning(f"   ⚠️  force=True as direct argument failed: {te}")

                            # Try method 2: force in config/options object
                            try:
                                logger.info("   Attempting delete with force in delete_options...")
                                from google.protobuf.field_mask_pb2 import FieldMask
                                from google.cloud import aiplatform_v1beta1

                                # Try using delete_options
                                client.file_search_stores.delete(
                                    name=target_store.name,
                                    delete_options={'force': True}
                                )
                                store_deleted = True
                                logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] FileSearch store deleted with delete_options: {target_store.name}")
                            except Exception as opts_err:
                                logger.warning(f"   ⚠️  force in delete_options failed: {opts_err}")

                                # Try method 3: Manual document clearing before delete
                                logger.warning(f"   Falling back to manual document deletion...")
                                try:
                                    # List files using different possible method names
                                    files = None

                                    # Try list_files() first (Gemini SDK)
                                    if hasattr(client.file_search_stores, 'list_files'):
                                        files = list(client.file_search_stores.list_files(
                                            file_search_store_name=target_store.name
                                        ))
                                        logger.info(f"   Found {len(files)} files using list_files()")

                                    # Try list_documents() if list_files didn't work
                                    elif hasattr(client.file_search_stores, 'list_documents'):
                                        files = list(client.file_search_stores.list_documents(
                                            file_search_store_name=target_store.name
                                        ))
                                        logger.info(f"   Found {len(files)} documents using list_documents()")

                                    # Try list_rag_files() for Vertex AI
                                    elif hasattr(client, 'list_rag_files'):
                                        files = list(client.list_rag_files(parent=target_store.name))
                                        logger.info(f"   Found {len(files)} RAG files using list_rag_files()")

                                    if files:
                                        logger.info(f"   Found {len(files)} items to delete")
                                        for idx, file_item in enumerate(files, 1):
                                            try:
                                                file_name = getattr(file_item, 'name', str(file_item))
                                                logger.info(f"   📍 Deleting item {idx}/{len(files)}: {file_name}")

                                                # Try different delete methods
                                                if hasattr(client.file_search_stores, 'delete_file'):
                                                    client.file_search_stores.delete_file(
                                                        file_search_store_name=target_store.name,
                                                        file_name=file_name
                                                    )
                                                elif hasattr(client.file_search_stores, 'delete_document'):
                                                    client.file_search_stores.delete_document(
                                                        file_search_store_name=target_store.name,
                                                        document_name=file_name
                                                    )
                                                elif hasattr(client, 'delete_rag_file'):
                                                    client.delete_rag_file(name=file_name)

                                                logger.info(f"   ✅ Deleted: {file_name}")
                                            except Exception as file_err:
                                                logger.warning(f"   ⚠️  Could not delete {file_name}: {file_err}")

                                        logger.info(f"   ✅ All files cleared from store")

                                    # Now delete the (hopefully empty) store
                                    logger.info(f"   Deleting now-empty store...")
                                    client.file_search_stores.delete(name=target_store.name)
                                    store_deleted = True
                                    logger.info(f"✅ [FILESEARCH_DELETE_SUCCESS] FileSearch store deleted: {target_store.name}")
                                except Exception as manual_err:
                                    logger.error(f"❌ [FILESEARCH_DELETE_ERROR] Error in manual deletion fallback: {manual_err}")
                                    raise manual_err

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
