"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""

from typing import List, Dict, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "chatbot-orchestration")


def gemini_pricing_for_model(model: str) -> Dict[str, float]:
    """Return paid-tier USD per 1M token rates for Gemini chat usage."""
    normalized_model = (model or "").lower()

    if "2.5-flash-lite" in normalized_model:
        return {
            "standard_input": 0.10,
            "completion": 0.40,
            "cache_read": 0.025,
            "cache_write": 0.0,
        }

    if "1.5-flash" in normalized_model:
        return {
            "standard_input": 0.075,
            "completion": 0.30,
            "cache_read": 0.01875,
            "cache_write": 0.0,
        }

    # Default to the rate card used for the current chat models
    # such as gemini-2.5-flash-lite and gemini-2.0-flash.
    return {
        "standard_input": 0.10,
        "completion": 0.40,
        "cache_read": 0.01,
        "cache_write": 0.10,
    }


class TokenDAO:
    """Data access object for token operations"""

    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def update_llm_usage(
        self, provider: str, total_tokens: int, default_limit: int = 20000
    ):
        """
        Update LLM token usage for a provider using PG17+ MERGE with RETURNING.

        MERGE provides better semantics than ON CONFLICT:
        - Returns merge_action() to distinguish INSERT vs UPDATE
        - Clearer intent when modifying multiple conditions
        - Enables audit trail logging of actual action taken

        Example log output:
        - "Provider gpt-4: first use (INSERT)"
        - "Provider gpt-4: +150 tokens (UPDATE)"
        """
        logger.info(
            f"🔍 update_llm_usage called - provider: {provider}, total_tokens: {total_tokens}"
        )
        query = """
            MERGE INTO llm_providers AS target
            USING (VALUES (CAST(:provider AS VARCHAR), CAST(:total_tokens AS BIGINT), CAST(:default_limit AS BIGINT)))
                  AS source(provider_name, token_used, token_limit)
            ON target.provider_name = source.provider_name
            WHEN MATCHED THEN
                UPDATE SET token_used = target.token_used + source.token_used, updated_at = NOW()
            WHEN NOT MATCHED THEN
                INSERT (provider_name, token_used, token_limit, is_active)
                VALUES (source.provider_name, source.token_used, source.token_limit, true)
            RETURNING merge_action() AS action, target.provider_name, target.token_used
        """
        params = {
            "provider": provider,
            "total_tokens": total_tokens,
            "default_limit": default_limit,
        }
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                await session.commit()

                # Log the actual action taken (INSERT or UPDATE)
                if row:
                    action = row.action
                    logger.log_db_query(query, params, f"MERGE {action}")
                    logger.info(
                        f"✅ update_llm_usage completed - provider: {provider}, "
                        f"action: {action}, tokens: {row.token_used}"
                    )
                else:
                    logger.log_db_query(query, params, "MERGE")
                    logger.info(
                        f"✅ update_llm_usage completed - provider: {provider}, total_tokens: {total_tokens}"
                    )
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def save_token_usage(
        self,
        session_id: str,
        message_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        api_call_type: str = None,
        request_metadata: dict = None,
    ) -> bool:
        """Save token usage record and update llm_providers table"""
        import json

        logger.info(
            f"🔍 save_token_usage called - session: {session_id}, total_tokens: {total_tokens}"
        )
        logger.info(
            f"[PARAM] request_metadata type: {type(request_metadata)}, value: {request_metadata}"
        )

        # PG18: id IS the UUIDv7 PK — verify session exists
        session_query = (
            "SELECT id FROM chat_sessions WHERE id = CAST(:session_id AS UUID)"
        )
        try:
            async with get_db_session() as session:
                logger.log_db_operation(session_query, session_id)
                session_record = (
                    await session.execute(
                        text(session_query), {"session_id": session_id}
                    )
                ).fetchone()
                logger.log_db_query(
                    session_query, {"session_id": session_id}, session_record
                )

                uuid_session_id = str(session_record.id) if session_record else None
                # PG18: session_id/message_id are UUIDs — use the passed message_id
                # and ensure it's a string if not None
                uuid_message_id = str(message_id) if message_id else None

                logger.info(
                    f"🔍 Updating llm_providers - provider: {provider}, total_tokens: {total_tokens}"
                )
                # First, update the llm_providers table with total tokens
                await self.update_llm_usage(provider, total_tokens)

                # Then, log the detailed token usage using model-aware Gemini pricing.
                cache_read = 0
                cache_write = 0
                if request_metadata:
                    cache_read = request_metadata.get("cache_read_tokens", 0)
                    cache_write = request_metadata.get("cache_write_tokens", 0)

                # prompt_tokens includes cache_read
                standard_input = max(0, (prompt_tokens or 0) - (cache_read or 0))
                pricing = (
                    gemini_pricing_for_model(model)
                    if provider == "gemini"
                    else {
                        "standard_input": 0.0,
                        "completion": 0.0,
                        "cache_read": 0.0,
                        "cache_write": 0.0,
                    }
                )
                cost_usd = (
                    (standard_input * float(pricing.get("standard_input", 0.0) or 0.0))
                    + (cache_read * float(pricing.get("cache_read", 0.0) or 0.0))
                    + (completion_tokens * float(pricing.get("completion", 0.0) or 0.0))
                    + (cache_write * float(pricing.get("cache_write", 0.0) or 0.0))
                ) / 1_000_000.0

                # Keep a coarse cents value for the legacy column, and store exact USD
                # in request_metadata for transparent sub-cent reporting.
                cost_cents = round(cost_usd * 100.0)
                if request_metadata is None:
                    request_metadata = {}
                request_metadata.update(
                    {
                        "cost_usd": cost_usd,
                        "billing_breakdown": {
                            "prompt_tokens": {
                                "tokens": int(prompt_tokens or 0),
                                "billing_class": "billable",
                                "source": "provider_usage",
                            },
                            "completion_tokens": {
                                "tokens": int(completion_tokens or 0),
                                "billing_class": "billable",
                                "source": "provider_usage",
                            },
                            "cache_read_tokens": {
                                "tokens": int(cache_read or 0),
                                "billing_class": "cached",
                                "source": "provider_usage_metadata",
                            },
                            "cache_write_tokens": {
                                "tokens": int(cache_write or 0),
                                "billing_class": "cached",
                                "source": "provider_usage_metadata",
                            },
                        },
                        "total_token_source": "provider_total_tokens",
                        "pricing_usd_per_1m": pricing,
                    }
                )

                query = """
                    INSERT INTO token_usage_log (
                        session_id, message_id, provider, model, prompt_tokens,
                        completion_tokens, total_tokens, cost_cents, api_call_type, request_metadata
                    ) VALUES (
                        CAST(:session_id AS UUID), CAST(:message_id AS UUID), 
                        :provider, :model, :prompt_tokens,
                        :completion_tokens, :total_tokens, :cost_cents, :api_call_type, :request_metadata
                    )
                """

                # Convert request_metadata dict to JSON string for PostgreSQL
                metadata_json = (
                    json.dumps(request_metadata) if request_metadata else None
                )
                logger.info(
                    f"[TRANSFORM] request_metadata converted to JSON: {metadata_json}"
                )

                params = {
                    "session_id": uuid_session_id,
                    "message_id": uuid_message_id,
                    "provider": provider,
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost_cents": cost_cents,
                    "api_call_type": api_call_type,
                    "request_metadata": metadata_json,
                }

                logger.log_db_operation(query, params)
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "INSERT 1")
                logger.info(
                    f"✅ save_token_usage completed - session: {session_id}, total_tokens: {total_tokens}"
                )
                return True

        except Exception as e:
            logger.error(f"❌ Error saving token usage: {e}", exc_info=True)
            return False

    async def get_token_usage(self, session_id: str) -> List[Dict[str, Any]]:
        """Get token usage for a session"""
        # PG18: id IS the UUIDv7 PK — verify session exists
        session_query = (
            "SELECT id FROM chat_sessions WHERE id = CAST(:session_id AS UUID)"
        )
        try:
            async with get_db_session() as session:
                logger.log_db_operation(session_query, session_id)
                session_record = (
                    await session.execute(
                        text(session_query), {"session_id": session_id}
                    )
                ).fetchone()
                logger.log_db_query(
                    session_query, {"session_id": session_id}, session_record
                )

                if not session_record:
                    return []

                uuid_session_id = str(session_record.id)

                query = """
                    SELECT id, session_id, message_id, provider, model, prompt_tokens,
                           completion_tokens, total_tokens, cost_cents, api_call_type,
                           request_metadata, created_at, updated_at
                    FROM token_usage_log
                    WHERE session_id = :session_id
                    ORDER BY id DESC
                """
                logger.log_db_operation(query, uuid_session_id)
                result = (
                    await session.execute(text(query), {"session_id": uuid_session_id})
                ).fetchall()
                logger.log_db_query(query, {"session_id": uuid_session_id}, result)
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.log_db_query("get_token_usage", {"session_id": session_id}, error=e)
            return []
