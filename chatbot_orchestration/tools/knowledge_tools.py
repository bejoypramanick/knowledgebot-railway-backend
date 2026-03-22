"""
Knowledge Tools - Citation helpers and S3 debug upload utilities.

Tool functions removed. Knowledge search is handled by Pydantic AI's builtin FileSearchTool.
Human agent detection is handled by keyword matching in streaming_service.py.
"""

import boto3
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("knowledge_tools", "chatbot-orchestration")


def build_citation_tree(urls: List[str]) -> Dict[str, Any]:
    """
    Convert flat list of URLs to hierarchical tree structure.

    Examples:
        Input: ["https://example.com", "https://example.com/about", "https://example.com/services"]
        Output: {
            "https://example.com": {
                "url": "https://example.com",
                "children": {
                    "https://example.com/about": {"url": "...", "children": {}},
                    "https://example.com/services": {"url": "...", "children": {}}
                }
            }
        }
    """
    tree = {}

    # Sort URLs by depth (fewer slashes = higher level)
    sorted_urls = sorted(urls, key=lambda u: u.count('/'))

    for url in sorted_urls:
        parts = url.split('/')
        current_level = tree
        current_url = ""

        # Build URL progressively: scheme://domain, then add path segments
        for i, part in enumerate(parts):
            if i <= 2:  # scheme, empty, domain
                current_url += part + ("/" if i < 2 else "")
            else:  # path segments
                current_url += "/" + part

            if current_url not in current_level:
                current_level[current_url] = {"url": current_url, "children": {}}

            current_level = current_level[current_url]["children"]

    return tree


async def get_citation_hierarchy(urls: List[str]) -> Dict[str, Any]:
    """
    Query database to get actual parent-child relationships from scraped_websites table.
    Falls back to tree building if database relationships not available.
    """
    try:
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            # Get all records matching URLs with hierarchy info
            query = """
                SELECT id, original_url, parent_id, depth, crawl_session_id
                FROM scraped_websites
                WHERE original_url = ANY(CAST(:urls AS text[])) AND processing_status != 'deleted'
                ORDER BY depth, original_url
            """
            result = await session.execute(text(query), {"urls": urls})
            records = result.mappings().all()

            if not records:
                # Fall back to building tree from flat list
                logger.info("No hierarchy records found - building tree from flat URL list")
                return build_citation_tree(urls)

            # Build tree from database relationships
            tree = {}
            id_to_node = {}

            for record_proxy in records:
                # Convert SQLAlchemy Row to dict-like access
                record = dict(record_proxy._mapping) if hasattr(record_proxy, '_mapping') else dict(record_proxy)
                node = {
                    "id": record.get("id"),
                    "url": record.get("original_url"),
                    "depth": record.get("depth"),
                    "children": {}
                }
                id_to_node[record.get("id")] = node

                if record.get("parent_id") is None:
                    # Root node
                    tree[record.get("original_url")] = node
                else:
                    # Add to parent's children
                    parent_node = id_to_node.get(record.get("parent_id"))
                    if parent_node:
                        parent_node["children"][record.get("original_url")] = node

            return tree

    except Exception as e:
        logger.warning(f"Error querying database for hierarchy: {e} - falling back to URL parsing")
        # Fall back to building tree from flat list
        return build_citation_tree(urls)


async def _batch_lookup_urls_by_gemini_file_names(doc_titles: List[str]) -> Dict[str, str]:
    """
    Batch lookup original source URLs using Gemini retrieved_context.title values.
    Returns {title: url} mapping.

    Lookup order:
    1. Redis cache (fast, 24h TTL)
    2. Database fallback (cache misses only)
    3. Cache DB results back to Redis

    Gemini FileSearch returns retrieved_context.title = the display_name set during upload
    (e.g. "page_019d122b-1c64-793c-88d4-7caae454d1bc_1774126453").
    This is stored in metadata->>'display_name' in the scraped_websites table.
    """
    if not doc_titles:
        return {}

    try:
        from shared.redis_citation_cache import get_cached_urls, cache_url_mappings

        # Phase 1: Check Redis cache first
        url_map = await get_cached_urls(doc_titles)
        cache_hits = len(url_map)

        # Phase 2: DB lookup for cache misses only
        uncached_titles = [t for t in doc_titles if t not in url_map]

        if uncached_titles:
            logger.info(f"📎 [CITATION_LOOKUP] Cache: {cache_hits} hits, {len(uncached_titles)} misses → querying DB")
            db_results = await _db_lookup_urls(uncached_titles)
            url_map.update(db_results)

            # Phase 3: Cache DB results for next time
            if db_results:
                await cache_url_mappings(db_results)
        else:
            logger.info(f"📎 [CITATION_LOOKUP] All {cache_hits} titles resolved from cache")

        logger.info(f"📎 [CITATION_LOOKUP] Result: {len(url_map)}/{len(doc_titles)} URLs mapped (cache: {cache_hits}, db: {len(url_map) - cache_hits})")
        return url_map

    except Exception as e:
        logger.error(f"❌ [CITATION_LOOKUP] Error looking up URLs: {e}", exc_info=True)
        return {}


