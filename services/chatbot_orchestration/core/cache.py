import time
import hashlib
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

# Import os to access environment variables potentially?
# The original code used MODEL_NAME global variable. 
# I will pass it as an argument or import settings.

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # 1 hour TTL
context_cache = {}

def generate_cache_key(prompt_components: Dict[str, Any], model_name: str) -> str:
    """Generate a unique cache key based on prompt components."""
    # Safely extract file_context data to prevent NoneType errors
    file_context = prompt_components.get('file_context', [])
    safe_file_context = []
    if file_context:
        try:
            # Ensure file_context is iterable and not None
            if isinstance(file_context, (list, tuple)):
                safe_file_context = [
                    (f.file_name, f.content[:100] if f.content else '')
                    for f in file_context 
                    if f and hasattr(f, 'file_name') and hasattr(f, 'content')
                ]
            else:
                logger.warning(f"file_context is not iterable: {type(file_context)}")
                safe_file_context = []
        except Exception as e:
            logger.warning(f"Error processing file_context for cache key: {e}")
            safe_file_context = []
    
    cache_data = {
        'file_context': str(sorted(safe_file_context)),
        'custom_prompt': prompt_components.get('custom_prompt', ''),
        'response_policy': prompt_components.get('response_policy', ''),
        'rag_had_results': prompt_components.get('rag_had_results', True),
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
