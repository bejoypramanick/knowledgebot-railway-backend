"""
Sentiment Analysis Service
Analyzes chat session sentiment using LLM
"""
import logging
import sys
from pathlib import Path
from typing import Optional, List, Dict
import json
import os
from dotenv import load_dotenv

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.config import settings

logger = logging.getLogger(__name__)

load_dotenv()

# Lazy initialization of LLM clients
genai_client = None
openai_client = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or settings.openai_api_key


def get_gemini_client():
    """Lazy initialization of Gemini client."""
    global genai_client
    if genai_client is None and GEMINI_API_KEY:
        try:
            from google import genai
            genai_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("✅ Gemini client initialized for sentiment analysis")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
    return genai_client


def get_openai_client():
    """Lazy initialization of OpenAI client."""
    global openai_client
    if openai_client is None and OPENAI_API_KEY:
        try:
            import openai
            openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
            logger.info("✅ OpenAI client initialized for sentiment analysis")
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenAI client: {e}")
    return openai_client


async def analyze_sentiment_with_llm(messages: List[Dict[str, str]]) -> Optional[str]:
    """
    Analyze sentiment of a chat session using LLM.
    
    Args:
        messages: List of messages with 'sender' and 'text' keys
        
    Returns:
        'positive', 'negative', or 'neutral', or None if analysis fails
    """
    try:
        # Filter to get only user and bot messages (exclude system messages)
        conversation_text = []
        for msg in messages:
            sender = msg.get('sender', '')
            text = msg.get('text', '')
            if sender in ['user', 'bot', 'agent'] and text:
                role = 'Customer' if sender == 'user' else 'Assistant'
                conversation_text.append(f"{role}: {text}")
        
        if not conversation_text:
            logger.warning("No conversation text to analyze")
            return None
        
        # Combine all messages into a single conversation
        full_conversation = "\n".join(conversation_text)
        
        # Create prompt for sentiment analysis
        prompt = f"""Analyze the sentiment of the following customer support conversation. 
Consider the overall tone, customer satisfaction, and resolution quality.

Conversation:
{full_conversation}

Based on this conversation, determine the overall sentiment. Respond with ONLY one word: "positive", "negative", or "neutral".

Your response should be just the single word, nothing else."""

        # Try Gemini first, fallback to OpenAI
        client = get_gemini_client()
        if client:
            try:
                response = client.models.generate_content(
                    model='gemini-2.0-flash-exp',
                    contents=prompt
                )
                response_text = response.text.strip().lower()
                logger.info(f"Gemini sentiment response: {response_text}")
                
                # Extract sentiment from response - be more strict
                # Remove any punctuation and whitespace, then check
                cleaned_response = response_text.replace('.', '').replace(',', '').replace('!', '').replace('?', '').strip()
                
                if cleaned_response == 'positive' or 'positive' in cleaned_response:
                    logger.info(f"Detected positive sentiment from Gemini")
                    return 'positive'
                elif cleaned_response == 'negative' or 'negative' in cleaned_response:
                    logger.info(f"Detected negative sentiment from Gemini")
                    return 'negative'
                elif cleaned_response == 'neutral' or 'neutral' in cleaned_response:
                    logger.info(f"Detected neutral sentiment from Gemini")
                    return 'neutral'
                else:
                    logger.warning(f"Unexpected sentiment analysis response from Gemini: {response_text}, defaulting to neutral")
                    return 'neutral'
            except Exception as e:
                logger.warning(f"Gemini sentiment analysis failed: {e}, trying OpenAI")
        
        # Fallback to OpenAI
        openai = get_openai_client()
        if openai:
            try:
                response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a sentiment analysis assistant. Analyze customer support conversations and respond with ONLY one word: 'positive', 'negative', or 'neutral'. Do not include any explanation or additional text."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=10
                )
                response_text = response.choices[0].message.content.strip().lower()
                logger.info(f"OpenAI sentiment response: {response_text}")
                
                # Remove any punctuation and whitespace, then check
                cleaned_response = response_text.replace('.', '').replace(',', '').replace('!', '').replace('?', '').strip()
                
                if cleaned_response == 'positive' or 'positive' in cleaned_response:
                    logger.info(f"Detected positive sentiment from OpenAI")
                    return 'positive'
                elif cleaned_response == 'negative' or 'negative' in cleaned_response:
                    logger.info(f"Detected negative sentiment from OpenAI")
                    return 'negative'
                elif cleaned_response == 'neutral' or 'neutral' in cleaned_response:
                    logger.info(f"Detected neutral sentiment from OpenAI")
                    return 'neutral'
                else:
                    logger.warning(f"Unexpected sentiment analysis response from OpenAI: {response_text}, defaulting to neutral")
                    return 'neutral'
            except Exception as e:
                logger.error(f"OpenAI sentiment analysis failed: {e}")
        
        logger.error("Both Gemini and OpenAI sentiment analysis failed")
        return None
        
    except Exception as e:
        logger.error(f"Error in sentiment analysis: {e}", exc_info=True)
        return None


async def analyze_and_store_sentiment(session_id: str, messages: List[Dict[str, str]], conn) -> Optional[str]:
    """
    Analyze sentiment for a session and store it in the database.
    
    Args:
        session_id: The session ID string
        messages: List of messages with 'sender' and 'text' keys
        conn: Database connection
        
    Returns:
        The analyzed sentiment ('positive', 'negative', 'neutral') or None
    """
    try:
        # Analyze sentiment
        sentiment = await analyze_sentiment_with_llm(messages)
        
        if sentiment:
            # Update the session with sentiment
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET sentiment = $1, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = $2
                """,
                sentiment, session_id
            )
            logger.info(f"Stored sentiment '{sentiment}' for session {session_id}")
        else:
            logger.warning(f"Could not analyze sentiment for session {session_id}")
        
        return sentiment
        
    except Exception as e:
        logger.error(f"Error analyzing and storing sentiment: {e}", exc_info=True)
        return None