async def _db_lookup_urls(doc_titles: List[str]) -> Dict[str, str]:
    """Database fallback for citation URL lookup. Called on Redis cache miss."""
    try:
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            logger.info(f"📎 [CITATION_DB] Looking up {len(doc_titles)} titles in database")

            result = await session.execute(text("""
                SELECT
                    metadata->>'display_name' AS display_name,
                    gemini_file_name,
                    original_url
                FROM scraped_websites
                WHERE processing_status != 'deleted'
                AND original_url IS NOT NULL
                AND (
                    metadata->>'display_name' = ANY(:titles)
                    OR gemini_file_name = ANY(:titles)
                )
            """), {"titles": doc_titles})
            rows = result.fetchall()

            url_map = {}
            for display_name, gemini_file_name, original_url in rows:
                for title in doc_titles:
                    if title == display_name or title == gemini_file_name:
                        url_map[title] = original_url
                        logger.info(f"📎 [CITATION_DB] ✅ {title} → {original_url}")

            # Fallback: extract website_id from title pattern and match by id
            unmatched = [t for t in doc_titles if t not in url_map]
            if unmatched:
                import re as _re
                for title in unmatched:
                    match = _re.match(r'^page_(.+)_(\d+)$', title)
                    if match:
                        website_id = match.group(1)
                        logger.info(f"📎 [CITATION_DB] Fallback: website_id={website_id} from {title}")

                        fallback_result = await session.execute(text("""
                            SELECT original_url FROM scraped_websites
                            WHERE (id::text = :website_id OR parent_id::text = :website_id)
                            AND processing_status != 'deleted'
                            AND original_url IS NOT NULL
                            LIMIT 1
                        """), {"website_id": website_id})
                        fallback_row = fallback_result.fetchone()

                        if fallback_row:
                            url_map[title] = fallback_row[0]
                            logger.info(f"📎 [CITATION_DB] ✅ Fallback: {title} → {fallback_row[0]}")
                        else:
                            logger.warning(f"📎 [CITATION_DB] ❌ No match: {title}")

            return url_map

    except Exception as e:
        logger.error(f"❌ [CITATION_DB] Database lookup failed: {e}", exc_info=True)
        return {}

