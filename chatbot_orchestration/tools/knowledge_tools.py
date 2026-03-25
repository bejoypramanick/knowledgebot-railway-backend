"""
Knowledge Tools - Citation helpers and S3 debug upload utilities.

Tool functions removed. Knowledge search is handled by the pgvector-backed
`search_knowledge_base` tool.
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
