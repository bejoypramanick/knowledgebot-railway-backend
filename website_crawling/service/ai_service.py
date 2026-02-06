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
        fd, temp_path = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({
                    "content": content,
                    "url": url,
                    "title": title,
                    "user_email": user_email,
                    "timestamp": datetime.now().isoformat(),
                    "source": "website_crawling"
                }, f, indent=2)
                temp_filename = f"scraped_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                
                # Upload to Gemini FileSearch
                gemini_file = genai_client.upload_file(
                    file_path=temp_path,
                    display_name=temp_filename,
                    mime_type="application/json"
                )
                
                # Get the file metadata
                file_metadata = genai_client.get_file(gemini_file.name)
                
                if file_metadata:
                    logger.info(f"✅ Successfully uploaded to Gemini FileSearch: {temp_filename}")
                    logger.info(f"📄 File ID: {file_metadata.name}")
                    logger.info(f"� File URI: {file_metadata.uri}")
                    
                    return {
                        "success": True,
                        "file_name": temp_filename,
                        "file_uri": file_metadata.uri,
                        "state": file_metadata.state
                    }
                else:
                    logger.error(f"❌ Failed to upload to Gemini FileSearch: {temp_filename}")
                    return {
                        "success": False,
                        "error": "Upload failed",
                        "file_name": None,
                        "state": "FAILED"
                    }
        except Exception as e:
            logger.error(f"❌ Error uploading to Gemini FileSearch: {e}")
            return {
                "success": False,
                "error": f"Upload error: {str(e)}",
                "file_name": None,
                "state": "ERROR"
            }
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete temporary file: {e}")
        )

        # Poll for operation completion
        final_state = "PENDING"
        gemini_processed_at = None
        document_name = None

        for i in range(15):  # Poll for up to 30 seconds
            current_operation = genai_client.operations.get(operation)

            # FileSearch upload returns document_name when done, not state
            if hasattr(current_operation.response, 'document_name'):
                final_state = "ACTIVE"
                document_name = current_operation.response.document_name
                logger.info(f"✅ [GEMINI] FileSearch upload complete - Document: {document_name}")
                gemini_processed_at = datetime.utcnow()
                break
            elif hasattr(current_operation.response.state, 'name'):
                # Fallback for other operation types that return state
                final_state = current_operation.response.state.name
                logger.info(f"🔄 [GEMINI] FileSearch operation state (Attempt {i+1}/15): {final_state}")

                if final_state == "ACTIVE":
                    gemini_processed_at = datetime.utcnow()
                    logger.info("⚡ [GEMINI] FileSearch upload complete - Content is now ACTIVE")
                    break
                elif final_state == "FAILED":
                    logger.error(f"❌ [GEMINI] FileSearch upload FAILED for {url}")
                    break
            else:
                logger.warning(f"⚠️ [GEMINI] Unknown operation response structure (Attempt {i+1}/15)")

            await asyncio.sleep(2)

        return {
            "success": final_state == "ACTIVE",
            "file_name": document_name or (operation.response.name if hasattr(operation.response, 'name') else None),
            "state": final_state,
            "processed_at": gemini_processed_at.isoformat() if gemini_processed_at else None,
            "file_search_store": file_search_store_name
        }

    except Exception as e:
        logger.error(f"❌ Error uploading content to Gemini: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_name": None,
            "state": "FAILED"
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
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
