import json
import os
from typing import List, Dict, Any, Optional, Annotated
from pydantic_ai import RunContext

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from sqlalchemy import text

# Import our dependencies
from ..core.dependencies import ChatSessionDeps
from ..core.ai import get_genai_client
from ..core.config import settings

logger = get_otel_logger("vector_search_tool", "chatbot-orchestration")

from shared.embeddings import generate_embedding


def _estimate_text_tokens(text: str) -> int:
    """Best-effort local token estimate for diagnostics."""
    if not text:
        return 0
    try:
        from litellm import token_counter

        return int(token_counter(model="gemini/gemini-2.5-flash-lite", text=text) or 0)
    except Exception:
        return max(1, len(text) // 4)

def _compress_context(context_text: str) -> str:
    """Implement LLMLingua-2 quantized compression with telemetry."""
    try:
        from llmlingua import PromptCompressor
        import time
        start = time.time()
        
        # Using the smaller, quantized-native bert-base model for 2026 performance
        compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank", 
            use_llmlingua2=True,
            device_map="cpu" # Explicitly use CPU for quantization-friendly execution
        )
        
        orig_len = len(context_text)
        # Target 2x compression ratio
        compressed = compressor.compress_prompt(context_text, rate=0.5, force_tokens=['\n', 'Snippet', 'Source'])
        compressed_text = compressed.get('compressed_prompt', context_text)
        comp_len = len(compressed_text)
        
        duration = (time.time() - start) * 1000
        savings = (1 - (comp_len / orig_len)) * 100 if orig_len > 0 else 0
        
        logger.info(f"📉 [LLMLingua-2] Compressed context in {duration:.1f}ms: "
                    f"{orig_len} -> {comp_len} chars ({savings:.1f}% saved)")
        
        return compressed_text
    except Exception as e:
        logger.warning(f"⚠️ LLMLingua-2 quantized compression failed: {e}")
        return context_text

def _is_table_chunk(chunk: Dict[str, Any]) -> bool:
    """Heuristic: table-aware Kreuzberg chunks should not be compressed by LLMLingua."""
    try:
        metadata = chunk.get("metadata") or {}
        strategy = metadata.get("strategy") if isinstance(metadata, dict) else None
        if strategy and "table" in str(strategy).lower():
            return True
        content = (chunk.get("content") or "").lstrip()
        if content.startswith("## Table") or content.startswith("|"):
            return True
    except Exception:
        return False
    return False

def _ensure_table_coverage(
    selected: List[Dict[str, Any]],
    pool: List[Dict[str, Any]],
    *,
    min_tables: int,
    max_total: int,
) -> List[Dict[str, Any]]:
    """
    Ensure table chunks aren't dropped entirely by reranking.

    Strategy:
    - Keep current `selected` ordering as much as possible.
    - If fewer than `min_tables` table chunks are present, pull additional table chunks
      from the broader `pool` (sorted by hybrid_score) and append them.
    - Trim to `max_total`.
    """
    if not selected:
        return selected

    out: List[Dict[str, Any]] = list(selected)
    table_count = sum(1 for c in out if _is_table_chunk(c))
    if table_count >= min_tables:
        return out[:max_total]

    # Prefer high-scoring table chunks from the original pool.
    def _score(c: Dict[str, Any]) -> float:
        try:
            return float(c.get("hybrid_score") or 0.0)
        except Exception:
            return 0.0

    existing_ids = {(str(c.get("document_id")), str(c.get("content") or "")[:200]) for c in out}
    candidates = [c for c in pool if _is_table_chunk(c)]
    candidates.sort(key=_score, reverse=True)

    for c in candidates:
        key = (str(c.get("document_id")), str(c.get("content") or "")[:200])
        if key in existing_ids:
            continue
        out.append(c)
        existing_ids.add(key)
        table_count += 1
        if table_count >= min_tables:
            break

    return out[:max_total]

