"""
AI Service for Website Crawling
Handles uploading scraped content to Gemini FileSearch
"""
import asyncio
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from google.genai import types

from website_crawling.core.otel_logger import get_otel_logger
from website_crawling.core.ai import get_genai_client
from website_crawling.service.website_service import WebsiteService

logger = get_otel_logger("ai_service", "website-crawling")


async def upload_content_to_gemini(
    content: str,
    url: str,
    title: str,
    user_email: str = None
) -> Dict[str, Any]:
    """
    Upload scraped content to Gemini FileSearch.
    Args:
        content: The scraped text content
        url: Original URL that was scraped
        title: Page title
        user_email: User email for metadata
    Returns:
        Dict with upload result including file name and state
    """
    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("Gemini client not available - returning placeholder response")
        return {
            "success": False,
            "error": "Gemini client not configured",
            "file_name": None,
            "state": "FAILED"
        }
    
    try:
        # Create a temporary file for the content
        fd, temp_path = tempfile.mkstemp(suffix='.md')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                # Add title and URL at the top for better context in Gemini FileSearch
                if title:
                    f.write(f"# {title}\n\n")
                if url:
                    f.write(f"Source URL: {url}\n\n")
                
                f.write(content)
                
            # Clean URL for filename (remove protocol, slashes, special chars)
            clean_url = url.replace('https://', '').replace('http://', '')
            clean_url = clean_url.replace('/', '_').replace(':', '_').replace('?', '_')
            clean_url = clean_url[:50]  # Limit length
            temp_filename = f"scraped_{clean_url}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            
            # Resolve FileSearch store on-demand
            from shared.file_search import get_file_search_store_by_display_name
            file_search_store_name = get_file_search_store_by_display_name(
                genai_client,
                display_name="knowledgebot-search-store"
            )

            if file_search_store_name:
                logger.info(f"📤 Uploading to FileSearch store: {file_search_store_name}")
                operation = genai_client.file_search_stores.upload_to_file_search_store(
                    file=temp_path,
                    file_search_store_name=file_search_store_name,
                    config={
                        'display_name': temp_filename,
                        'custom_metadata': [
                            {'key': 'original_url', 'string_value': url},
                            {'key': 'user_email', 'string_value': user_email or 'admin'}
                        ]
                    }
                )

                # Poll for operation completion
                final_state = "PENDING"
                gemini_processed_at = None
                document_name = None

                for i in range(15):  # Poll for up to 30 seconds
                    try:
                        current_operation = genai_client.operations.get(operation)
                        if not current_operation:
                            logger.warning(f"🔄 [GEMINI] Poll attempt {i+1}: Operation is None")
                            await asyncio.sleep(2)
                            continue

                        # Extremely defensive check for response and state
                        resp = getattr(current_operation, 'response', None)
                        if resp:
                            if hasattr(resp, 'document_name') and resp.document_name:
                                final_state = "ACTIVE"
                                document_name = resp.document_name
                                logger.info(f"✅ [GEMINI] FileSearch upload complete - Document: {document_name}")
                                gemini_processed_at = datetime.utcnow()
                                break
                            
                            # Check for state nested in response
                            state_obj = getattr(resp, 'state', None)
                            if state_obj:
                                final_state = getattr(state_obj, 'name', str(state_obj))
                                logger.info(f"🔄 [GEMINI] FileSearch operation state (Attempt {i+1}/15): {final_state}")
                                if final_state == "ACTIVE":
                                    gemini_processed_at = datetime.utcnow()
                                    break
                        else:
                            # Some operations have state at the top level
                            top_state = getattr(current_operation, 'state', None)
                            if top_state:
                                final_state = getattr(top_state, 'name', str(top_state))
                                logger.info(f"🔄 [GEMINI] Operation top-level state (Attempt {i+1}/15): {final_state}")
                                if final_state == "ACTIVE":
                                    break
                        
                        await asyncio.sleep(2)
                    except Exception as poll_err:
                        logger.warning(f"⚠️ [GEMINI] Error during polling attempt {i+1}: {poll_err}")
                        await asyncio.sleep(2)

                return {
                    "success": final_state == "ACTIVE",
                    "file_name": document_name or temp_filename,
                    "state": final_state,
                    "processed_at": gemini_processed_at.isoformat() if gemini_processed_at else None,
                }
            else:
                # Fallback to general file upload
                logger.info("📤 Using general file upload (no FileSearch store configured)")
                gemini_file = genai_client.files.upload(
                    file=temp_path,
                    config=types.UploadFileConfig(
                        display_name=temp_filename,
                        mime_type="text/markdown"
                    )
                )
                
                return {
                    "success": True,
                    "file_name": gemini_file.name,
                    "file_uri": gemini_file.uri,
                    "state": gemini_file.state if hasattr(gemini_file, 'state') else "ACTIVE"
                }

        except Exception as e:
            logger.error(f"❌ Error uploading to Gemini: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "file_name": None,
                "state": "FAILED"
            }
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass

    except Exception as e:
        logger.error(f"❌ Error uploading content to Gemini: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_name": None,
            "state": "FAILED"
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


async def record_scraped_metadata(
    url: str,
    domain: str,
    title: str,
    content_length: int,
    pages_scraped: int,
    gemini_file_name: str,
    gemini_file_uri: str,
    gemini_state: str,
    scraped_urls: List[str],
    scraping_config: Dict[str, Any],
    version: int = 1,
    user_id: str = None
) -> Optional[str]:
    """
    Record scraped website metadata to database.

    Returns:
        Record ID if successful, None otherwise
    """
    try:
        website_service = WebsiteService()

        # Get admin user_role_id (same logic as file uploads)
        admin_user_role_id = await get_admin_user_role_id()
        if not admin_user_role_id:
            logger.error("❌ Failed to get admin user_role_id for scraped metadata")
            return None

        metadata = {
            "user_role_id": admin_user_role_id,  # Use the admin user_role_id
            "url": url,
            "domain": domain,
            "title": title,
            "description": f"Scraped from {url}",
            "content_length": content_length,
            "pages_scraped": pages_scraped,
            "status": gemini_state if gemini_state else "pending",
            "gemini_file_name": gemini_file_name,
            "gemini_file_uri": gemini_file_uri
        }

        record_id = await website_service.insert_scraped_metadata(metadata)
        logger.info(f"✅ Scraped metadata recorded: {record_id}")
        return record_id

    except Exception as e:
        logger.error(f"❌ Failed to persist scraped metadata: {e}")
        return None


async def get_admin_user_role_id() -> Optional[str]:
    """Get user_role_id for admin role - same logic as file uploads"""
    try:
        from website_crawling.core.db import get_db_connection
        
        async with get_db_connection() as conn:
            # First get the admin role ID
            admin_role = await conn.fetchrow(
                "SELECT id FROM roles WHERE role_name = 'admin'"
            )
            
            if not admin_role:
                logger.error("Admin role not found in roles table")
                return None
            
            admin_role_id = admin_role['id']
            
            # Check if user has admin role mapping (use a default admin user)
            admin_mapping = await conn.fetchrow(
                """SELECT user_role_id 
                   FROM user_role_mapping 
                   WHERE role_id = $1 AND is_active = true
                   LIMIT 1""",
                admin_role_id
            )
            
            if admin_mapping:
                logger.info(f"Using admin user_role_id: {admin_mapping['user_role_id']}")
                return admin_mapping['user_role_id']
            else:
                logger.warning("No admin user_role_mapping found - scraped websites may not be saved")
                return None
            
    except Exception as e:
        logger.error(f"Error getting admin user role ID: {e}")
        return None
