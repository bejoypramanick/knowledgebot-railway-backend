import logging
import json
import uuid
import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..schemas.models import (
    ChatRequest, ChatResponse, ChatSessionResponse, 
    SuggestedMessagesRequest, SuggestedMessagesResponse, HumanReviewRequest
)
from ..core.memory import sessions
from ..core.dependencies import ChatSessionDeps
from ..core.database import get_railway_db
from ..agent.service import (
    pydantic_ai_service, session_state_manager
)
from ..core.ai import gemini_model
from ..tools.rag import search_knowledge_base
from ..tools.general import (
    request_human_agent_connection, query_railway_postgres
)
from ..agent.prompt import get_system_prompt, extract_gemini_rag_metadata
from shared.token_tracker import track_gemini_usage_from_response
from shared.utils import log_endpoint_request

# Pydantic AI imports for processing messages
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Handle chat request with streaming response using optimized Pydantic AI Gateway Service.
    """
    try:
        session_id = request.session_id or str(uuid.uuid4())
        
        # Generate system prompt with caching (logic inside get_system_prompt handles caching check)
        # Note: In optimized path, we pass prompt content to create_agent which handles caching
        # But get_system_prompt currently returns the *cached* prompt from local cache if enabled?
        # Revisiting logic: get_system_prompt in agent/prompt.py calls cache_system_prompt.
        # It generates the prompt string.
        
        system_prompt = get_system_prompt(
            file_context=None,  # File context will be handled by FileSearch tool
            custom_prompt=request.system_prompt,
            response_policy=request.response_policy,
            rag_had_results=True  # Will be determined by FileSearch tool
        )
        
        # Prepare tools for the agent
        tools = [search_knowledge_base]
        tools.append(request_human_agent_connection)
        
        # We need to act carefully about optional dependencies
        # Since tools are imports, they exist. But we should check connectivity?
        # The logic in main.py checked DB availability.
        # We can do basic checks or just include them.
        tools.append(query_railway_postgres) # It handles internal check
        
        
        # Create optimized agent using Pydantic AI Gateway Service
        try:
            agent = await pydantic_ai_service.create_agent(
                session_id=session_id,
                system_prompt=system_prompt,
                tools=tools
            )
        except Exception as e:
            logger.error(f"❌ Failed to create optimized agent: {e}")
            logger.error("❌ No fallback available - agent creation failed")
            return StreamingResponse(
                iter(["data: " + json.dumps({"error": "Failed to create agent"}) + "\n\n"]),
                media_type="text/plain",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
        
        if not agent:
            logger.error("Failed to create agent")
            return StreamingResponse(
                iter(["data: " + json.dumps({"error": "Failed to create agent"}) + "\n\n"]),
                media_type="text/plain",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
        
        # Prepare message history
        message_history = []
        turn_count = session_state_manager.get_turn_count(session_id)
        is_new_session = session_state_manager.is_new_session(session_id)
        
        if not is_new_session:
            message_history = session_state_manager.get_message_history(session_id)
            logger.info(f"📚 Using preserved message history for turn {turn_count + 1}: {len(message_history)} messages")
        else:
            logger.info(f"🆕 Starting new session (turn 1) for {session_id}")
        
        session_dep = ChatSessionDeps(session_id=session_id)
        
        logger.info(f"🚀 Starting optimized chat stream for session {session_id} (turn {turn_count + 1})")
        
        async def generate_response():
            max_retries = 3
            retry_delay = 1.0
            
            for attempt in range(max_retries):
                try:
                    if attempt == 0:
                        yield f"data: {json.dumps({'type': 'start', 'content': ''})}\n\n"
                    
                    result = await agent.run(
                        request.message,
                        message_history=message_history,
                        deps=session_dep
                    )
                    
                    session_state_manager.update_session_state(session_id, result)
                    
                    response_text = ""
                    if hasattr(result, 'output'):
                        response_text = result.output if isinstance(result.output, str) else str(result.output)
                    elif hasattr(result, 'data'):
                        response_text = str(result.data)
                    elif hasattr(result, 'response') and result.response:
                        response_text = result.response.text if hasattr(result.response, 'text') else str(result.response)
                    
                    words = response_text.split()
                    for i, word in enumerate(words):
                        chunk = word + (' ' if i < len(words) - 1 else '')
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                        await asyncio.sleep(0.05) # Slightly faster than 0.1
                    
                    # Usage tracking from response metadata
                    if hasattr(result, 'usage'):
                        await track_gemini_usage_from_response(
                            result.usage, 
                            session_id=session_id, 
                            api_call_type='chat_stream'
                        )
                    
                    # Extract grounding metadata (RAG)
                    rag_metadata = extract_gemini_rag_metadata(result)
                    sources = []
                    if rag_metadata:
                        logger.info(f"📊 Extracted RAG metadata: {len(rag_metadata)} items")
                        sources = rag_metadata

                    yield f"data: {json.dumps({'type': 'complete', 'content': response_text, 'sources': sources, 'metadata': rag_metadata})}\n\n"
                    yield f"data: [DONE]\n\n"
                    
                    logger.info(f"✅ Stream completed successfully on attempt {attempt + 1}")
                    return
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ Error in streaming response (attempt {attempt + 1}/{max_retries}): {error_msg}")
                    
                    is_retryable_error = any(keyword in error_msg.lower() for keyword in [
                        'database', 'connection', 'timeout', 'network', 'unavailable',
                        'sql', 'postgres', 'connection refused', 'connection reset'
                    ])
                    
                    if attempt < max_retries - 1 and is_retryable_error:
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 8.0)
                        continue
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'content': 'Error processing request.'})}\n\n"
                        yield f"data: [DONE]\n\n"
                        return
        
        return StreamingResponse(
            generate_response(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
        
    except Exception as e:
        logger.error(f"Chat streaming error: {e}")
        return StreamingResponse(
            iter(["data: " + json.dumps({"error": f"Chat processing failed: {str(e)}"}) + "\n\ndata: [DONE]\n\n"]),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )


@router.get("/sessions")
async def list_sessions_endpoint():
    return {
        "sessions": [
            {"session_id": sid, "created_at": sess["created_at"], "message_count": len(sess["messages"])}
            for sid, sess in sessions.items()
        ]
    }

@router.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        return {"success": True, "message": f"Session {session_id} deleted"}
    raise HTTPException(status_code=404, detail="Session not found")

@router.post("/sessions/{session_id}/review")
async def review_response_endpoint(session_id: str, review: HumanReviewRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]
    if "reviews" not in session: session["reviews"] = []
    session["reviews"].append({
        "approved": review.approved, "feedback": review.feedback, 
        "corrected_answer": review.corrected_answer, "timestamp": datetime.utcnow().isoformat()
    })
    return {"success": True, "message": "Review recorded", "session_id": session_id}

@router.post("/suggested-messages", response_model=SuggestedMessagesResponse)
async def generate_suggested_messages_endpoint(request: SuggestedMessagesRequest):
    try:
        conversation_history = request.conversation_history
        if not conversation_history and request.session_id in sessions:
            session = sessions[request.session_id]
            conversation_history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in session.get("messages", [])[-10:]
            ]
        
        context = ""
        if conversation_history:
            for msg in conversation_history:
                context += f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}\n"
        
        prompt = f"""Based on the following conversation, generate 3-5 short, relevant follow-up questions or messages that a user might want to ask next. 
Keep each suggestion concise (under 40 characters).
Conversation:
{context if context else "Start of conversation."}
Generate suggested messages as a JSON array of strings. Example: ["Q1", "Q2"]"""

        if not gemini_model:
            raise HTTPException(status_code=503, detail="Gemini model not available")
            
        suggestion_agent = Agent(model=gemini_model, system_prompt="You are a helpful assistant. Return JSON array.")
        result = await suggestion_agent.run(prompt)
        
        response_text = ""
        if hasattr(result, 'output'): response_text = str(result.output)
        elif hasattr(result, 'data'): response_text = str(result.data)
        
        import re
        json_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
        suggested_messages = []
        if json_match:
            try:
                suggested_messages = json.loads(json_match.group(0))
            except: pass
        
        if not suggested_messages:
            suggested_messages = ["Tell me more", "I have a question"]
            
        return SuggestedMessagesResponse(suggested_messages=suggested_messages[:5])
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