def _rerank_results(query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Implement FlashRank Stage-2 reranking with telemetry."""
    try:
        from flashrank import Ranker, RerankRequest
        import time
        start = time.time()
        
        ranker = Ranker()
        passages = [{"id": i, "text": c["content"], "meta": c["metadata"]} for i, c in enumerate(chunks)]
        rerank_request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(rerank_request)
        
        # Map back to original chunks
        ranked_chunks = []
        for r in results:
            idx = r["id"]
            ranked_chunks.append(chunks[idx])
            
        duration = (time.time() - start) * 1000
        logger.info(f"🎯 [FlashRank] Reranked {len(passages)} candidates in {duration:.1f}ms. "
                    f"Top score: {results[0]['score'] if results else 'N/A'}")
        
        return ranked_chunks[:10]
    except Exception as e:
        logger.warning(f"⚠️ FlashRank reranking failed: {e}")
        return chunks[:10]

async def search_knowledge_base(
    ctx: RunContext[ChatSessionDeps],
    query: Annotated[str, "The user's normalized information request or greeting text. For a non-greeting message, one search call is usually enough, but additional calls are allowed when they search for distinct new information needed to answer a genuinely multi-part question."],
    greeting_flag: Annotated[Optional[bool], "Set to true only when the latest user message is a pure greeting with no information request. Set to false for all other messages. For non-greeting messages, avoid repeating the same search again for the same user message unless the query meaning materially changes."] = None,
) -> str:
    """
    Advanced Knowledge Base Search with Hybrid Search, Reranking, Compression, and Caching.

    For non-greeting turns, one call is the default.
    Multiple calls are acceptable only when each call has a distinct purpose and retrieves
    new information needed to answer a complex or multi-part question.
    Repeating the same search for the same user message is unnecessary.
    """
    if ctx.deps.search_tool_calls >= 1:
        logger.warning("🛑 [TOOL_CALL_LIMIT] search_knowledge_base already called once in this request; skipping repeated retrieval")
        return (
            "Search already completed for this user message. "
            "Use the previous search result to answer now. "
            "Do not call search_knowledge_base again."
        )

    ctx.deps.search_tool_calls += 1

    if greeting_flag is True:
        logger.info("👋 [GREETING_BYPASS] Greeting flag=true, skipping pgvector retrieval")
        return (
            "Greeting-only message detected. Do not use knowledge base facts. "
            "Respond briefly, warmly, and directly to the user without citations."
        )

    import time
    rag_start = time.time()
    table_rows_hint = "Remember to check in all Columns and Row"
    effective_query = query
    if greeting_flag is not True and table_rows_hint not in query:
        effective_query = f"{query} {table_rows_hint}".strip()

    logger.info(f"🔍 Starting advanced retrieval for: '{effective_query}'")
    
    try:
        query_embedding = await generate_embedding(effective_query)
        if not query_embedding:
            return "Knowledge base search failed: Could not generate search vector."
            
        vector_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
        
        async with get_db_session() as db:
            await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
            
            # --- STEP 1: Hybrid Search (Vector + FTS) ---
            hybrid_query = """
                WITH vector_matches AS (
                    SELECT id, content, metadata, document_id, document_type,
                           (1 - (embedding <=> cast(:vector as halfvec))) as sim_score
                    FROM document_chunks
                    WHERE NOT EXISTS (
                        SELECT 1 FROM file_uploads f
                        WHERE f.id = document_chunks.document_id
                          AND document_chunks.document_type = 'file'
                          AND f.processing_status = 'deleted'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM scraped_websites w
                        WHERE w.id = document_chunks.document_id
                          AND document_chunks.document_type = 'website'
                          AND w.processing_status = 'deleted'
                    )
                    ORDER BY embedding <=> cast(:vector as halfvec)
                    LIMIT 50
                ),
                fts_matches AS (
                    SELECT id, ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', :query)) as fts_score
                    FROM document_chunks
                    WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', :query)
                      AND NOT EXISTS (
                          SELECT 1 FROM file_uploads f
                          WHERE f.id = document_chunks.document_id
                            AND document_chunks.document_type = 'file'
                            AND f.processing_status = 'deleted'
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM scraped_websites w
                          WHERE w.id = document_chunks.document_id
                            AND document_chunks.document_type = 'website'
                            AND w.processing_status = 'deleted'
                      )
                    LIMIT 50
                )
                SELECT v.content, v.metadata, v.document_id, v.document_type,
                       (v.sim_score + COALESCE(f.fts_score, 0)) as hybrid_score
                FROM vector_matches v
                LEFT JOIN fts_matches f ON v.id = f.id
                ORDER BY hybrid_score DESC
                LIMIT 50
            """
            
            result = await db.execute(text(hybrid_query), {"vector": vector_str, "query": effective_query})
            rows = result.mappings().all()
            
            if not rows:
                logger.info(
                    f"🧭 [RAG_EARLY_RETURN] reason=no_rows session_id={ctx.deps.session_id or 'none'} query='{effective_query[:120]}'"
                )
                return "I don't have any information on this topic."
            
            # --- STEP 2: Reranking ---
            chunks = [dict(row) for row in rows]
            flashrank_applied = False
            if settings.enable_reranking:
                top_chunks = _rerank_results(effective_query, chunks)
                flashrank_applied = top_chunks != chunks[:10]
            else:
                top_chunks = chunks[:10]

            # --- STEP 3: Format & Compression ---
            # Build a single citation-friendly grounding stream and preserve the
            # retrieval/reranking order without splitting tables from narrative text.
            citation_urls: List[str] = []
            citation_index_by_source: Dict[str, int] = {}
            grounding_chunks: List[str] = []

            for chunk in top_chunks:
                doc_id, doc_type = str(chunk["document_id"]), chunk["document_type"]
                content = chunk["content"]
                score = f"{float(chunk['hybrid_score']):.3f}"

                # Prefer canonical URL for websites; otherwise fall back to a stable KB reference.
                url = None
                try:
                    meta = chunk.get("metadata") or {}
                    if isinstance(meta, dict):
                        url = meta.get("url") or meta.get("source_url")
                except Exception:
                    url = None
                if not url:
                    url = f"kb://{doc_type}/{doc_id}"
                citation_number = citation_index_by_source.get(url)
                if citation_number is None:
                    citation_urls.append(url)
                    citation_number = len(citation_urls)
                    citation_index_by_source[url] = citation_number

                chunk_str = (
                    f"Source {citation_number} (type={doc_type} id={doc_id} score={score} url={url})\n"
                    f"Cite this source as: [{citation_number}]\n"
                    f"{content}\n"
                )

                grounding_chunks.append(chunk_str)

            grounding_context = "\n".join(grounding_chunks).strip()
            grounding_before_chars = len(grounding_context)
            grounding_before_tokens = _estimate_text_tokens(grounding_context)

            llmlingua_applied = False
            llmlingua_reason = "disabled"
            if settings.enable_context_compression and grounding_context:
                compressed_context = _compress_context(grounding_context)
                llmlingua_applied = compressed_context != grounding_context
                llmlingua_reason = "compressed" if llmlingua_applied else "no_change"
            else:
                compressed_context = grounding_context
                if not settings.enable_context_compression:
                    llmlingua_reason = "disabled"
                elif not grounding_context:
                    llmlingua_reason = "no_context"
            grounding_after_chars = len(compressed_context)
            grounding_after_tokens = _estimate_text_tokens(compressed_context)

            final_context = compressed_context

            total_duration = (time.time() - rag_start) * 1000
            
            # Theoretical storage savings per chunk (standard vector 3072B -> halfvec 1536B for 768d)
            # This is constant but helpful to see in telemetry for business value justification
            logger.info(f"✅ [RAG_COMPLETE] Total Retrieval Pipeline: {total_duration:.1f}ms")
            logger.info(f"📊 [HALFVEC_STATS] Using halfp-float storage: 50% byte savings per index row (1.5KB vs 3.0KB)")
            if settings.enable_context_compression:
                logger.info(f"📉 [LLMLingua-2] Compression applied to final grounding stream (chunks_kept={len(grounding_chunks)})")
                
            # Tool output is internal context for the brain model.
            # Provide a minimal instruction for how to cite without leaking URLs to the user.
            response = (
                "Use the sources below to answer the user's question.\n"
                "If a source table directly contains the exact year, row, field, or cell the user asked for, answer with that exact matched value directly.\n"
                "For direct table hits, prefer a short sentence that states the exact value from the matching row instead of a generic summary.\n"
                "Do not say 'Insufficient data provided' or similar generic fallback phrases when the answer is present in the retrieved table rows.\n"
                "When you use a fact from Source N, add an inline citation marker like [N] after that fact.\n\n"
                + final_context
            )

            # DEV-ONLY (user requested): log grounding context returned to the model.
            # WARNING: This can leak knowledge base content into logs. Remove before prod.
            try:
                preview_limit = 12000
                preview = response[:preview_limit]
                logger.info(f"📦 [RAG_GROUNDING_FULL] tool_return_chars={len(response)} preview_chars={len(preview)}\n{preview}")
            except Exception:
                pass

            # Always-on: safe grounding summary (no chunk content).
            # This makes it possible to debug recall/citation issues in production without leaking KB text.
            try:
                sources_summary = []
                for i, chunk in enumerate(top_chunks):
                    meta = chunk.get("metadata") or {}
                    url = meta.get("url") if isinstance(meta, dict) else None
                    if not url:
                        url = f"kb://{chunk.get('document_type')}/{chunk.get('document_id')}"
                    sources_summary.append(
                        {
                            "n": i + 1,
                            "type": chunk.get("document_type"),
                            "id": str(chunk.get("document_id")),
                            "score": float(chunk.get("hybrid_score") or 0.0),
                            "url": url,
                            "is_table": _is_table_chunk(chunk),
                            "content_chars": len(chunk.get("content") or ""),
                        }
                    )
                logger.info(
                    "📦 [RAG_GROUNDING_SUMMARY]",
                    extra={
                        "query_chars": len(query or ""),
                        "sources": sources_summary,
                        "final_context_chars": len(final_context or ""),
                        "tables_kept": 0,
                        "narrative_kept": len(grounding_chunks),
                    },
                )
            except Exception:
                pass

            logger.info(
                f"🧭 [RAG_DIAG] query='{effective_query[:120]}' hit=yes rows={len(rows)} top={len(top_chunks)} "
                f"tables=0 narrative={len(grounding_chunks)} "
                f"flashrank={'on' if settings.enable_reranking else 'off'} "
                f"flashrank_applied={'yes' if flashrank_applied else 'no'} "
                f"flashrank_knn_before={len(chunks)} flashrank_after={len(top_chunks)} "
                f"llmlingua={'on' if settings.enable_context_compression else 'off'} "
                f"llmlingua_applied={'yes' if llmlingua_applied else 'no'} "
                f"llmlingua_reason={llmlingua_reason} "
                f"llmlingua_before_chars={grounding_before_chars} llmlingua_after_chars={grounding_after_chars} "
                f"llmlingua_before_tokens={grounding_before_tokens} llmlingua_after_tokens={grounding_after_tokens} "
                f"citations={len(citation_urls)}"
            )
            
            # --- STEP 4: Update Session State ---
            if ctx.deps.session_id:
                from ..service.session_manager import session_state_manager
                session_state_manager.set_tool_used(ctx.deps.session_id, "search_knowledge_base")
                session_state_manager.set_last_citation_urls(ctx.deps.session_id, citation_urls)
                logger.info(
                    f"🧭 [RAG_STATE_WRITE] path=live_retrieval session_id={ctx.deps.session_id} "
                    f"citation_count={len(citation_urls)} tool_used=yes"
                )
            else:
                logger.warning("🧭 [RAG_STATE_WRITE] skipped: missing session_id on tool context")
                
            return response
            
    except Exception as e:
        logger.error(f"❌ Advanced RAG error: {e}", exc_info=True)
        return f"An error occurred during search: {str(e)}"
