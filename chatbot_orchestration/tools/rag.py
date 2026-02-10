import os
import logging
from typing import Annotated, List

from google.genai import types

from ..core.ai import get_genai_client
from ..schemas.models import SearchResult

logger = logging.getLogger(__name__)

async def search_knowledge_base(query: Annotated[str, "The search query to find relevant information in uploaded documents"]) -> List[SearchResult]:
    """
    Search the knowledge base using Gemini FileSearch for relevant information.
    
    Correct implementation using FileSearch tool instead of cached_content.
    """
    logger.info(f"🔍 Searching Gemini FileStore for query: {query[:100]}...")
    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("❌ Gemini API client not configured")
        return [SearchResult(
            file_name="System_Error",
            content="Gemini API client not configured - cannot search knowledge base"
        )]

    try:
        # Get the file search store from environment
        file_search_store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        # Resolve display name to full resource name
        from shared.file_search import get_file_search_store_by_display_name

        file_search_store_name = get_file_search_store_by_display_name(
            genai_client,
            display_name=file_search_store_display_name
        )

        if not file_search_store_name:
            logger.warning(f"⚠️ FileSearch store '{file_search_store_display_name}' not found")
            return [SearchResult(
                file_name="RAG_Response",
                content=f"File Search store '{file_search_store_display_name}' not found. Please check configuration."
            )]

        logger.info(f"🔍 Using File Search store: {file_search_store_name}")

        # Generate response using FileSearch tool (CORRECT WAY)
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

        # Log response text preview to check for Source URL
        logger.info(f"📄 Response text preview (first 500 chars):")
        logger.info(f"{response_text[:500]}")

        # Check if response contains "Source URL:"
        if "Source URL:" in response_text:
            logger.info(f"✅ Response text CONTAINS 'Source URL:' - will extract")
        else:
            logger.warning(f"⚠️ Response text DOES NOT contain 'Source URL:' - no citations to extract")

        # Extract metadata from Gemini response
        logger.info("="*80)
        logger.info("🔍 STARTING CITATION EXTRACTION")
        logger.info("="*80)
        metadata = {}
        source_urls = []  # Collect source URLs for the chatbot to reference
        document_source_urls = []  # URLs from scraped documents

        if hasattr(response, 'candidates'):
            metadata['candidates_count'] = len(response.candidates)

            # Extract source URLs from grounding metadata
            for candidate in response.candidates:
                if hasattr(candidate, 'grounding_metadata'):
                    grounding = candidate.grounding_metadata

                    # Check for grounding_chunks which contain source information
                    if hasattr(grounding, 'grounding_chunks'):
                        logger.info(f"🔍 Found {len(grounding.grounding_chunks)} grounding chunks")
                        for idx, chunk in enumerate(grounding.grounding_chunks):
                            logger.info(f"   Chunk [{idx+1}] type: {type(chunk).__name__}")
                            # Extract web search result URLs (from Google Search)
                            if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                                url = chunk.web.uri
                                if url and url not in source_urls:
                                    source_urls.append(url)
                                    logger.info(f"📎 Found web search URL: {url}")

                            # Extract URLs from scraped documents in FileSearch
                            # Check if chunk has retrieved_context (FileSearch document content)
                            if hasattr(chunk, 'retrieved_context'):
                                context = chunk.retrieved_context
                                logger.info(f"   ✓ Chunk has retrieved_context")
                                # Try to extract "Source URL: ..." from document content
                                if hasattr(context, 'text') or hasattr(context, 'content'):
                                    content_text = getattr(context, 'text', None) or getattr(context, 'content', None)
                                    if content_text:
                                        logger.info(f"   ✓ Context has content: {len(content_text)} chars")
                                        logger.info(f"   📄 Context preview (first 200 chars): {content_text[:200]}")
                                        import re
                                        # Match "Source URL: http(s)://..."
                                        url_match = re.search(r'Source URL:\s*(https?://[^\s\n]+)', content_text)
                                        if url_match:
                                            doc_url = url_match.group(1)
                                            if doc_url and doc_url not in document_source_urls:
                                                document_source_urls.append(doc_url)
                                                logger.info(f"📄 ✅ Found document source URL: {doc_url}")
                                        else:
                                            logger.warning(f"   ⚠️ No 'Source URL:' pattern found in context")
                                    else:
                                        logger.warning(f"   ⚠️ Context text/content is empty")
                                else:
                                    logger.warning(f"   ⚠️ Context has no text or content attribute")
                            else:
                                logger.warning(f"   ⚠️ Chunk has no retrieved_context")

                    # Check for web_search_queries
                    if hasattr(grounding, 'web_search_queries'):
                        logger.info(f"🔍 Web search queries used: {grounding.web_search_queries}")

                    # Check for search_entry_point
                    if hasattr(grounding, 'search_entry_point') and hasattr(grounding.search_entry_point, 'rendered_content'):
                        logger.info(f"🌐 Search entry point available")

        if hasattr(response, 'prompt_feedback'):
            metadata['prompt_feedback'] = response.prompt_feedback
        if hasattr(response, 'usage_metadata'):
            metadata['usage_metadata'] = response.usage_metadata._asdict() if hasattr(response.usage_metadata, '_asdict') else str(response.usage_metadata)
        if hasattr(response, 'finish_reason'):
            metadata['finish_reason'] = response.finish_reason
        if hasattr(response, 'safety_ratings'):
            metadata['safety_ratings'] = [rating._asdict() if hasattr(rating, '_asdict') else str(rating) for rating in response.safety_ratings]

        # Fallback: Parse response text for "Source URL: ..." if not found in grounding chunks
        # This catches cases where FileSearch doesn't expose document content in grounding
        logger.info(f"🔍 Checking response text for 'Source URL:' pattern (fallback)")
        if not document_source_urls and response_text:
            import re
            url_matches = re.findall(r'Source URL:\s*(https?://[^\s\n]+)', response_text)
            if url_matches:
                logger.info(f"✅ Found {len(url_matches)} URL(s) in response text")
                for url in url_matches:
                    if url not in document_source_urls and url not in source_urls:
                        document_source_urls.append(url)
                        logger.info(f"📄 ✅ Extracted document URL from response text: {url}")
            else:
                logger.warning(f"⚠️ No 'Source URL:' pattern found in response text")
                logger.warning(f"⚠️ This means the FileSearch documents don't have source URLs")
        elif document_source_urls:
            logger.info(f"✅ Already found {len(document_source_urls)} URLs in grounding chunks, skipping response text parsing")

        # Combine all source URLs (web search + document sources)
        all_source_urls = source_urls + document_source_urls

        # Add source URLs to metadata for the chatbot to reference
        logger.info("="*80)
        logger.info("📊 CITATION EXTRACTION SUMMARY")
        logger.info("="*80)
        if all_source_urls:
            metadata['source_urls'] = all_source_urls
            logger.info(f"✅ Extracted {len(source_urls)} web search URL(s) and {len(document_source_urls)} document source URL(s)")
            logger.info(f"📚 Total sources: {len(all_source_urls)}")
            for i, url in enumerate(all_source_urls, 1):
                logger.info(f"   [{i}] {url}")
        else:
            logger.warning(f"❌ NO CITATIONS FOUND")
            logger.warning(f"   - Web search URLs: {len(source_urls)}")
            logger.warning(f"   - Document source URLs: {len(document_source_urls)}")
            logger.warning(f"   - Check if documents contain 'Source URL:' metadata")
        logger.info("="*80)

        # Add grounding metadata if available
        if hasattr(response, 'grounding_metadata'):
            metadata['grounding_metadata'] = response.grounding_metadata

        metadata['api_method'] = 'FileSearch tool (correct implementation)'

        # Append source URLs to content so model can easily cite them
        # Format them clearly so the model sees them
        enhanced_content = response_text
        if all_source_urls:
            citation_section = "\n\n[CITATION_SOURCES]"
            for url in all_source_urls:
                citation_section += f"\n- {url}"
            citation_section += "\n[/CITATION_SOURCES]"

            enhanced_content += citation_section

            logger.info(f"📎 Appended {len(all_source_urls)} source URL(s) to content for citation")
            logger.info(f"📋 Citation section added to response:")
            logger.info(f"{citation_section}")
            logger.info(f"📄 Full enhanced content length: {len(enhanced_content)} characters")
        else:
            logger.warning(f"⚠️ No source URLs found - citations will NOT be available")
            logger.warning(f"⚠️ Response text length: {len(response_text)} characters")

        return [SearchResult(
            file_name="RAG_Response",
            content=enhanced_content,
            metadata=metadata
        )]
        
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}", exc_info=True)
        return [SearchResult(
            file_name="System_Error",
            content=f"Error performing FileSearch: {str(e)}"
        )]
