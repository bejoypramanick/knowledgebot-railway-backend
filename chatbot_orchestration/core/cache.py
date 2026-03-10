import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

import logging
from shared.otel_logger import get_otel_logger
from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Import os to access environment variables potentially?
# The original code used MODEL_NAME global variable. 
# I will pass it as an argument or import settings.

CACHE_TTL_SECONDS = 3600  # 1 hour TTL
context_cache = {}

def generate_cache_key(prompt_components: Dict[str, Any], model_name: str) -> str:
    """Generate a unique cache key based on prompt components."""
    cache_data = {
        'custom_prompt': prompt_components.get('custom_prompt', ''),
        'response_policy': prompt_components.get('response_policy', ''),
        'model_name': model_name
    }
    
    cache_string = json.dumps(cache_data, sort_keys=True)
    return hashlib.sha256(cache_string.encode()).hexdigest()

def get_cached_system_prompt(prompt_components: Dict[str, Any], model_name: str) -> Optional[str]:
    """Get cached system prompt if available and not expired."""
    cache_key = generate_cache_key(prompt_components, model_name)
    
    logger.info(f"🔍 Checking cache for key: {cache_key[:16]}...")
    logger.info(f"🔍 Current cache size: {len(context_cache)} entries")
    
    if cache_key in context_cache:
        cached_data = context_cache[cache_key]
        current_time = time.time()
        cache_age = current_time - cached_data['timestamp']
        logger.info("cache_age: {cache_age}")
        logger.info(f"📦 Cache entry found:")
        logger.info(f"  - Cache age: {cache_age:.1f}s ({cache_age/60:.1f}m)")
        logger.info(f"  - TTL: {CACHE_TTL_SECONDS}s ({CACHE_TTL_SECONDS/60:.1f}m)")
        logger.info(f"  - Expires in: {CACHE_TTL_SECONDS - cache_age:.1f}s")
        logger.info(f"  - Prompt length: {len(cached_data['prompt'])} chars")
        logger.info(f"  - Created at: {datetime.fromtimestamp(cached_data['timestamp']).isoformat()}")
        
        if cache_age < CACHE_TTL_SECONDS:
            logger.info(f"✅ CACHE HIT - Using cached system prompt (age: {cache_age:.1f}s)")
            logger.info(f"✅ Cache efficiency: 90% discount applied")
            return cached_data['prompt']
        else:
            logger.warning(f"⏰ CACHE EXPIRED - Removing expired entry for key: {cache_key[:16]}...")
            logger.warning(f"⏰ Cache was {cache_age - CACHE_TTL_SECONDS:.1f}s past TTL")
            del context_cache[cache_key]
            logger.info(f"🗑️ Expired cache entry removed. New cache size: {len(context_cache)} entries")
    else:
        logger.info(f"❌ CACHE MISS - No entry found for key: {cache_key[:16]}...")
    
    return None

def cache_system_prompt(prompt_components: Dict[str, Any], prompt: str, model_name: str) -> str:
    """Cache the system prompt with timestamp."""
    cache_key = generate_cache_key(prompt_components, model_name)
    
    logger.info(f"💾 Caching system prompt:")
    logger.info(f"  - Cache key: {cache_key[:16]}...")
    logger.info(f"  - Prompt length: {len(prompt)} characters")
    logger.info(f"  - TTL: {CACHE_TTL_SECONDS}s ({CACHE_TTL_SECONDS/60:.1f}m)")
    logger.info(f"  - Timestamp: {datetime.fromtimestamp(time.time()).isoformat()}")
    logger.info(f"  - Components: {list(prompt_components.keys())}")
    
    context_cache[cache_key] = {
        'prompt': prompt,
        'timestamp': time.time(),
        'components': prompt_components
    }
    
    logger.info(f"💾 Cache entry stored. New cache size: {len(context_cache)} entries")
    logger.info(f"💾 Cache efficiency: 90% discount available for future requests")
    
    return prompt
