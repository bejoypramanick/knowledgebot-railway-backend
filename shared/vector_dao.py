import json
from typing import List, Dict, Any, Optional, Sequence
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session, execute_autocommit
from sqlalchemy import text

logger = get_otel_logger("vector_dao", "shared")

class VectorDAO:
    """DAO for managing vector embeddings in the document_chunks table."""
    
    @staticmethod
    async def batch_insert_chunks(
        chunks: List[Dict[str, Any]], 
        document_id: str,
        document_type: str
    ) -> bool:
        """
        Insert a batch of semantic chunks and their embeddings into the database.
        
        Args:
            chunks: List of chunk dictionaries containing 'text', 'embedding', and optional 'metadata'
            document_id: The UUID of the source document (file or website)
            document_type: 'file' or 'website'
            
        Returns:
            bool: True if successful, False otherwise.
        """
        if not chunks:
            logger.warning("No chunks provided to batch_insert_chunks")
            return False
            
        if not document_id or not document_type:
            logger.error("Must provide both document_id and document_type for chunks")
            return False
            
        try:
            async with get_db_session() as db:
                # Prepare data for insertion
                values = []
                for i, chunk in enumerate(chunks):
                    content = chunk.get("text") or chunk.get("content", "")
                    if not content:
                        continue
                        
                    embedding = chunk.get("embedding") or chunk.get("vector")
                    embedding_str = None
                    if embedding and isinstance(embedding, list):
                        embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"
                        
                    metadata = chunk.get("metadata", {})
                    if "chunk_index" not in metadata:
                        metadata["chunk_index"] = i
                        
                    values.append({
                        "document_id": document_id,
                        "document_type": document_type,
                        "chunk_index": i,
                        "content": content,
                        "metadata": json.dumps(metadata),
                        "embedding": embedding_str
                    })
                
                if not values:
                    logger.warning("No valid text found in any provided chunks")
                    return False
                
                query = text("""
                    INSERT INTO document_chunks (
                        document_id, document_type, chunk_index, content, metadata, embedding
                    ) VALUES (
                        :document_id, :document_type, :chunk_index, :content, 
                        CAST(:metadata AS jsonb), 
                        CAST(:embedding AS halfvec)
                    )
                """)
                
                await db.execute(query, values)
                await db.commit()
                
                logger.info(f"✅ Successfully inserted {len(values)} chunks into document_chunks for {document_type} {document_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to batch insert chunks: {e}", exc_info=True)
            return False

    @staticmethod
    async def delete_chunks_for_documents(document_ids: Sequence[str], document_type: str) -> int:
        """Hard delete chunks for one or more documents. Returns deleted row count."""
        ids = [str(i) for i in document_ids if i]
        if not ids:
            return 0
        if document_type not in ("file", "website"):
            raise ValueError("document_type must be 'file' or 'website'")

        async with get_db_session() as db:
            result = await db.execute(
                text(
                    """
                    DELETE FROM document_chunks
                    WHERE document_type = :document_type
                      AND document_id = ANY(:document_ids)
                    """
                ),
                {"document_type": document_type, "document_ids": ids},
            )
            await db.commit()
            deleted = int(result.rowcount or 0)
            logger.info(f"🗑️ Deleted {deleted} chunks for {document_type} documents: {len(ids)} ids")
            return deleted

    @staticmethod
    async def delete_chunks_for_document(document_id: str, document_type: str) -> int:
        return await VectorDAO.delete_chunks_for_documents([document_id], document_type)

    @staticmethod
    async def get_document_chunk_metrics(document_id: str, document_type: str) -> Dict[str, int]:
        """Return stored chunk size plus text metrics for a document."""
        if document_type not in ("file", "website"):
            raise ValueError("document_type must be 'file' or 'website'")

        async with get_db_session() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            COALESCE(SUM(pg_column_size(content)), 0) AS size_bytes,
                            COALESCE(SUM(char_length(content)), 0) AS char_count,
                            COALESCE(
                                SUM(
                                    CASE
                                        WHEN btrim(content) = '' THEN 0
                                        ELSE cardinality(regexp_split_to_array(btrim(content), E'\\s+'))
                                    END
                                ),
                                0
                            ) AS word_count
                        FROM document_chunks
                        WHERE document_id = :document_id
                          AND document_type = :document_type
                        """
                    ),
                    {"document_id": document_id, "document_type": document_type},
                )
            ).mappings().first()

        return {
            "size_bytes": int(row["size_bytes"] or 0) if row else 0,
            "char_count": int(row["char_count"] or 0) if row else 0,
            "word_count": int(row["word_count"] or 0) if row else 0,
        }

    @staticmethod
    async def clear_all_chunks() -> int:
        """HARD DELETE all records from the document_chunks table. Use with caution!"""
        try:
            logger.info("🗑️ [VECTOR_DAO] Emptying document_chunks table (total reset)...")
            async with get_db_session() as session:
                result = await session.execute(text("DELETE FROM public.document_chunks"))
                count = result.rowcount or 0
                await session.commit()
                logger.info(f"✅ [VECTOR_DAO_SUCCESS] Cleared {count} vector chunks")
                return count
        except Exception as e:
            logger.error(f"❌ [VECTOR_DAO_ERROR] Failed to clear document_chunks: {e}")
            return 0

    @staticmethod
    async def vacuum_document_chunks() -> None:
        """Run VACUUM (ANALYZE) for document_chunks in autocommit mode."""
        try:
            await execute_autocommit("VACUUM (ANALYZE) public.document_chunks")
            logger.info("🧹 VACUUM (ANALYZE) completed for public.document_chunks")
        except Exception as e:
            # We don't want deletions to fail if VACUUM fails.
            logger.warning(f"⚠️ VACUUM (ANALYZE) failed for public.document_chunks: {e}")

vector_dao = VectorDAO()
