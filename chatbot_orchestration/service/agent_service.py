import time
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from google.genai import types
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

from chatbot_orchestration.dao.chat_dao import ChatDAO
from chatbot_orchestration.core.otel_logger import get_otel_logger

from ..core.ai import MODEL_NAME, get_genai_client
from ..core.dependencies import ChatSessionDeps

logger = get_otel_logger("agent_service", "chatbot-orchestration")

class PydanticAIGatewayService:
    """ Service class for Pydantic AI integration with Gemini FileSearch """
    
    def __init__(self):
        self.genai_client = None
        self.chat_dao = ChatDAO()  # Unified ChatDAO for all chat operations
        
    async def initialize(self):
        if not self.genai_client:
            self.genai_client = get_genai_client()
    
    async def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        logger.info(f"🔍 Retrieving session metadata for session: {session_id}")
        
        try:
            session_data = await self.chat_dao.get_session_metadata(session_id)
            
            if not session_data:
                return {'session_id': session_id, 'is_new_session': True}
            
            return {
                'session_id': session_id,
                'file_search_store_id': session_data['file_search_store_id'],
                'cached_content_id': session_data['cached_content_id'],
                'is_new_session': False
            }
        except Exception as e:
            logger.error(f"❌ Error retrieving session metadata: {e}")
            return {'session_id': session_id, 'is_new_session': True}

    async def get_or_create_file_search_store(self, session_id: str) -> str:
        if not self.genai_client:
            raise ValueError("GenAI client not initialized")
        
        try:
            if hasattr(self.genai_client, 'stores'):
                stores = list(self.genai_client.stores.list())
                app_store = None
                for store in stores:
                    if hasattr(store, 'display_name') and 'knowledgebot_file_search' in store.display_name.lower():
                        app_store = store
                        break
                
                if app_store:
                    return app_store.name
                else:
                    # Create new store using correct Python client API
                    new_store = self.genai_client.stores.create(
                        displayName="KnowledgeBot FileSearch Store"
                    )
                    logger.info(f"Created FileSearch store: {new_store.name}")
                    return new_store.name
            else:
                return f"knowledgebot_store_{session_id[:8]}"
        except Exception as e:
            logger.error(f"❌ Error managing FileSearchStore: {e}")
            return f"knowledgebot_store_{session_id[:8]}"

    async def get_or_create_cached_content(self, system_prompt: str) -> str:
        if not self.genai_client:
            raise ValueError("GenAI client not initialized")
        
        try:
            if not hasattr(self.genai_client, 'caches'):
                return f"no_cache_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            
            cached_content = self.genai_client.caches.create(
                model=MODEL_NAME,
                config=types.CreateCachedContentConfig(
                    display_name=f"system_prompt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    contents=[types.Part.from_text(system_prompt)],
                    ttl="3600s"
                )
            )
            return cached_content.name
        except Exception as e:
            logger.error(f"❌ Error creating cached content: {e}")
            raise

    async def get_cached_content_id(self, session_id: str) -> str:
        session_metadata = await self.get_session_metadata(session_id)
        return session_metadata.get('cached_content_id')

    async def run_agent_with_fallback(self, agent: Agent, user_message: str, session_deps: ChatSessionDeps) -> Any:
        """Run agent with proper error handling for cache expiration and fallback."""
        try:
            logger.info("Running agent with cached content")
            result = await agent.run(user_message, deps=session_deps)
            logger.info("Agent run completed successfully")
            return result
        except Exception as e:
            logger.error(f"Agent run failed with cached content: {e}")
            
            # Check if it's a cache-related error
            if "cached_content" in str(e).lower() or "cache" in str(e).lower():
                logger.warning("Cache error detected, falling back to no cache")
                
                # Create fallback agent without cache
                try:
                    fallback_model = GoogleModel(MODEL_NAME)
                    fallback_agent = Agent(
                        fallback_model,
                        system_prompt=agent.system_prompt,
                        tools=agent.tools,
                        deps_type=ChatSessionDeps,
                    )
                    
                    logger.info("Running fallback agent without cache")
                    result = await fallback_agent.run(user_message, deps=session_deps)
                    logger.info("Fallback agent run completed successfully")
                    return result
                    
                except Exception as fallback_error:
                    logger.error(f"Fallback agent also failed: {fallback_error}")
                    raise fallback_error
            else:
                # Non-cache related error, re-raise
                raise e

    async def create_agent(self, session_id: str, system_prompt: str, tools: List[Any], user_email: str) -> Agent:
        """Create an agent instance with proper Pydantic AI settings and caching."""
        logger.info(f"Creating agent for session {session_id} for user {user_email}")
        
        try:
            # Get or create file search store for this session
            file_search_store_id = await self.get_or_create_file_search_store(session_id)
            
            # Get cached content ID from session metadata
            cached_content_id = await self.get_cached_content_id(session_id)
            if not cached_content_id:
                try:
                    cached_content_id = await self.get_or_create_cached_content(system_prompt)
                except Exception as e:
                    logger.warning(f"Failed to create cached content: {e}")
                    cached_content_id = None
            
            # Prepare model settings following Pydantic AI best practices
            model_settings = None
            if cached_content_id and not cached_content_id.startswith('no_cache_'):
                model_settings = GoogleModelSettings(google_cached_content=cached_content_id)
                logger.info(f"Using cached content ID: {cached_content_id}")
            
            # Initialize model with proper settings handling
            try:
                google_model = GoogleModel(MODEL_NAME, settings=model_settings)
                logger.info("GoogleModel initialized with settings")
            except Exception as e:
                logger.error(f"Failed to initialize GoogleModel with settings: {e}")
                # Fallback to model without settings
                google_model = GoogleModel(MODEL_NAME)
                logger.warning("Falling back to GoogleModel without settings")
        
            # Create agent with proper Pydantic AI initialization
            try:
                agent = Agent(
                    google_model,
                    system_prompt=system_prompt,
                    tools=tools,
                    deps_type=ChatSessionDeps,
                )
                logger.info("Agent created successfully with proper settings")
            except Exception as e:
                logger.error(f"Failed to create agent: {e}")
                raise e
            
            # Update session metadata asynchronously if DB is available
            if self.db:
                try:
                    await self.update_session_metadata(session_id, file_search_store_id, cached_content_id)
                except Exception as e:
                    logger.warning(f"Failed to update session metadata: {e}")
            
            return agent
            
        except Exception as e:
            logger.error(f"Error creating agent: {e}")
            raise e

    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
         if not self.db: return
         await self.db.update_session_metadata(session_id, file_search_store_id, cached_content_id)

    async def process_message(self, message: str, session_id: str) -> str:
        """Process a chat message and return response"""
        try:
            # This would need to be implemented based on actual chat logic
            # For now, return a simple response
            return f"Response to: {message}"
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise

    async def get_chat_history(self, session_id: str) -> Dict[str, Any]:
        """Get chat history for a session"""
        try:
            # Use ChatDAO to get chat history
            history = await self.chat_dao.get_chat_history(session_id)
            return history or {"messages": []}
        except Exception as e:
            logger.error(f"❌ Error getting chat history: {e}")
            return {"messages": []}

    async def process_message_stream(self, message: str, session_id: str):
        """Process a chat message with RAG-enhanced streaming response"""
        try:
            # Import AI service
            from ..core.ai import get_genai_client, get_gemini_model
            
            logger.info(f"Processing message: {message[:50]}... for session: {session_id}")
            
            # Get Gemini model
            model = get_gemini_model()
            if not model:
                logger.error("Gemini model is not available")
                yield "AI service is currently unavailable. Please try again later."
                return
            
            # Get Gemini client for RAG search
            client = get_genai_client()
            if not client:
                logger.error("Gemini client is not available")
                yield "AI service is currently unavailable. Please try again later."
                return
            
            # Step 1: RAG Search - Use Gemini File Search tool
            logger.info("🔍 Performing RAG search in knowledge base...")
            rag_context = ""
            try:
                # Import types at the top to avoid UnboundLocalError
                from google.genai import types

                # Resolve FileSearch store on-demand (not relying on module-level variable which may not be shared across workers)
                from shared.file_search import get_file_search_store_by_display_name

                resolved_store_id = get_file_search_store_by_display_name(
                    client,
                    display_name="knowledgebot-search-store"
                )

                if not resolved_store_id:
                    logger.error("❌ FileSearch store could not be resolved - RAG search cannot proceed")
                    rag_context = "FileSearch store not found. Please check API Gateway has created the store."
                    raise ValueError("FileSearch store not resolved")

                logger.info(f"📂 Using FileSearch store: {resolved_store_id}")

                # Configure the File Search tool
                file_search_tool = types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[resolved_store_id]
                    )
                )
                
                # Perform a quick search to get context (this will be used in the main generation)
                search_response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=f"Search for information related to: {message}",
                    config=types.GenerateContentConfig(
                        tools=[file_search_tool],
                        temperature=0.1  # Low temperature for factual responses
                    )
                )
                
                if search_response and search_response.text:
                    rag_context = search_response.text
                    logger.info(f"📚 RAG search successful, context length: {len(rag_context)} characters")
                else:
                    logger.info("📚 No relevant documents found in knowledge base")
                    rag_context = "No relevant documents found in the knowledge base."
                    
            except Exception as e:
                logger.error(f"❌ RAG search failed: {e}")
                rag_context = "Unable to search knowledge base due to an error."
            
            # Step 2: Get chat history for context
            chat_history = await self.get_chat_history(session_id)
            logger.info(f"Retrieved chat history: {len(chat_history.get('messages', []))} messages")
            
            # Format chat history for Gemini
            history_text = ""
            if chat_history and chat_history.get("messages"):
                for msg in chat_history["messages"][-3:]:  # Last 3 messages for context
                    if msg.get("sender") == "user":
                        history_text += f"User: {msg.get('message', '')}\n"
                    elif msg.get("sender") in ["agent", "bot"]:
                        history_text += f"Assistant: {msg.get('message', '')}\n"
            
            logger.info(f"History text length: {len(history_text)} characters")
            
            # Step 3: Fetch active persona and response policy, create conversational system prompt
            persona_prompt = ""
            persona_name = "KnowledgeBot"
            response_policy = ""
            response_timeout = 30  # Default timeout
            
            try:
                # Import here to avoid circular imports
                import os
                import httpx
                
                # Get chat agent config from configuration service
                config_url = os.getenv("CONFIGURATION_SERVICE_URL", "https://api-gateway-common.up.railway.app/api/v1/gateway/configuration/chatAgentConfig")
                
                # Add authentication headers if available
                headers = {}
                # Try to get API key from environment for internal service communication
                api_key = os.getenv("INTERNAL_API_KEY")
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                
                async with httpx.AsyncClient(timeout=10.0, headers=headers) as http_client:
                    response = await http_client.get(config_url)
                    if response.status_code == 200:
                        config_data = response.json()
                        persona_data = config_data.get("persona", {})
                        persona_prompt = persona_data.get("system_prompt", "")
                        persona_name = persona_data.get("selected_persona", "KnowledgeBot")
                        
                        # Get response policy
                        response_policy = config_data.get("response_policy", "")
                        if response_policy:
                            logger.info(f"📋 Using response policy: {response_policy}")
                        
                        # Get response timeout from security settings
                        security_data = config_data.get("security", {})
                        response_timeout = security_data.get("response_timeout", 30)
                        logger.info(f"⏱️ Response timeout: {response_timeout} seconds")
                        
                        logger.info(f"🎭 Using active persona: {persona_name}")
                    else:
                        logger.warning(f"⚠️ Failed to fetch persona config: {response.status_code}")
                        # Log response body for debugging
                        if response.status_code == 401:
                            logger.warning("🔐 Authentication failed - check INTERNAL_API_KEY environment variable")
            except Exception as e:
                logger.error(f"❌ Error fetching persona config: {e}")
                logger.info("🎭 Using default KnowledgeBot persona")
            
            # Create conversational system prompt with persona and response policy integration
            system_prompt = f"""You are {persona_name}, a helpful AI assistant that engages in natural conversation and answers questions based ONLY on the provided knowledge base context.

{persona_prompt}

RESPONSE POLICY:
{response_policy if response_policy else "Be helpful, accurate, and concise in your responses."}

CONVERSATION GUIDELINES:
1. Be friendly and conversational - greet naturally when users say hello or introduce themselves
2. If the user's message is just a greeting (like "hi", "hello", "hey"), respond with a natural greeting and ask how you can help
3. If the user's message is unclear or too vague, ask for clarification in a friendly way
4. Only when you have a clear question, check the Knowledge Base Context for relevant information
5. You MUST answer ONLY using information from the provided Knowledge Base Context
6. If the answer is not found in the context, respond: "I'm sorry, but this information is not available in my training data."
7. Do NOT use any external knowledge or make up information
8. Be helpful and conversational while staying within the knowledge base constraints

Knowledge Base Context:
{rag_context}

Conversation History:
{history_text}"""
            
            # User message separate for better caching
            user_message = f"User Message: {message}\n\nRespond naturally based on the conversation:"
            
            logger.info(f"🤖 Using cached Gemini model with structured prompt (system: {len(system_prompt)}, user: {len(user_message)} chars)")
            
            # Step 4: Generate response using Gemini with File Search tool
            logger.info("🧠 Generating content with Gemini using RAG context and caching...")
            
            # Use the Gemini client directly with File Search tool (not Pydantic AI)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=f"{system_prompt}\n\n{user_message}",
                config=types.GenerateContentConfig(
                    tools=[file_search_tool],
                    temperature=0.1
                )
            )
            
            # Stream the response
            if response and response.text:
                response_text = response.text
                logger.info(f"✅ Generated response length: {len(response_text)} characters")
                logger.info(f"💬 Response text: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")

                # Debug: Log response metadata
                if hasattr(response, 'usage_metadata'):
                    logger.info(f"📊 Token usage - Prompt: {response.usage_metadata.prompt_token_count}, "
                              f"Completion: {response.usage_metadata.candidates_token_count}, "
                              f"Total: {response.usage_metadata.total_token_count}")

                # Track token usage from the RAG response
                await self._track_token_usage(response, session_id)
                
                # Stream the response in chunks of ~10 characters with proper JSON format
                chunk_size = 10
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    # Format as JSON for frontend compatibility (FastAPI will add data: prefix)
                    chunk_data = {
                        "type": "chunk",
                        "content": chunk
                    }
                    yield f"{json.dumps(chunk_data)}\n\n"
                
                # Send completion signal
                complete_data = {
                    "type": "complete", 
                    "content": response_text,
                    "sources": []
                }
                yield f"{json.dumps(complete_data)}\n\n"
            else:
                logger.error("❌ No response received from Gemini")
                error_data = {
                    "type": "error",
                    "content": "I'm sorry, but I couldn't generate a response. Please try again."
                }
                yield f"{json.dumps(error_data)}\n\n"
            
        except Exception as e:
            logger.error(f"Error processing message stream with RAG: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception details: {str(e)}")
            yield "I encountered an error while processing your message. Please try again."

    async def _track_token_usage(self, response, session_id: str):
        """Track token usage from Gemini response"""
        try:
            # Extract token usage from Gemini response
            usage_data = None
            if hasattr(response, 'usage_metadata'):
                usage_data = response.usage_metadata
            elif hasattr(response, 'usage'):
                usage_data = response.usage

            if usage_data:
                # Use TokenDAO for tracking
                from ..dao.token_dao import TokenDAO
                token_dao = TokenDAO()

                # Generate a message ID
                import uuid
                message_id = str(uuid.uuid4())

                # Extract token counts from Gemini usage data
                prompt_tokens = getattr(usage_data, 'prompt_token_count', 0) or getattr(usage_data, 'promptTokenCount', 0) or getattr(usage_data, 'prompt_tokens', 0)
                completion_tokens = getattr(usage_data, 'candidates_token_count', 0) or getattr(usage_data, 'candidatesTokenCount', 0) or getattr(usage_data, 'completion_tokens', 0)
                total_tokens = getattr(usage_data, 'total_token_count', 0) or getattr(usage_data, 'totalTokenCount', 0) or getattr(usage_data, 'total_tokens', 0)

                # Save to database using DAO
                import os
                model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")

                success = await token_dao.save_token_usage(
                    session_id=session_id,
                    message_id=message_id,
                    provider='gemini',
                    model=model_name,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                    total_tokens=int(total_tokens),
                    api_call_type='rag'
                )

                if success:
                    logger.info(f"✅ Tracked token usage: {total_tokens} tokens for session {session_id}")
                else:
                    logger.error(f"❌ Failed to track token usage for session {session_id}")

        except Exception as e:
            logger.error(f"Error tracking token usage: {e}")

    async def get_available_agents(self) -> list:
        """Get list of available agents"""
        try:
            # This would need to be implemented based on actual agent logic
            # For now, return empty list
            return []
        except Exception as e:
            logger.error(f"Error getting available agents: {e}")
            raise

    async def get_agent_info(self, agent_id: str) -> dict:
        """Get information about a specific agent"""
        try:
            # This would need to be implemented based on actual agent logic
            # For now, return empty dict
            return {}
        except Exception as e:
            logger.error(f"Error getting agent info: {e}")
            raise

pydantic_ai_service = PydanticAIGatewayService()

class SessionStateManager:
    """Manages session state for multi-turn conversational loops."""
    def __init__(self):
        self.session_states = {}

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        return self.session_states.get(session_id, {
            'session_id': session_id,
            'turn_count': 0,
            'message_history': [],
            'last_activity': time.time()
        })
    
    def update_session_state(self, session_id: str, result: Any) -> Dict[str, Any]:
        state = self.get_session_state(session_id)
        state['turn_count'] += 1
        if hasattr(result, 'all_messages'):
            state['message_history'] = result.all_messages()
        state['last_activity'] = time.time()
        self.session_states[session_id] = state
        return state

session_state_manager = SessionStateManager()
