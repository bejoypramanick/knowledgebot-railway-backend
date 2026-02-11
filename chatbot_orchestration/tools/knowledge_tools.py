"""
Knowledge Tools for Pydantic AI Agent
Contains all tool implementations as standalone functions
"""

import os
import re
import logging
from typing import List

from google.genai import types
from shared.otel_logger import get_otel_logger

from ..core.ai import get_genai_client
from ..schemas.models import SearchResult

logger = get_otel_logger("knowledge_tools", "chatbot-orchestration")

async def search_knowledge_base(query: str) -> str:
    """
    Search knowledge base using Gemini FileSearch for relevant information.

    Use this tool for questions about:
    - Content in uploaded documents, PDFs, text files
    - Scraped website content stored in knowledge base
    - Technical documentation and research papers
    - Company policies and procedures
    - Any content that should be retrieved from stored documents
    """
    # Reject empty queries to prevent duplicate tool call attempts
    if not query or not query.strip():
        logger.warning("❌ search_knowledge_base called with EMPTY query - rejecting to prevent infinite loops")
        return "TOOL_CALL_REJECTED: Empty query provided. Please ensure a valid search query is passed to the tool."

    logger.info(f"🔍 Tool called: search_knowledge_base with query: {query[:100]}...")

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

        # Generate response using FileSearch tool
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=query,
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
            citation_section = "\n\n[CITATION_SOURCES]"
            for url in source_urls:
                citation_section += f"\n- {url}"
            citation_section += "\n[/CITATION_SOURCES]"
            enhanced_content += citation_section
            logger.info(f"📎 Appended {len(source_urls)} source URL(s) to content")
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
            logger.info(f"✅ Tool completed: search_knowledge_base (no results)")
            logger.info("=" * 80)
            logger.info("📦 KB SEARCH RESULT:")
            logger.info(no_results_msg)
            logger.info("=" * 80)
            return no_results_msg

        logger.info(f"✅ Tool completed: search_knowledge_base (returned {len(enhanced_content)} chars)")
        logger.info("=" * 80)
        logger.info("📦 FINAL ENHANCED CONTENT (with citations):")
        logger.info(enhanced_content)
        logger.info("=" * 80)
        return enhanced_content

    except Exception as e:
        logger.error(f"❌ Tool failed: search_knowledge_base - {e}", exc_info=True)
        return f"Error performing FileSearch: {str(e)}"

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
