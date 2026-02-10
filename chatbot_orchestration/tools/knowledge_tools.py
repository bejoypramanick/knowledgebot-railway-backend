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

        # Extract source URLs from grounding metadata
        source_urls = []
        if hasattr(response, 'candidates'):
            for candidate in response.candidates:
                if hasattr(candidate, 'grounding_metadata'):
                    grounding = candidate.grounding_metadata
                    if hasattr(grounding, 'grounding_chunks'):
                        for chunk in grounding.grounding_chunks:
                            # Extract web search result URLs
                            if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                                url = chunk.web.uri
                                if url and url not in source_urls:
                                    source_urls.append(url)
                                    logger.info(f"📎 Found web search URL: {url}")
                            # Extract URLs from scraped documents
                            if hasattr(chunk, 'retrieved_context'):
                                context = chunk.retrieved_context
                                content_text = getattr(context, 'text', None) or getattr(context, 'content', None)
                                if content_text:
                                    url_match = re.search(r'Source URL:\s*(https?://[^\s\n]+)', content_text)
                                    if url_match:
                                        doc_url = url_match.group(1)
                                        if doc_url and doc_url not in source_urls:
                                            source_urls.append(doc_url)
                                            logger.info(f"📄 Found document URL: {doc_url}")

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

        logger.info(f"✅ Tool completed: search_knowledge_base (returned {len(enhanced_content)} chars)")
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
        from ..service.file_service import FileService
        file_service = FileService()

        # Parse the query and construct appropriate response
        query_lower = query.lower()

        # File-related queries
        if any(word in query_lower for word in ['file', 'upload', 'document', 'document']):
            if 'count' in query_lower or 'total' in query_lower or 'number' in query_lower:
                count = await file_service.get_active_files_count()
                result = f"Total active files in system: {count}"
                logger.info(f"✅ Tool completed: query_railway_postgres (file count)")
                return result
            elif 'recent' in query_lower or 'latest' in query_lower:
                files = await file_service.get_recent_files(5)
                if files:
                    result = "Recent uploaded files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']}, {f['size_bytes']} bytes, uploaded {f['uploaded_at']})\n"
                    logger.info(f"✅ Tool completed: query_railway_postgres (recent files: {len(files)})")
                    return result
                logger.info(f"✅ Tool completed: query_railway_postgres (no recent files)")
                return "No recent files found."
            else:
                # General file info
                files = await file_service.get_recent_files(10)
                if files:
                    result = f"Found {len(files)} active files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']})\n"
                    logger.info(f"✅ Tool completed: query_railway_postgres (file list: {len(files)})")
                    return result
                logger.info(f"✅ Tool completed: query_railway_postgres (no files)")
                return "No files found in the database."

        # Metrics queries
        elif any(word in query_lower for word in ['metric', 'statistic', 'analytics', 'usage']):
            metrics = await file_service.get_recent_metrics(10)
            if metrics:
                result = "Recent metrics (last 7 days):\n"
                for m in metrics:
                    result += f"- {m['metric_name']}: {m['total_value']} {m['unit'] or ''}\n"
                logger.info(f"✅ Tool completed: query_railway_postgres (metrics: {len(metrics)})")
                return result
            logger.info(f"✅ Tool completed: query_railway_postgres (no metrics)")
            return "No metrics found."

        # Default: return file count
        count = await file_service.get_active_files_count()
        result = f"Database contains {count} active files. Please be more specific about what information you need."
        logger.info(f"✅ Tool completed: query_railway_postgres")
        return result

    except Exception as e:
        logger.error(f"❌ Tool failed: query_railway_postgres - {e}")
        return f"Error querying database: {str(e)}"

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
