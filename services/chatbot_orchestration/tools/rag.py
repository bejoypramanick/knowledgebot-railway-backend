import logging
import uuid
from typing import List, Annotated

from google.genai import types

from ..core.ai import get_genai_client, gemini_model
from ..schemas.models import SearchResult
from shared.token_tracker import track_gemini_usage_from_response

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
            content="Gemini API client not configured - cannot search knowledge base",
            relevance_score=0.0,
            similarity_score=0.0,
            element_type="error",
            hierarchy_level=0,
            page_number=0
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
                content=f"Error creating cached content: {str(cache_error)}",
                relevance_score=0.1,
                similarity_score=0.1,
                chunk_id=f"error_{uuid.uuid4().hex[:16]}",
                element_type="error",
                hierarchy_level=0,
                page_number=0,
                metadata={
                    "error_type": "cache_creation_failed",
                    "error_message": str(cache_error)
                }
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
            
            # Track token usage
            try:
                await track_gemini_usage_from_response(response, session_id=None, message_id=None, api_call_type='rag')
            except Exception as track_error:
                logger.warning(f"⚠️ Failed to track token usage: {track_error}")
            
            return [SearchResult(
                file_name="RAG_Response",
                content=response_text,
                relevance_score=0.9,
                similarity_score=0.9,
                chunk_id=f"rag_{uuid.uuid4().hex[:16]}",
                element_type="text",
                hierarchy_level=0,
                page_number=0,
                metadata={
                    "source": "gemini_filesearch",
                    "query": query,
                    "response_length": len(response_text)
                }
            )]
            
        except Exception as generation_error:
            logger.error(f"❌ Failed to generate response: {generation_error}")
            return [SearchResult(
                file_name="System_Error",
                content=f"Error generating response: {str(generation_error)}",
                relevance_score=0.1,
                similarity_score=0.1,
                chunk_id=f"error_{uuid.uuid4().hex[:16]}",
                element_type="error",
                hierarchy_level=0,
                page_number=0,
                metadata={
                    "error_type": "generation_failed",
                    "error_message": str(generation_error)
                }
            )]
            
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}", exc_info=True)
        return [SearchResult(
            file_name="System_Error",
            content=f"Error performing semantic search: {str(e)}",
            relevance_score=0.1,
            similarity_score=0.1,
            chunk_id=f"error_{uuid.uuid4().hex[:16]}",
            element_type="error",
            hierarchy_level=0,
            page_number=0,
            metadata={
                "error_type": "search_failed",
                "error_message": str(e)
            }
        )]
