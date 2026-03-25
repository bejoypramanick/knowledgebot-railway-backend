import json
from typing import List, Dict, Any, Optional
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
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

vector_dao = VectorDAO()
