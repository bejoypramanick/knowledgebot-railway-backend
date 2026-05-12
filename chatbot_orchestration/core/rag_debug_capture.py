"""
Per-turn RAG debug stage capture and S3 artifact publishing.

This captures the main user-visible stages of a chat turn:
- initial model input context
- RAG tool search input
- RAG tool response returned to the model
- post-RAG model input context
- final model response

Artifacts are overwritten per session by clearing the session prefix on each
new debug-enabled chat turn before fresh files are uploaded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "chatbot-orchestration")


@dataclass
class RagDebugTurn:
    session_id: str
    enabled: bool = False
    current_user_message: str = ""
    conversation_history: List[Any] = field(default_factory=list)
    cache_name: Optional[str] = None
    model_name: Optional[str] = None
    rag_queries: List[str] = field(default_factory=list)
    rag_responses: List[str] = field(default_factory=list)
    rag_raw_rows: List[Any] = field(default_factory=list)
    rag_raw_chunks: List[Any] = field(default_factory=list)
    rag_top_chunks: List[Any] = field(default_factory=list)
    rag_grounding_chunks: List[str] = field(default_factory=list)
    rag_final_contexts: List[str] = field(default_factory=list)
    final_response: str = ""


_turns: Dict[str, RagDebugTurn] = {}


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def begin_turn(
    session_id: str,
    *,
    enabled: bool,
    current_user_message: str,
    conversation_history: Optional[List[Any]] = None,
    cache_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> None:
    _turns[session_id] = RagDebugTurn(
        session_id=session_id,
        enabled=enabled,
        current_user_message=current_user_message or "",
        conversation_history=conversation_history or [],
        cache_name=cache_name,
        model_name=model_name,
    )


def get_turn(session_id: str) -> Optional[RagDebugTurn]:
    return _turns.get(session_id)


def update_turn_context(
    session_id: str,
    *,
    conversation_history: Optional[List[Any]] = None,
    cache_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> None:
    turn = _turns.get(session_id)
    if not turn:
        return
    if conversation_history is not None:
        turn.conversation_history = conversation_history
    if cache_name is not None:
        turn.cache_name = cache_name
    if model_name is not None:
        turn.model_name = model_name


def add_rag_query(session_id: str, *, query: str, tool_name: str = "search_knowledge_base") -> None:
    turn = _turns.get(session_id)
    if not turn or not turn.enabled:
        return
    turn.rag_queries.append(query or "")


def add_rag_response(
    session_id: str,
    *,
    response: str,
    tool_name: str = "search_knowledge_base",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    turn = _turns.get(session_id)
    if not turn or not turn.enabled:
        return
    turn.rag_responses.append(response or "")


def add_rag_raw_stage(
    session_id: str,
    *,
    rows: Optional[List[Any]] = None,
    chunks: Optional[List[Any]] = None,
    top_chunks: Optional[List[Any]] = None,
    grounding_chunks: Optional[List[str]] = None,
    final_context: Optional[str] = None,
) -> None:
    turn = _turns.get(session_id)
    if not turn or not turn.enabled:
        return
    if rows is not None:
        turn.rag_raw_rows.append(rows)
    if chunks is not None:
        turn.rag_raw_chunks.append(chunks)
    if top_chunks is not None:
        turn.rag_top_chunks.append(top_chunks)
    if grounding_chunks is not None:
        turn.rag_grounding_chunks.extend(grounding_chunks)
    if final_context is not None:
        turn.rag_final_contexts.append(final_context)


def set_final_response(session_id: str, response: str) -> None:
    turn = _turns.get(session_id)
    if not turn:
        return
    turn.final_response = response or ""


def clear_turn(session_id: str) -> None:
    _turns.pop(session_id, None)


def _turn_prefix(session_id: str) -> str:
    return f"rag-stage-debug/{session_id}/"


def _stage_objects(turn: RagDebugTurn) -> List[Dict[str, Any]]:
    post_rag_payload = {
        "current_user_message": turn.current_user_message,
        "conversation_history": turn.conversation_history,
        "rag_tool_returns": turn.rag_responses,
    }
    return [
        {
            "label": "Current User Message",
            "filename": "01_current_user_message.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": (turn.current_user_message or "").encode("utf-8"),
        },
        {
            "label": "Conversation History",
            "filename": "02_conversation_history.json",
            "content_type": "application/json",
            "body": _json_bytes(turn.conversation_history),
        },
        {
            "label": "RAG Search Input",
            "filename": "03_rag_search_input.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": ("\n\n---\n\n".join(turn.rag_queries) if turn.rag_queries else "").encode("utf-8"),
        },
        {
            "label": "RAG Raw DB Rows",
            "filename": "04_rag_raw_db_rows.json",
            "content_type": "application/json",
            "body": _json_bytes(turn.rag_raw_rows),
        },
        {
            "label": "RAG Candidate Chunks",
            "filename": "05_rag_candidate_chunks.json",
            "content_type": "application/json",
            "body": _json_bytes(turn.rag_raw_chunks),
        },
        {
            "label": "RAG Top Chunks",
            "filename": "06_rag_top_chunks.json",
            "content_type": "application/json",
            "body": _json_bytes(turn.rag_top_chunks),
        },
        {
            "label": "RAG Grounding Chunks",
            "filename": "07_rag_grounding_chunks.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": ("\n\n---\n\n".join(turn.rag_grounding_chunks) if turn.rag_grounding_chunks else "").encode("utf-8"),
        },
        {
            "label": "RAG Final Context",
            "filename": "08_rag_final_context.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": ("\n\n---\n\n".join(turn.rag_final_contexts) if turn.rag_final_contexts else "").encode("utf-8"),
        },
        {
            "label": "RAG Search Output",
            "filename": "09_rag_search_output.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": ("\n\n---\n\n".join(turn.rag_responses) if turn.rag_responses else "").encode("utf-8"),
        },
        {
            "label": "Model Input (After RAG)",
            "filename": "10_model_input_after_rag.json",
            "content_type": "application/json",
            "body": _json_bytes(post_rag_payload),
        },
        {
            "label": "Final Model Response",
            "filename": "11_final_model_response.txt",
            "content_type": "text/plain; charset=utf-8",
            "body": (turn.final_response or "").encode("utf-8"),
        },
    ]


async def cleanup_session_stage_files(session_id: str) -> None:
    from .s3_client import get_bucket_name, get_s3_client

    s3_client = get_s3_client()
    bucket_name = get_bucket_name()
    if not s3_client or not bucket_name:
        return

    prefix = _turn_prefix(session_id)
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        keys: List[str] = []
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                key = obj.get("Key")
                if key:
                    keys.append(key)
        if not keys:
            return
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
        logger.info(
            f"🧹 Cleared {len(keys)} prior RAG stage debug files from S3 for session={session_id[:16]}"
        )
    except Exception as e:
        logger.warning(f"Failed to clear prior RAG stage files for {session_id}: {e}")


async def publish_turn_stage_files(session_id: str) -> List[Dict[str, str]]:
    from .s3_client import get_bucket_name, get_s3_client

    turn = _turns.get(session_id)
    if not turn or not turn.enabled:
        return []

    s3_client = get_s3_client()
    bucket_name = get_bucket_name()
    if not s3_client or not bucket_name:
        return []

    await cleanup_session_stage_files(session_id)

    prefix = _turn_prefix(session_id)
    links: List[Dict[str, str]] = []
    for stage in _stage_objects(turn):
        key = prefix + stage["filename"]
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=stage["body"],
            ContentType=stage["content_type"],
            ContentDisposition=f'attachment; filename="{stage["filename"]}"',
        )
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=3600,
        )
        links.append({"label": stage["label"], "url": url, "key": key})
    logger.info(
        f"📁 Published {len(links)} RAG stage debug files for session={session_id[:16]}"
    )
    return links
