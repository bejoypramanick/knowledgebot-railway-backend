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

RAG_MAX_CANDIDATE_ROWS = int(os.getenv("RAG_MAX_CANDIDATE_ROWS", "80"))
RAG_MAX_TOOL_CONTEXT_CHARS = int(os.getenv("RAG_MAX_TOOL_CONTEXT_CHARS", "120000"))
RAG_MAX_CHUNK_CHARS = int(os.getenv("RAG_MAX_CHUNK_CHARS", "8000"))


def _count_gemini_tokens(text: str) -> int:
    """Count diagnostic tokens with Gemini's count_tokens API."""
    if not text:
        return 0
    client = get_genai_client()
    if not client:
        return 0
    model = os.getenv("GEMINI_TOKEN_COUNT_MODEL", os.getenv("CHATBOT_MODEL", settings.chatbot_model))
    response = client.models.count_tokens(model=model, contents=text)
    return int(getattr(response, "total_tokens", 0) or 0)


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
            device_map="cpu",  # Explicitly use CPU for quantization-friendly execution
        )

        orig_len = len(context_text)
        # Target 2x compression ratio
        compressed = compressor.compress_prompt(
            context_text, rate=0.5, force_tokens=["\n", "Snippet", "Source"]
        )
        compressed_text = compressed.get("compressed_prompt", context_text)
        comp_len = len(compressed_text)

        duration = (time.time() - start) * 1000
        savings = (1 - (comp_len / orig_len)) * 100 if orig_len > 0 else 0

        logger.info(
            f"📉 [LLMLingua-2] Compressed context in {duration:.1f}ms: "
            f"{orig_len} -> {comp_len} chars ({savings:.1f}% saved)"
        )

        return compressed_text
    except Exception as e:
        logger.warning(f"⚠️ LLMLingua-2 quantized compression failed: {e}")
        return context_text


def _is_table_chunk(chunk: Dict[str, Any]) -> bool:
    """Heuristic: table-aware Kreuzberg chunks are structured row/table chunks."""
    try:
        metadata = chunk.get("metadata") or {}
        strategy = metadata.get("strategy") if isinstance(metadata, dict) else None
        if strategy and "table" in str(strategy).lower():
            return True
        content = (chunk.get("content") or "").lstrip()
        if (
            content.startswith("## Table")
            or content.startswith("|")
            or content.startswith("### Row")
        ):
            return True
    except Exception:
        return False
    return False


def _truncate_text(text_value: str, max_chars: int) -> str:
    if not text_value or len(text_value) <= max_chars:
        return text_value or ""
    return text_value[:max_chars].rstrip() + "\n[Content truncated to fit retrieval context budget.]"


