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
        
        # Extract metadata from Gemini response
        metadata = {}
        if hasattr(response, 'candidates'):
            metadata['candidates_count'] = len(response.candidates)
        if hasattr(response, 'prompt_feedback'):
            metadata['prompt_feedback'] = response.prompt_feedback
        if hasattr(response, 'usage_metadata'):
            metadata['usage_metadata'] = response.usage_metadata._asdict() if hasattr(response.usage_metadata, '_asdict') else str(response.usage_metadata)
        if hasattr(response, 'finish_reason'):
            metadata['finish_reason'] = response.finish_reason
        if hasattr(response, 'safety_ratings'):
            metadata['safety_ratings'] = [rating._asdict() if hasattr(rating, '_asdict') else str(rating) for rating in response.safety_ratings]
        
        # Add citation metadata if available
        if hasattr(response, 'grounding_metadata'):
            metadata['grounding_metadata'] = response.grounding_metadata
        
        metadata['api_method'] = 'FileSearch tool (correct implementation)'
        
        return [SearchResult(
            file_name="RAG_Response",
            content=response_text,
            metadata=metadata
        )]
        
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}", exc_info=True)
        return [SearchResult(
            file_name="System_Error",
            content=f"Error performing FileSearch: {str(e)}"
        )]
