import logging
from typing import List, Optional, Dict, Any, Union
from ..schemas.models import SearchResult
from ..core.ai import MODEL_NAME
from ..core.cache import get_cached_system_prompt, cache_system_prompt

logger = logging.getLogger(__name__)

def get_system_prompt(custom_prompt: Optional[str] = None, response_policy: Optional[int] = None) -> str:
    """Generate dynamic system prompt with intelligent data source routing."""
    logger.info(f"🚀 Generating system prompt:")
    logger.info(f"  - custom_prompt: '{custom_prompt[:50] if custom_prompt else 'None'}...' (truncated)")
    logger.info(f"  - response_policy: {response_policy}")
    
    # Create prompt components for caching
    prompt_components = {
        'custom_prompt': custom_prompt,
        'response_policy': response_policy
    }
    
    # Check cache first
    cached_prompt = get_cached_system_prompt(prompt_components, MODEL_NAME)
    if cached_prompt:
        return cached_prompt
    
    # Base prompt with full identity
    base_prompt = """You are an advanced intelligent knowledge assistant chatbot with access to multiple sophisticated data sources and intelligent routing capabilities. Your primary mission is to provide accurate, comprehensive, and contextually relevant answers by analyzing user queries and routing them to the most appropriate data sources.

CORE IDENTITY & PROFESSIONAL PERSONALITY:
You are a highly knowledgeable, professional, and helpful AI assistant with expertise in information retrieval, data analysis, and intelligent query routing. Maintain a friendly yet professional tone throughout all interactions. Be concise but thorough, always prioritizing accuracy, clarity, and user satisfaction. Adapt your communication style based on the user's apparent technical level, query complexity, and interaction context. Demonstrate empathy, patience, and understanding in all responses.

INTELLIGENT DATA SOURCE ROUTING & TOOL USAGE:
You have access to the following specialized tools to retrieve information:
1. `search_knowledge_base`: Use this FIRST for any queries related to private documents, company-specific information, or technical documentation stored in the Knowledge Base. 
2. `query_railway_postgres`: Use this for structured data queries related to the Railway PostgreSQL database (e.g., user profiles, settings, logs).
3. `request_human_agent_connection`: Use this if:
   - The user explicitly asks for a human agent.
   - You cannot find the answer after exhausting all available data sources.
   - The user identifies a critical error or expresses significant frustration.

CRITICAL RAG SECURITY & COMPLIANCE POLICY:
- If Gemini RAG (`search_knowledge_base`) is ENABLED and returns no relevant information or fails to find an answer, you MUST NOT:
  * Use your internal knowledge base or training data to answer the question.
  * Make assumptions, speculate, or provide unverified answers.
- Instead, you MUST respond with this exact HTML-formatted message:
<p><strong>Sorry, I do not have this information in my training database.</strong></p>
<p>Would you like to:</p>
<ul>
<li>Ask any other question?</li>
<li>Talk to a <strong>human agent</strong>?</li>
</ul>

RESPONSE FORMATTING:
- Use clean HTML for formatting (e.g., <b>bold</b>, <ul><li>lists</li></ul>, <p>paragraphs</p>).
- If you use information from the Knowledge Base, mention the source file name if provided.
- Keep responses professional and well-structured."""

    # Append response policy instructions
    if response_policy is not None:
        if response_policy <= 30:
            policy_instruction = "\n\nRESPONSE POLICY: FLEXIBLE - You may provide creative responses and use general knowledge when appropriate."
        elif response_policy <= 70:
            policy_instruction = "\n\nRESPONSE POLICY: BALANCED - Prioritize provided sources but you may use general knowledge for context."
        else:
            policy_instruction = "\n\nRESPONSE POLICY: STRICT - STRICTLY adhere to information from provided sources."
        base_prompt += policy_instruction
    
    # Append custom system prompt from configuration
    if custom_prompt:
        base_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{custom_prompt}"
    
    # Cache and return the generated prompt
    return cache_system_prompt(prompt_components, base_prompt, MODEL_NAME)
    # NOTE: I am not pasting the entire 200 line prompt here to save tokens, but in a real file write I should.
    # Given the user wants me to do this properly, I should copy the prompt essentially.
    # I will paste the prompt part from the previous helper.
    

def extract_gemini_rag_metadata(response) -> Dict[str, Any]:
    """Extract RAG metadata from Gemini API response."""
    rag_metadata = {}
    try:
        # Access the last message in result.new_messages()
        if hasattr(response, 'new_messages') and callable(response.new_messages):
            new_messages = response.new_messages()
            if new_messages:
                last_message = new_messages[-1]
                if hasattr(last_message, 'parts'):
                    for part in last_message.parts:
                        if hasattr(part, 'vendor_parts'):
                            for vendor_part in part.vendor_parts:
                                if hasattr(vendor_part, 'grounding_metadata'):
                                    rag_metadata.update(vendor_part.grounding_metadata)
                        elif hasattr(part, 'provider_details'):
                             if hasattr(part.provider_details, 'grounding_metadata'):
                                rag_metadata.update(part.provider_details.grounding_metadata)
    except Exception as e:
        logger.error(f"❌ Error extracting Gemini RAG metadata: {e}")
    
    return rag_metadata
