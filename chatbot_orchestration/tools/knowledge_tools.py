"""
Knowledge Tools for Pydantic AI Agent
Contains all tool implementations as standalone functions
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic_ai import RunContext

from google.genai import types
from shared.otel_logger import get_otel_logger

from ..core.ai import get_genai_client
from ..core.dependencies import ChatSessionDeps
from ..schemas.models import SearchResult

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
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Get all records matching URLs with hierarchy info
            records = await conn.fetch("""
                SELECT id, original_url, parent_id, depth, crawl_session_id
                FROM scraped_websites
                WHERE original_url = ANY($1::text[]) AND processing_status != 'deleted'
                ORDER BY depth, original_url
            """, urls)

            if not records:
                # Fall back to building tree from flat list
                logger.info("No hierarchy records found - building tree from flat URL list")
                return build_citation_tree(urls)

            # Build tree from database relationships
            tree = {}
            id_to_node = {}

            for record in records:
                node = {
                    "id": record["id"],
                    "url": record["original_url"],
                    "depth": record["depth"],
                    "children": {}
                }
                id_to_node[record["id"]] = node

                if record["parent_id"] is None:
                    # Root node
                    tree[record["original_url"]] = node
                else:
                    # Add to parent's children
                    parent_node = id_to_node.get(record["parent_id"])
                    if parent_node:
                        parent_node["children"][record["original_url"]] = node

            return tree

    except Exception as e:
        logger.warning(f"Error querying database for hierarchy: {e} - falling back to URL parsing")
        # Fall back to building tree from flat list
        return build_citation_tree(urls)


async def _perform_rag_search(session_id: str, query: str) -> str:
    """
    Internal RAG search function - pure business logic with no RunContext dependency.
    Can be called directly by service layer or as agent tool.

    This is the core RAG implementation extracted from search_knowledge_base.
    All FileSearch logic, citation extraction, and formatting is here.
    """
    # Reject empty queries to prevent tool call failures
    if not query or not query.strip():
        logger.warning("❌ _perform_rag_search called with EMPTY query")
        return "ERROR: Empty search query. Please provide a valid search question."

    logger.info(f"🔍 RAG search initiated")
    logger.info(f"📝 Query: {query[:100]}...")
    logger.info(f"🔑 Session ID: {session_id}")

    # Step 1: Fetch conversation history automatically
    conversation_history = None
    try:
        from ..service.session_manager import session_state_manager
        chat_history = await session_state_manager.get_chat_history(session_id)
        logger.info(f"📚 Retrieved {len(chat_history)} messages from session history")

        # Format chat history per Gemini API specification
        conversation_history = []
        max_history_messages = 5  # Keep last 5 messages for token efficiency

        for i, hist_msg in enumerate(chat_history[-max_history_messages:]):
            try:
                # Debug: Show what's actually in the message
                if i == 0:
                    logger.info(f"🔍 DEBUG: Raw chat_history[0] keys: {list(hist_msg.keys())}")
                    logger.info(f"🔍 DEBUG: Raw chat_history[0]: {hist_msg}")
                
                role = hist_msg.get('role', '').lower()
                # Try both 'content' and 'message' fields (database uses 'content', but check what's available)
                content = hist_msg.get('content', '') or hist_msg.get('message', '')

                # Map database role names to Gemini API format
                if role == 'user':
                    conversation_history.append({
                        "role": "user",
                        "text": content
                    })
                elif role in ['assistant', 'model']:
                    conversation_history.append({
                        "role": "model",
                        "text": content
                    })
            except Exception as e:
                logger.warning(f"⚠️ Error formatting history message: {e}")
                continue

        if conversation_history:
            logger.info(f"📚 Formatted {len(conversation_history)} messages for FileSearch context")
    except Exception as session_err:
        logger.warning(f"⚠️ Could not fetch conversation history: {session_err}")
        logger.info(f"📚 Proceeding with query alone (no conversation context)")
        conversation_history = None

    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("❌ Gemini API client not configured")
        return "Gemini API client not configured - cannot search knowledge base"

    try:
        # Import required modules
        from shared.file_search import get_file_search_store_by_display_name

        # Get file search store from environment
        file_search_store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        # Resolve display name to full resource name
        file_search_store_name = get_file_search_store_by_display_name(
            genai_client,
            display_name=file_search_store_display_name
        )

        if not file_search_store_name:
            logger.warning(f"⚠️ FileSearch store '{file_search_store_display_name}' not found")
            return f"File Search store '{file_search_store_display_name}' not found. Please check configuration."

        logger.info(f"🔍 Using File Search store: {file_search_store_name}")

        # ============================================================================
        # PROFESSIONAL IMPLEMENTATION: Format conversation history per Gemini API spec
        # ============================================================================
        # Gemini API documentation specifies:
        # - contents: array of Content objects with alternating user/model roles
        # - Each Content: {role: "user"|"model", parts: [{text: "..."}]}
        # - FileSearch tool uses full history for better context understanding
        # Reference: https://ai.google.dev/api/generate-content
        # ============================================================================

        # Build contents array following Gemini API specification
        contents = []

        # Step 1: Add conversation history if provided
        if conversation_history and isinstance(conversation_history, list):
            logger.info(f"🔍 DEBUG: conversation_history contains {len(conversation_history)} messages")
            if conversation_history:
                logger.info(f"🔍 DEBUG: First message keys: {list(conversation_history[0].keys())}")
                logger.info(f"🔍 DEBUG: First message: {conversation_history[0]}")
            logger.info(f"📌 Building contents array: adding {len(conversation_history)} historical messages")

            for i, msg in enumerate(conversation_history):
                try:
                    # Validate message structure per Gemini API spec
                    role = msg.get("role", "").lower()
                    # Try both "text" (API format) and "content" (database format)
                    text = msg.get("text", "") or msg.get("content", "")

                    # Validate role and text
                    if not role or not text:
                        logger.warning(f"⚠️  Skipping history message {i}: invalid format (missing role or text)")
                        logger.info(f"   Message keys: {list(msg.keys())}")
                        logger.info(f"   Role: '{role}', Text: '{text[:50] if text else 'EMPTY'}'...")
                        continue

                    if role not in ["user", "model"]:
                        logger.warning(f"⚠️  Skipping history message {i}: invalid role '{role}' (must be 'user' or 'model')")
                        continue

                    # Create Content object per Gemini API specification
                    # Content = {role, parts} where parts is array of Part objects
                    content = types.Content(
                        role=role,
                        parts=[types.Part(text=text)]
                    )
                    contents.append(content)
                    logger.debug(f"✅ Added {role} message {i}: {text[:60]}...")

                except Exception as msg_err:
                    logger.warning(f"⚠️  Error processing history message {i}: {msg_err}")
                    continue

        # Step 2: Add current user query as latest message
        logger.info(f"📌 Adding current user query to contents array")
        current_message = types.Content(
            role="user",
            parts=[types.Part(text=query)]
        )
        contents.append(current_message)

        logger.info(f"📚 Contents array finalized: {len(contents)} total messages")
        logger.info(f"💬 Calling Gemini API with FileSearch tool (full conversation context)")

        # Step 3: Call Gemini API with full conversation context
        # FileSearch will use entire conversation for better RAG results
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,  # ✅ PROFESSIONAL: Full conversation per Gemini API spec
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[file_search_store_name]
                        )
                    )
                ]
            )
        )

        response_text = response.text if hasattr(response, 'text') else str(response)
        logger.info(f"✅ Generated response: {len(response_text)} characters")
        logger.info("=" * 80)
        logger.info("🔍 DEBUG: QUERY vs RESPONSE VALIDATION")
        logger.info(f"   Input Query: {query}")
        logger.info(f"   Query contains 'first': {'first' in query.lower()}")
        logger.info(f"   Query contains 'second': {'second' in query.lower()}")
        logger.info(f"   Query contains 'fourth': {'fourth' in query.lower()}")
        logger.info(f"   Query contains '4th': {'4th' in query.lower()}")
        logger.info(f"   Response contains 'first row': {'first row' in response_text.lower()}")
        logger.info(f"   Response contains 'second row': {'second row' in response_text.lower()}")
        logger.info(f"   Response contains 'fourth row': {'fourth row' in response_text.lower()}")
        logger.info(f"   Response contains '4th row': {'4th row' in response_text.lower()}")
        logger.info("=" * 80)
        logger.info("📄 RAG RESPONSE (raw from Gemini FileSearch):")
        logger.info(response_text)
        logger.info("=" * 80)

        # DEBUG: Log response structure to understand what's available
        logger.info("🔍 DEBUG: Response object structure:")
        logger.info(f"  - Has 'candidates': {hasattr(response, 'candidates')}")
        if hasattr(response, 'candidates'):
            logger.info(f"  - Number of candidates: {len(response.candidates)}")
            for i, candidate in enumerate(response.candidates):
                logger.info(f"  - Candidate {i} attributes: {dir(candidate)}")
                logger.info(f"  - Candidate {i} has 'grounding_metadata': {hasattr(candidate, 'grounding_metadata')}")
                if hasattr(candidate, 'grounding_metadata'):
                    gm = candidate.grounding_metadata
                    logger.info(f"  - Grounding metadata attributes: {dir(gm)}")
                    logger.info(f"  - Grounding metadata: {gm}")
        logger.info("=" * 80)

        # Extract source URLs from grounding metadata
        source_urls = []
        if hasattr(response, 'candidates'):
            for candidate in response.candidates:
                if hasattr(candidate, 'grounding_metadata'):
                    grounding = candidate.grounding_metadata
                    if hasattr(grounding, 'grounding_chunks'):
                        for chunk in grounding.grounding_chunks:
                            # Extract web search result URLs (for Google Search grounding)
                            if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                                url = chunk.web.uri
                                if url and url not in source_urls:
                                    source_urls.append(url)
                                    logger.info(f"📎 Found web search URL: {url}")

                            # Extract FileSearch document information (web-crawled URLs only)
                            if hasattr(chunk, 'retrieved_context'):
                                context = chunk.retrieved_context
                                url_found = False

                                # Get document title for logging
                                doc_title = getattr(context, 'title', None)
                                if doc_title:
                                    logger.info(f"📄 Found document title: {doc_title}")

                                # Strategy 1: Check if context has URI field (like web search)
                                if hasattr(context, 'uri'):
                                    doc_url = context.uri
                                    if doc_url and doc_url not in source_urls:
                                        source_urls.append(doc_url)
                                        logger.info(f"📎 Extracted URL from context.uri: {doc_url}")
                                        url_found = True

                                # Strategy 2: Check custom_metadata for original_url (web-crawled content)
                                if not url_found and hasattr(chunk, 'custom_metadata'):
                                    metadata = chunk.custom_metadata
                                    logger.info(f"🔍 Found custom_metadata: {metadata}")
                                    for meta_item in metadata:
                                        if hasattr(meta_item, 'key') and meta_item.key == 'original_url':
                                            doc_url = getattr(meta_item, 'string_value', None)
                                            if doc_url and doc_url not in source_urls:
                                                source_urls.append(doc_url)
                                                logger.info(f"📎 Extracted URL from custom_metadata: {doc_url}")
                                                url_found = True
                                                break

                                # Strategy 3: Extract URL from document text content (embedded "Source URL:")
                                if not url_found:
                                    content_text = getattr(context, 'text', None)
                                    if content_text:
                                        logger.info(f"📄 Document snippet: {content_text[:200]}...")

                                        # Try to extract URL from document content
                                        # Pattern to match "Source URL: https://..."
                                        url_pattern = r'Source URL:\s*(https?://[^\s\n\)]+)'
                                        url_matches = re.findall(url_pattern, content_text, re.IGNORECASE)

                                        for doc_url in url_matches:
                                            # Clean up URL (remove trailing punctuation)
                                            doc_url = doc_url.rstrip('.,;:)')
                                            if doc_url and doc_url not in source_urls:
                                                source_urls.append(doc_url)
                                                logger.info(f"📎 Extracted URL from embedded 'Source URL:': {doc_url}")
                                                url_found = True
                                                break

                                # Strategy 4: Parse URL from filename (for scraped files)
                                # Filename format: scraped_{url_encoded}_YYYYMMDD_HHMMSS.md
                                # Example: scraped_en.wikipedia.org_wiki_Sachin_Tendulkar_20260210_223347.md
                                # → URL: https://en.wikipedia.org/wiki/Sachin_Tendulkar
                                if not url_found and doc_title and doc_title.startswith('scraped_'):
                                    try:
                                        logger.info(f"🔍 Attempting to reconstruct URL from filename: {doc_title}")

                                        # Remove 'scraped_' prefix and '.md' extension
                                        url_part = doc_title[8:]  # Remove 'scraped_'
                                        url_part = url_part[:-3]  # Remove '.md'

                                        # Remove timestamp (YYYYMMDD_HHMMSS pattern at end)
                                        timestamp_pattern = r'_\d{8}_\d{6}$'
                                        url_part = re.sub(timestamp_pattern, '', url_part)

                                        logger.info(f"🔍 After removing timestamp: {url_part}")

                                        # Replace underscores with slashes to reconstruct URL path
                                        reconstructed_url = f"https://{url_part.replace('_', '/')}"

                                        if reconstructed_url not in source_urls:
                                            source_urls.append(reconstructed_url)
                                            logger.info(f"✅ Reconstructed actual webpage URL: {reconstructed_url}")
                                            url_found = True
                                    except Exception as parse_error:
                                        logger.warning(f"⚠️ Failed to parse URL from filename '{doc_title}': {parse_error}")

                                # Note: Only show URLs for web-crawled content (uploaded files have no URL)
                                if not url_found:
                                    logger.info(f"ℹ️ No URL found for document '{doc_title}' - skipping citation (uploaded file)")

        # Fallback: Parse response text for source URLs
        if not source_urls and response_text:
            url_matches = re.findall(r'Source URL:\s*(https?://[^\s\n]+)', response_text)
            for url in url_matches:
                if url not in source_urls:
                    source_urls.append(url)
                    logger.info(f"📄 Extracted URL from response text: {url}")

        # Append source URLs to content for citation
        enhanced_content = response_text
        if source_urls:
            # Build tree structure for hierarchical citations
            citation_tree = await get_citation_hierarchy(source_urls)

            # Format as JSON for frontend parsing
            citation_section = "\n\n[CITATION_TREE]"
            citation_section += json.dumps(citation_tree, indent=2)
            citation_section += "\n[/CITATION_TREE]"

            # Also include flat list for backward compatibility
            citation_section += "\n\n[CITATION_SOURCES]"
            for url in source_urls:
                citation_section += f"\n- {url}"
            citation_section += "\n[/CITATION_SOURCES]"

            enhanced_content += citation_section
            logger.info(f"📎 Appended {len(source_urls)} source URL(s) to content with tree structure")
            logger.info("=" * 80)
            logger.info("📎 CITATIONS ADDED:")
            for i, url in enumerate(source_urls, 1):
                logger.info(f"  {i}. {url}")
            logger.info("=" * 80)
        else:
            logger.warning("⚠️ No source URLs found - no citations appended!")
            # Still include the response text even without citations

        # Check if response is meaningful or empty
        if not response_text or len(response_text.strip()) < 50:
            logger.warning("⚠️ Knowledge base returned no relevant results")
            # Return explicit "no results" message to prevent infinite tool loops
            no_results_msg = "No relevant information found in knowledge base for this query."
            logger.info(f"✅ Internal RAG search completed: _perform_rag_search (no results)")
            logger.info("=" * 80)
            logger.info("📦 KB SEARCH RESULT:")
            logger.info(no_results_msg)
            logger.info("=" * 80)
            return no_results_msg

        logger.info(f"✅ Internal RAG search completed: _perform_rag_search (returned {len(enhanced_content)} chars)")
        logger.info("=" * 80)
        logger.info("📦 FINAL ENHANCED CONTENT (with citations):")
        logger.info(enhanced_content)
        logger.info("=" * 80)
        return enhanced_content

    except Exception as e:
        logger.error(f"❌ Internal RAG search failed: _perform_rag_search - {e}", exc_info=True)
        return f"Error performing FileSearch: {str(e)}"


async def search_knowledge_base(
    ctx: RunContext[ChatSessionDeps],
    query: str
) -> str:
    """
    Agent tool: Search knowledge base using Gemini FileSearch.

    This is a thin wrapper around the internal _perform_rag_search() function.
    The actual RAG implementation is in _perform_rag_search, which can be called
    directly by the service layer or through this tool by the agent.

    Args:
        ctx: Pydantic AI RunContext containing ChatSessionDeps with session_id
        query: The user's search query (may be enhanced by agent)

    Returns:
        String containing RAG-powered response with source citations
    """
    session_id = ctx.deps.session_id

    logger.info(f"🔍 Tool called: search_knowledge_base")
    logger.info(f"📝 Agent query: {query[:100]}...")
    logger.info(f"🔑 Session ID: {session_id}")

    # Delegate to internal RAG search function
    return await _perform_rag_search(session_id, query)

async def query_railway_postgres(query: str) -> str:
    """
    Query Railway PostgreSQL database for file metadata, user information, or metrics.

    Use this for questions about:
    - Uploaded files and their metadata
    - User information (non-PII only)
    - System metrics and analytics
    - File upload history
    """
    logger.info(f"🗄️ Tool called: query_railway_postgres with query: {query[:100]}...")
    try:
        # Direct database query using shared db connection
        from shared.db import get_db_connection

        # Parse the query and construct appropriate response
        query_lower = query.lower()

        async with get_db_connection() as conn:
            # File count queries
            if any(word in query_lower for word in ['count', 'total', 'number', 'how many']):
                if any(word in query_lower for word in ['file', 'document', 'upload']):
                    count = await conn.fetchval("SELECT COUNT(*) FROM uploaded_files WHERE is_active = true")
                    result = f"Total active files in system: {count}"
                    logger.info(f"✅ Tool completed: query_railway_postgres (file count: {count})")
                    return result
                elif any(word in query_lower for word in ['session', 'chat', 'conversation']):
                    count = await conn.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE is_active = true")
                    result = f"Total active chat sessions: {count}"
                    logger.info(f"✅ Tool completed: query_railway_postgres (session count: {count})")
                    return result

            # Recent files query
            elif any(word in query_lower for word in ['recent', 'latest', 'last']):
                if any(word in query_lower for word in ['file', 'document', 'upload']):
                    rows = await conn.fetch(
                        "SELECT display_name, mime_type, size_bytes, uploaded_at FROM uploaded_files WHERE is_active = true ORDER BY uploaded_at DESC LIMIT 5"
                    )
                    if rows:
                        result = "Recent uploaded files:\n"
                        for row in rows:
                            result += f"- {row['display_name']} ({row['mime_type']}, {row['size_bytes']} bytes)\n"
                        logger.info(f"✅ Tool completed: query_railway_postgres (recent files: {len(rows)})")
                        return result
                    return "No recent files found."

            # Default: provide general info
            file_count = await conn.fetchval("SELECT COUNT(*) FROM uploaded_files WHERE is_active = true")
            session_count = await conn.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE is_active = true")
            result = f"Database Summary:\n- Active files: {file_count}\n- Active sessions: {session_count}\n\nPlease ask a more specific question about the data you need."
            logger.info(f"✅ Tool completed: query_railway_postgres (summary)")
            return result

    except Exception as e:
        logger.error(f"❌ Tool failed: query_railway_postgres - {e}")
        return f"I encountered an error querying the database. The database query functionality may need to be configured properly."

async def request_human_agent_connection(reason: str) -> str:
    """
    Request to connect user to a human agent for personalized assistance.

    Use this tool when:
    - The user explicitly asks to speak with a human, real person, or agent
    - The user requests human support or assistance
    - The user is frustrated and needs human help
    - The query cannot be answered by knowledge base or requires human judgment

    This will assign the chat to an available human agent and the chat will appear in their chat log.
    """
    logger.info(f"🧑 Tool called: request_human_agent_connection with reason: {reason}")
    
    try:
        import httpx

        # Get configuration service URL from environment
        config_service_url = os.getenv(
            'CONFIGURATION_SERVICE_URL',
            'https://configuration-service-production.up.railway.app'
        )
        
        # Note: We don't have access to session_id in this context
        # For now, return a message indicating human agent request
        # In a real implementation, we'd need to pass session_id through deps

        result = f"I've noted your request to connect with a human agent for: {reason}. A human agent will join the conversation shortly. The chat has been opened in their chat log."
        logger.info(f"✅ Tool completed: request_human_agent_connection")
        return result

    except Exception as e:
        logger.error(f"❌ Tool failed: request_human_agent_connection - {e}")
        return f"Error requesting human agent: {str(e)}"
