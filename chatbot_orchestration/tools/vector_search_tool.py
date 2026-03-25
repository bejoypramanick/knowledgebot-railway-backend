import json
import os
import hashlib
from typing import List, Dict, Any, Optional
from pydantic_ai import RunContext

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from sqlalchemy import text
import redis.asyncio as redis

# Import our dependencies
from ..core.dependencies import ChatSessionDeps
from ..core.ai import get_genai_client

logger = get_otel_logger("vector_search_tool", "chatbot-orchestration")

# --- Redis Semantic Cache Setup ---
_semantic_cache_client: Optional[redis.Redis] = None

async def _get_cache_client() -> redis.Redis:
    global _semantic_cache_client
    if _semantic_cache_client:
        return _semantic_cache_client
    
    url = os.getenv('AGENT_CACHE_REDIS_URL') or os.getenv('CHAT_STORE_REDIS_URL')
    if not url:
        raise RuntimeError("Redis URL not configured for semantic caching")
    
    _semantic_cache_client = redis.from_url(url, decode_responses=True)
    return _semantic_cache_client

from shared.embeddings import generate_embedding

def _compress_context(context_text: str) -> str:
    """Implement LLMLingua-2 quantized compression (Fast & Efficient)."""
    try:
        from llmlingua import PromptCompressor
        # Using the smaller, quantized-native bert-base model for 2026 performance
        compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank", 
            use_llmlingua2=True,
            device_map="cpu" # Explicitly use CPU for quantization-friendly execution
        )
        # Target 2x compression ratio
        compressed = compressor.compress_prompt(context_text, rate=0.5, force_tokens=['\n', 'Snippet', 'Source'])
        return compressed.get('compressed_prompt', context_text)
    except Exception as e:
        logger.warning(f"⚠️ LLMLingua-2 quantized compression failed: {e}")
        return context_text

def _rerank_results(query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Implement FlashRank Stage-2 reranking."""
    try:
        from flashrank import Ranker, RerankRequest
        ranker = Ranker()
        passages = [{"id": i, "text": c["content"], "meta": c["metadata"]} for i, c in enumerate(chunks)]
        rerank_request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(rerank_request)
        # Map back to original chunks
        ranked_chunks = []
        for r in results:
            idx = r["id"]
            ranked_chunks.append(chunks[idx])
        return ranked_chunks[:10]
    except Exception as e:
        logger.warning(f"⚠️ FlashRank reranking failed: {e}")
        return chunks[:10]

async def search_knowledge_base(ctx: RunContext[ChatSessionDeps], query: str) -> str:
    """
    Advanced Knowledge Base Search with Hybrid Search, Reranking, Compression, and Caching.
    """
    # --- STEP 0: Semantic Caching (Redis) ---
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    cache_key = f"rag:cache:{query_hash}"
    try:
        cache = await _get_cache_client()
        cached_result = await cache.get(cache_key)
        if cached_result:
            logger.info(f"⚡ Semantic Cache HIT for query: '{query}'")
            return cached_result
    except Exception as e:
        logger.warning(f"⚠️ Cache lookup failed: {e}")

    logger.info(f"🔍 Starting advanced retrieval for: '{query}'")
    
    try:
        query_embedding = await generate_embedding(query)
        if not query_embedding:
            return "Knowledge base search failed: Could not generate search vector."
            
        vector_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
        
        async with get_db_session() as db:
            await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
            
            # --- STEP 1: Hybrid Search (Vector + FTS) ---
            # Combining pgvector cosine similarity and Postgres Full-Text Search rank
            hybrid_query = """
                WITH vector_matches AS (
                    SELECT id, content, metadata, document_id, document_type,
                           (1 - (embedding <=> cast(:vector as halfvec))) as sim_score
                    FROM document_chunks
                    ORDER BY embedding <=> cast(:vector as halfvec)
                    LIMIT 50
                ),
                fts_matches AS (
                    SELECT id, ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', :query)) as fts_score
                    FROM document_chunks
                    WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', :query)
                    LIMIT 50
                )
                SELECT v.content, v.metadata, v.document_id, v.document_type,
                       (v.sim_score + COALESCE(f.fts_score, 0)) as hybrid_score
                FROM vector_matches v
                LEFT JOIN fts_matches f ON v.id = f.id
                ORDER BY hybrid_score DESC
                LIMIT 50
            """
            
            result = await db.execute(text(hybrid_query), {"vector": vector_str, "query": query})
            rows = result.mappings().all()
            
            if not rows:
                return "No relevant information found in the knowledge base."
            
            # --- STEP 2: FlashRank Reranking ---
            chunks = [dict(row) for row in rows]
            top_chunks = _rerank_results(query, chunks)
                
            # --- STEP 3: Format & LLMLingua-2 Compression ---
            formatted_chunks = []
            for i, chunk in enumerate(top_chunks):
                doc_id, doc_type = str(chunk['document_id']), chunk['document_type']
                content = chunk['content']
                score = f"{float(chunk['hybrid_score']):.3f}"
                
                # Compress individual large chunks or the full context? 
                # Compressing full context is better for token saving.
                chunk_str = f"Source {i+1} ({doc_type} {doc_id}, Score: {score}):\n{content}\n"
                formatted_chunks.append(chunk_str)
                
            full_context = "\n".join(formatted_chunks)
            compressed_context = _compress_context(full_context)
            
            response = "I found the following in our knowledge base:\n\n" + compressed_context
            
            # --- STEP 4: Update Cache & Session State ---
            if cache:
                await cache.set(cache_key, response, ex=3600) # Cache for 1 hour

            if ctx.deps.session_id:
                from ..service.session_manager import session_state_manager
                session_state_manager.set_tool_used(ctx.deps.session_id, "search_knowledge_base")
                
            return response
            
    except Exception as e:
        logger.error(f"❌ Advanced RAG error: {e}", exc_info=True)
        return f"An error occurred during search: {str(e)}"