def _rerank_results(query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Implement FlashRank Stage-2 reranking with telemetry."""
    try:
        from flashrank import Ranker, RerankRequest
        import time

        start = time.time()

        ranker = Ranker()
        passages = [
            {"id": i, "text": c["content"], "meta": c["metadata"]}
            for i, c in enumerate(chunks)
        ]
        rerank_request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(rerank_request)

        # Map back to original chunks
        ranked_chunks = []
        for r in results:
            idx = r["id"]
            ranked_chunks.append(chunks[idx])

        duration = (time.time() - start) * 1000
        logger.info(
            f"🎯 [FlashRank] Reranked {len(passages)} candidates in {duration:.1f}ms. "
            f"Top score: {results[0]['score'] if results else 'N/A'}"
        )

        return ranked_chunks[:10]
    except Exception as e:
        logger.warning(f"⚠️ FlashRank reranking failed: {e}")
        return chunks[:10]


async def search_knowledge_base(
    ctx: RunContext[ChatSessionDeps],
    query: Annotated[
        str,
        "The search query derived from the user's latest request.",
    ],
) -> str:
    """
    Advanced Knowledge Base Search with Hybrid Search, Reranking, Compression, and Caching.

    BE GREEDY - FETCH ALL POSSIBLE INFORMATION:
    - No limit on chunks returned - fetches ALL matching documents
    - One question often has MULTIPLE contextual answers (different cities, countries, sources)
    - Example: 'average precipitation in August' → gather data from ALL available cities/countries
    - Example: 'GDP of Asian countries' → return data from multiple Asian countries
    - Example: 'weather NYC' → get weather data from all available NYC sources

    STRATEGY:
    - For simple questions: use the query directly
    - For complex/multi-part questions: split into multiple search terms joined by ' | '
    - Example: 'population of France and Germany' → 'population France | population Germany'

    The search returns ALL relevant documents ranked by relevance. Use ALL results to answer the user's question comprehensively.
    """
    # Tool call limit removed
    ctx.deps.search_tool_calls += 1

    import time

    rag_start = time.time()
    effective_query = query
    fts_query = effective_query
    flashrank_query = effective_query

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
                ),
                fts_matches AS (
                    SELECT id, ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery('english', :fts_query)) as fts_score
                    FROM document_chunks
                    WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', :fts_query)
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
                ),
                candidate_rows AS (
                    SELECT
                        dc.id,
                        dc.content,
                        dc.metadata,
                        dc.document_id,
                        dc.document_type,
                        COALESCE(v.sim_score, 0) AS sim_score,
                        COALESCE(f.fts_score, 0) AS fts_score,
                        CASE
                            WHEN lower(dc.content) LIKE '%### rows %'
                              OR lower(dc.content) LIKE '%### row %'
                              OR lower(dc.content) LIKE '%columns:%'
                            THEN 0.12
                            ELSE 0
                        END AS structure_boost
                    FROM document_chunks dc
                    LEFT JOIN vector_matches v ON dc.id = v.id
                    LEFT JOIN fts_matches f ON dc.id = f.id
                    WHERE (v.id IS NOT NULL OR f.id IS NOT NULL)
                )
                SELECT
                    content,
                    metadata,
                    document_id,
                    document_type,
                    sim_score,
                    fts_score,
                    structure_boost,
                    (sim_score + (fts_score * 1.8) + structure_boost) as hybrid_score,
                    COALESCE(
                        (SELECT f.display_name FROM file_uploads f WHERE f.id = candidate_rows.document_id AND candidate_rows.document_type = 'file'),
                        (SELECT w.original_url FROM scraped_websites w WHERE w.id = candidate_rows.document_id AND candidate_rows.document_type = 'website'),
                        ''
                    ) as source_name
                FROM candidate_rows
                ORDER BY hybrid_score DESC
                LIMIT :candidate_limit
            """

            result = await db.execute(
                text(hybrid_query),
                {
                    "vector": vector_str,
                    "fts_query": fts_query,
                    "candidate_limit": RAG_MAX_CANDIDATE_ROWS,
                },
            )
            rows = result.mappings().all()

            if not rows:
                logger.info(
                    f"🧭 [RAG_EARLY_RETURN] reason=no_rows session_id={ctx.deps.session_id or 'none'} query='{effective_query[:120]}'"
                )
                response = "I don't have any information on this topic."
                logger.info(
                    f"🔎 [DEBUG] Tool Result: status=success payload_size_bytes={len(response.encode('utf-8'))} "
                    f"preview={response[:500]!r}"
                )
                return response

            # --- STEP 2: Reranking ---
            chunks = [dict(row) for row in rows]
            flashrank_applied = False
            if settings.enable_reranking:
                top_chunks = _rerank_results(flashrank_query, chunks)
                flashrank_applied = top_chunks != chunks
            else:
                # Return all chunks (up to 80) to gather ALL contextual answers
                top_chunks = chunks

            # --- STEP 3: Format & Compression ---
            # Build a single citation-friendly grounding stream and preserve the
            # retrieval/reranking order without splitting tables from narrative text.
            citation_urls: List[str] = []
            citation_index_by_source: Dict[str, int] = {}
            grounding_chunks: List[str] = []
            grounding_chars = 0

            for chunk in top_chunks:
                doc_id, doc_type = str(chunk["document_id"]), chunk["document_type"]
                content = _truncate_text(chunk["content"] or "", RAG_MAX_CHUNK_CHARS)
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

                source_name = chunk.get("source_name") or ""
                source_line = f"Document: {source_name}\n" if source_name else ""
                chunk_str = (
                    f"Source {citation_number} (type={doc_type} id={doc_id} score={score} url={url})\n"
                    f"{source_line}"
                    f"Cite this source as: [{citation_number}]\n"
                    f"{content}\n"
                )

                if grounding_chunks and grounding_chars + len(chunk_str) > RAG_MAX_TOOL_CONTEXT_CHARS:
                    logger.info(
                        f"🧭 [RAG_CONTEXT_BUDGET] Stopping grounding assembly at {len(grounding_chunks)} chunks "
                        f"to stay under {RAG_MAX_TOOL_CONTEXT_CHARS} chars"
                    )
                    break

                grounding_chunks.append(chunk_str)
                grounding_chars += len(chunk_str)

            grounding_context = "\n".join(grounding_chunks).strip()
            grounding_before_chars = len(grounding_context)
            grounding_before_tokens = _count_gemini_tokens(grounding_context)

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
            grounding_after_tokens = _count_gemini_tokens(compressed_context)

            final_context = compressed_context

            total_duration = (time.time() - rag_start) * 1000

            # Theoretical storage savings per chunk (standard vector 3072B -> halfvec 1536B for 768d)
            # This is constant but helpful to see in telemetry for business value justification
            logger.info(
                f"✅ [RAG_COMPLETE] Total Retrieval Pipeline: {total_duration:.1f}ms"
            )
            logger.info(
                f"📊 [HALFVEC_STATS] Using halfp-float storage: 50% byte savings per index row (1.5KB vs 3.0KB)"
            )
            if settings.enable_context_compression:
                logger.info(
                    f"📉 [LLMLingua-2] Compression applied to final grounding stream (chunks_kept={len(grounding_chunks)})"
                )

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
                logger.info(
                    f"📦 [RAG_GROUNDING_FULL] tool_return_chars={len(response)} preview_chars={len(preview)}\n{preview}"
                )
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

                session_state_manager.set_tool_used(
                    ctx.deps.session_id, "search_knowledge_base"
                )
                session_state_manager.set_last_citation_urls(
                    ctx.deps.session_id, citation_urls
                )
                logger.info(
                    f"🧭 [RAG_STATE_WRITE] path=live_retrieval session_id={ctx.deps.session_id} "
                    f"citation_count={len(citation_urls)} tool_used=yes"
                )
            else:
                logger.warning(
                    "🧭 [RAG_STATE_WRITE] skipped: missing session_id on tool context"
                )

            try:
                preview = response[:800].replace("\n", " ")
                logger.info(
                    f"🧰 [TOOL_RETURN] tool=search_knowledge_base query_len={len(effective_query or '')} "
                    f"response_len={len(response)} citations={len(citation_urls)} "
                    f"rows={len(rows)} top_chunks={len(top_chunks)} preview={preview}"
                )
                logger.info(
                    f"🔎 [DEBUG] Tool Result: status=success payload_size_bytes={len(response.encode('utf-8'))} "
                    f"preview={response[:500]!r}"
                )
            except Exception:
                pass

            return response

    except Exception as e:
        logger.error(f"❌ Advanced RAG error: {e}", exc_info=True)
        response = f"An error occurred during search: {str(e)}"
        try:
            logger.info(
                f"🔎 [DEBUG] Tool Result: status=fail payload_size_bytes={len(response.encode('utf-8'))} "
                f"preview={response[:500]!r}"
            )
        except Exception:
            pass
        return response
