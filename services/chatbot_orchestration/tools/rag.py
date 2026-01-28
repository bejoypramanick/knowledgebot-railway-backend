import logging
import uuid
from typing import List, Annotated

from google.genai import types

from ..core.ai import get_genai_client, gemini_model
from ..schemas.models import SearchResult

logger = logging.getLogger(__name__)

async def search_knowledge_base(query: Annotated[str, "The search query to find relevant information in uploaded documents"]) -> List[SearchResult]:
    """
    Search the knowledge base using Gemini FileSearch for relevant information.
    
    Simple implementation: Just query Gemini FileStore and return the answer.
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
        # Create a simple retrieval prompt for Gemini
        retrieval_prompt = f"""
        Based on the user's query, provide relevant information from the available documents.
        
        User Query: "{query}"
        
        Instructions:
        1. Search through all available documents to find relevant information.
        2. Provide helpful, factual information based on the documents.
        3. If no relevant information is found, indicate that clearly.
        4. Keep your response concise and focused on answering the query.
        """
        
        # Create cached content for RAG search
        logger.info("🧠 Creating cached content for RAG search...")
        try:
            cached_content = genai_client.cached_content.create(
                model=gemini_model,
                contents=[retrieval_prompt]
                # Gemini will automatically search all available files
            )
            logger.info("✅ Cached content created successfully")
        except Exception as cache_error:
            logger.error(f"❌ Failed to create cached content: {cache_error}")
            return [SearchResult(
                file_name="System_Error",
                content=f"Error creating cached content: {str(cache_error)}"
            )]
        
        # Generate response using the cached content
        try:
            logger.info("🤖 Generating response using cached content...")
            response = cached_content.generate_content(
                model=gemini_model,
                contents=[query]
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
            
            # Note: Gemini doesn't provide similarity_score or relevance_score
            # These would need to be calculated by the application if needed
            metadata['note'] = "Gemini API provides usage metadata, not similarity scores"
            
            return [SearchResult(
                file_name="RAG_Response",
                content=response_text,
                # Only real metadata from Gemini API
                metadata=metadata
            )]
            
        except Exception as generation_error:
            logger.error(f"❌ Failed to generate response: {generation_error}")
            return [SearchResult(
                file_name="System_Error",
                content=f"Error generating response: {str(generation_error)}"
            )]
            
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}", exc_info=True)
        return [SearchResult(
            file_name="System_Error",
            content=f"Error performing semantic search: {str(e)}"
        )]