def _trim_system_prompt_content(data: Any, max_chars: int = 10) -> Any:
    """
    Recursively trim SystemPromptPart content to prevent exposing full system prompt in S3 uploads.
    
    Args:
        data: The data structure to process (dict, list, or other)
        max_chars: Maximum characters to keep from system prompt (default: 10)
        
    Returns:
        Data with system prompt content trimmed to max_chars + "..."
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key == 'content' and isinstance(value, str) and len(value) > 50:
                # Check if this looks like a system prompt (long content starting with instructions)
                if any(indicator in value.lower()[:100] for indicator in ['🚨', 'custom instructions', 'rule', 'you are', 'system']):
                    original_length = len(value)
                    result[key] = value[:max_chars] + "..." if len(value) > max_chars else value
                    logger.info(f"📝 Trimmed system prompt content: {original_length} chars → {len(result[key])} chars")
                    continue
            result[key] = _trim_system_prompt_content(value, max_chars)
        return result
    elif isinstance(data, list):
        return [_trim_system_prompt_content(item, max_chars) for item in data]
    elif isinstance(data, str):
        # Check if this is a string representation of a SystemPromptPart
        if 'SystemPromptPart(content=' in data and len(data) > 100:
            # Extract just the first part and trim
            if 'content=' in data:
                start_idx = data.find('content=') + 9  # Skip 'content="'
                if start_idx < len(data):
                    original_length = len(data)
                    trimmed_content = data[start_idx:start_idx + max_chars] + "..."
                    result = data[:start_idx] + trimmed_content + "')"
                    logger.info(f"📝 Trimmed SystemPromptPart string: {original_length} chars → {len(result)} chars")
                    return result
        return data
    else:
        return data


async def _upload_agent_request_to_s3(session_id: str, user_message: str, conversation_history: list = None) -> Optional[str]:
    """
    Upload agent request data (user message and conversation history) to S3 for debugging.
    
    Args:
        session_id: Session identifier
        user_message: The user's message/query
        conversation_history: Previous conversation messages
        
    Returns:
        S3 download URL if successful, None otherwise
    """
    try:
        from ..core.s3_client import get_s3_client, get_bucket_name
        import json
        from datetime import datetime
        
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("📁 S3 client not configured - skipping agent request upload")
            return None
        
        # Build comprehensive request data structure
        request_data = {
            "upload_info": {
                "type": "agent_request",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "capture_method": "user_message_capture",
                "user_message_length": len(user_message),
                "conversation_history_count": len(conversation_history) if conversation_history else 0
            },
            "user_message": user_message,
            "conversation_history": _trim_system_prompt_content(conversation_history or []),
            "session_metadata": {
                "session_id": session_id,
                "capture_timestamp": datetime.utcnow().isoformat()
            }
        }
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"agent_request_{timestamp}.json"
        
        # Upload to S3
        bucket_name = get_bucket_name()
        if not bucket_name:
            logger.warning("📁 S3 bucket name not configured - skipping agent request upload")
            return None
        
        s3_key = f"agent-requests/{session_id}/{filename}"
        
        # Convert to JSON string
        json_content = json.dumps(request_data, indent=2, default=str)
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json'
        )
        
        # Generate presigned URL for download (1 hour expiry)
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        logger.info(f"📁 ✅ Agent request uploaded to S3: {s3_key}")
        logger.info(f"📁 ✅ Agent request download URL: {download_url}")
        
        return download_url
        
    except Exception as e:
        logger.error(f"📁 ❌ Failed to upload agent request to S3: {e}", exc_info=True)
        return None


async def _upload_file_search_tool_request_to_s3(session_id: str, query: str, contents: list, conversation_history: list, file_search_store_name: str) -> Optional[str]:
    """
    Upload FileSearch tool request data to S3 for debugging.
    
    Args:
        session_id: Session identifier
        query: Original user query
        contents: Complete contents array sent to Gemini API
        conversation_history: Formatted conversation history
        file_search_store_name: FileSearch store name used
        
    Returns:
        S3 download URL if successful, None otherwise
    """
    try:
        from ..core.s3_client import get_s3_client, get_bucket_name
        import json
        from datetime import datetime
        
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("📁 S3 client not configured - skipping FileSearch tool request upload")
            return None
        
        # Build comprehensive input data structure
        input_data = {
            "upload_info": {
                "type": "file_search_tool_request",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "capture_method": "pre_api_call",
                "query_length": len(query),
                "contents_count": len(contents),
                "conversation_history_count": len(conversation_history) if conversation_history else 0
            },
            "original_query": query,
            "file_search_store_name": file_search_store_name,
            "conversation_history": _trim_system_prompt_content(conversation_history),
            "complete_contents_array": []
        }
        
        # Convert contents array to serializable format
        for i, content in enumerate(contents):
            content_data = {
                "index": i,
                "role": getattr(content, 'role', 'unknown'),
                "parts": []
            }
            
            if hasattr(content, 'parts'):
                for j, part in enumerate(content.parts):
                    part_data = {
                        "part_index": j,
                        "type": type(part).__name__
                    }
                    
                    if hasattr(part, 'text'):
                        # Trim system prompt content in parts as well
                        part_text = part.text
                        if 'system' in getattr(content, 'role', '').lower() or 'SystemPromptPart' in type(part).__name__:
                            part_text = part_text[:10] + "..." if len(part_text) > 10 else part_text
                        part_data["text"] = part_text
                        part_data["text_length"] = len(part.text)
                    
                    content_data["parts"].append(part_data)
            
            input_data["complete_contents_array"].append(content_data)
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"file_search_tool_request_{timestamp}.json"
        
        # Upload to S3
        bucket_name = get_bucket_name()
        if not bucket_name:
            logger.warning("📁 S3 bucket name not configured - skipping FileSearch tool request upload")
            return None
        
        s3_key = f"file-search-requests/{session_id}/{filename}"
        
        # Convert to JSON string
        json_content = json.dumps(input_data, indent=2, default=str)
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json'
        )
        
        # Generate presigned URL for download (1 hour expiry)
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        logger.info(f"📁 ✅ FileSearch tool request uploaded to S3: {s3_key}")
        logger.info(f"📁 ✅ FileSearch tool request download URL: {download_url}")
        
        return download_url
        
    except Exception as e:
        logger.error(f"📁 ❌ Failed to upload FileSearch tool request to S3: {e}", exc_info=True)
        return None


async def _upload_file_search_tool_response_to_s3(session_id: str, response_text: str, full_response: Any) -> Optional[str]:
    """
    Upload the complete FileSearch tool response to S3 and return a download URL.
    
    This feature is controlled by the ENABLE_RAG_S3_UPLOAD environment variable.
    When enabled, captures the complete raw response from Gemini FileSearch API
    including grounding metadata, usage statistics, and all response details.
    
    Args:
        session_id: Session identifier for organizing uploads
        response_text: Extracted text response from FileSearch
        full_response: Complete response object from Gemini API
        
    Returns:
        S3 download URL if successful, None otherwise
    """
    try:
        from ..core.s3_client import get_s3_client, get_bucket_name
        import json
        from datetime import datetime
        
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("📁 S3 client not configured - skipping FileSearch tool response upload")
            return None
        
        # Build comprehensive response data structure
        response_data = {
            "upload_info": {
                "type": "file_search_tool_response",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "capture_method": "model_dump",
                "response_text_length": len(response_text)
            },
            "extracted_response_text": response_text,
            "complete_raw_response": {}
        }
        
        # Capture complete raw response using model_dump if available
        try:
            if hasattr(full_response, 'model_dump'):
                response_data["complete_raw_response"] = _trim_system_prompt_content(full_response.model_dump())
                logger.info("📁 ✅ Captured complete response using model_dump()")
            elif hasattr(full_response, '__dict__'):
                # Fallback to __dict__ if model_dump not available
                response_data["complete_raw_response"] = _trim_system_prompt_content(full_response.__dict__)
                logger.info("📁 ✅ Captured complete response using __dict__")
            else:
                # Last resort: convert to string
                response_data["complete_raw_response"] = {"raw_str": str(full_response)}
                logger.info("📁 ⚠️ Captured response as string (no model_dump or __dict__)")
        except Exception as capture_error:
            logger.warning(f"📁 ⚠️ Error capturing raw response: {capture_error}")
            response_data["complete_raw_response"] = {"error": str(capture_error), "raw_str": str(full_response)}
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"file_search_tool_response_{timestamp}.json"
        
        # Upload to S3
        bucket_name = get_bucket_name()
        if not bucket_name:
            logger.warning("📁 S3 bucket name not configured - skipping FileSearch tool response upload")
            return None
        
        s3_key = f"file-search-responses/{session_id}/{filename}"
        
        # Convert to JSON string with proper serialization
        json_content = json.dumps(response_data, indent=2, default=str)
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json'
        )
        
        # Generate presigned URL for download (1 hour expiry)
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        logger.info(f"📁 ✅ FileSearch tool response uploaded to S3: {s3_key}")
        logger.info(f"📁 ✅ FileSearch tool response download URL: {download_url}")
        
        return download_url
        
    except Exception as e:
        logger.error(f"📁 ❌ Failed to upload FileSearch tool response to S3: {e}", exc_info=True)
        return None


async def _upload_rag_response_to_s3(session_id: str, response_text: str, full_response: Any) -> Optional[str]:
    """
    Upload the complete RAG response to S3 and return a download URL.
    
    This feature is controlled by the ENABLE_RAG_S3_UPLOAD environment variable.
    Set ENABLE_RAG_S3_UPLOAD=true to enable RAG response uploads to S3.
    
    Args:
        session_id: The chat session ID
        response_text: The extracted response text
        full_response: The complete Gemini response object
        
    Returns:
        S3 download URL or None if upload failed
    """
    try:
        logger.info(f"📁 Starting RAG response S3 upload for session: {session_id}")
        logger.info(f"📁 COMPLETE RAW RESPONSE DUMP - No extraction, just raw data")
        
        # Get S3 configuration from environment
        bucket_name = os.getenv("RAILWAY_BUCKET_NAME")
        aws_access_key = os.getenv("RAILWAY_STORAGE_ACCESS_KEY")
        aws_secret_key = os.getenv("RAILWAY_STORAGE_SECRET_KEY")
        aws_region = os.getenv("RAILWAY_REGION", "us-east-1")
        storage_url = os.getenv("RAILWAY_STORAGE_URL")
        
        logger.info(f"📁 S3 Config - Bucket: {bucket_name}, Region: {aws_region}, Storage URL: {storage_url}")
        logger.info(f"📁 S3 Config - Has Access Key: {bool(aws_access_key)}, Has Secret Key: {bool(aws_secret_key)}")
        
        if not all([bucket_name, aws_access_key, aws_secret_key]):
            missing = []
            if not bucket_name: missing.append("RAILWAY_BUCKET_NAME")
            if not aws_access_key: missing.append("RAILWAY_STORAGE_ACCESS_KEY")
            if not aws_secret_key: missing.append("RAILWAY_STORAGE_SECRET_KEY")
            logger.warning(f"📁 S3 credentials not configured - missing: {', '.join(missing)}")
            return None
            
        # Create S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
            endpoint_url=storage_url if storage_url else None
        )
        
        # Create minimal metadata wrapper - COMPLETE RAW RESPONSE DUMP
        timestamp = datetime.utcnow().isoformat()
        
        # Try multiple methods to capture the COMPLETE raw response object
        raw_response_data = None
        capture_method = "none"
        
        try:
            # Method 1: Try model_dump() first (Pydantic models)
            if hasattr(full_response, 'model_dump'):
                raw_response_data = full_response.model_dump()
                capture_method = "model_dump"
                logger.info("📦 RAG S3: Captured via model_dump()")
            # Method 2: Try __dict__ (regular objects)
            elif hasattr(full_response, '__dict__'):
                raw_response_data = full_response.__dict__
                capture_method = "__dict__"
                logger.info("📦 RAG S3: Captured via __dict__")
            # Method 3: Try to convert to dict if it's a dataclass or similar
            elif hasattr(full_response, '_asdict'):
                raw_response_data = full_response._asdict()
                capture_method = "_asdict"
                logger.info("📦 RAG S3: Captured via _asdict()")
            # Method 4: Try vars() function
            else:
                try:
                    raw_response_data = vars(full_response)
                    capture_method = "vars"
                    logger.info("📦 RAG S3: Captured via vars()")
                except:
                    # Method 5: Last resort - string representation
                    raw_response_data = str(full_response)
                    capture_method = "str"
                    logger.info("📦 RAG S3: Captured via str() (last resort)")
        except Exception as capture_error:
            logger.error(f"📦 RAG S3: All capture methods failed: {capture_error}")
            raw_response_data = f"CAPTURE_ERROR: {str(capture_error)}"
            capture_method = "error"
        
        # Trim any system prompt content that might be in the response
        trimmed_response_data = _trim_system_prompt_content(raw_response_data)
        
        # Minimal wrapper - just metadata + complete raw response
        response_data = {
            "upload_info": {
                "type": "complete_gemini_filesearch_response",
                "session_id": session_id,
                "timestamp": timestamp,
                "capture_method": capture_method,
                "response_text_length": len(response_text) if response_text else 0
            },
            "complete_raw_response": trimmed_response_data,
            "extracted_response_text": response_text  # Keep this for reference but raw data is the main content
        }
        
        # Convert to formatted JSON
        json_content = json.dumps(response_data, indent=2, ensure_ascii=False)
        
        # Create S3 key with timestamp and session
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"rag-responses/{session_id}/rag_response_{timestamp_str}.json"
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json',
            ContentDisposition=f'attachment; filename="rag_response_{timestamp_str}.json"'
        )
        
        # Generate download URL (expires in 1 hour)
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600  # 1 hour
        )
        
        logger.info(f"📁 RAG response uploaded to S3: {s3_key}")
        return download_url
        
    except Exception as e:
        logger.error(f"❌ Failed to upload RAG response to S3: {e}")
        return None

async def _upload_agent_response_to_s3(session_id: str, all_messages: list, run_object: Any = None) -> Optional[str]:
    """
    Upload the complete agent response to S3 and return a download URL.
    
    This feature is controlled by the ENABLE_RAG_S3_UPLOAD environment variable.
    Set ENABLE_RAG_S3_UPLOAD=true to enable agent response uploads to S3.
    
    Args:
        session_id: The chat session ID
        all_messages: The complete message history from agent.iter()
        run_object: The run object from agent.iter() (may contain raw response)
        
    Returns:
        S3 download URL or None if upload failed
    """
    try:
        logger.info(f"📁 Starting agent response S3 upload for session: {session_id}")
        logger.info(f"📁 COMPLETE RAW AGENT DUMP - No extraction, just raw data")
        
        # Use centralized S3 client
        from ..core.s3_client import get_s3_client, get_bucket_name
        
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("📁 S3 client not available - agent response upload skipped")
            return None
            
        bucket_name = get_bucket_name()
        
        # Create minimal wrapper - COMPLETE RAW AGENT RESPONSE DUMP
        timestamp = datetime.utcnow().isoformat()
        
        # Capture ALL messages without processing - just convert to serializable format
        raw_messages_data = []
        for i, msg in enumerate(all_messages):
            try:
                # Try multiple methods to capture complete message data
                if hasattr(msg, 'model_dump'):
                    msg_data = msg.model_dump()
                elif hasattr(msg, '__dict__'):
                    msg_data = msg.__dict__
                elif hasattr(msg, '_asdict'):
                    msg_data = msg._asdict()
                else:
                    msg_data = str(msg)
                
                # Trim system prompt content for privacy
                trimmed_msg_data = _trim_system_prompt_content(msg_data)
                
                raw_messages_data.append({
                    "message_index": i,
                    "raw_message_data": trimmed_msg_data
                })
            except Exception as msg_error:
                raw_messages_data.append({
                    "message_index": i,
                    "error": str(msg_error),
                    "fallback_str": str(msg)
                })
        
        # Capture complete run object if available
        raw_run_data = None
        run_capture_method = "none"
        if run_object:
            try:
                if hasattr(run_object, 'model_dump'):
                    raw_run_data = run_object.model_dump()
                    run_capture_method = "model_dump"
                elif hasattr(run_object, '__dict__'):
                    raw_run_data = run_object.__dict__
                    run_capture_method = "__dict__"
                elif hasattr(run_object, '_asdict'):
                    raw_run_data = run_object._asdict()
                    run_capture_method = "_asdict"
                else:
                    raw_run_data = str(run_object)
                    run_capture_method = "str"
            except Exception as run_error:
                raw_run_data = f"RUN_CAPTURE_ERROR: {str(run_error)}"
                run_capture_method = "error"
        
        # Minimal wrapper - just metadata + complete raw data
        response_data = {
            "upload_info": {
                "type": "complete_agent_response",
                "session_id": session_id,
                "timestamp": timestamp,
                "messages_count": len(all_messages),
                "run_capture_method": run_capture_method
            },
            "complete_raw_messages": raw_messages_data,
            "complete_raw_run_object": raw_run_data
        }
        
        # Convert to formatted JSON
        json_content = json.dumps(response_data, indent=2, ensure_ascii=False, default=str)
        
        # Create S3 key with timestamp and session
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"agent-responses/{session_id}/agent_response_{timestamp_str}.json"
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json',
            ContentDisposition=f'attachment; filename="agent_response_{timestamp_str}.json"'
        )
        
        # Generate download URL (expires in 1 hour)
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600  # 1 hour
        )
        
        logger.info(f"📁 Agent response uploaded to S3: {s3_key}")
        return download_url
        
    except Exception as e:
        logger.error(f"❌ Failed to upload agent response to S3: {e}")
        return None