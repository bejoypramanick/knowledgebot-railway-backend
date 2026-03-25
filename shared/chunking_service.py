import os
from typing import List, Dict, Any, Optional
from shared.otel_logger import get_otel_logger
from shared.embeddings import batch_generate_embeddings

logger = get_otel_logger("chunking_service", "shared")

try:
    from chonkie import SemanticChunker
    CHONKIE_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ Chonkie library not found. Falling back to basic chunking.")
    CHONKIE_AVAILABLE = False

class HierarchicalSemanticChunker:
    """
    Service for advanced hierarchical semantic chunking using Chonkie.
    """
    def __init__(
        self, 
        chunk_size: int = 800, 
        chunk_overlap: int = 150,
        threshold: float = 0.5,
        skip_window: int = 1
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.threshold = threshold
        self.skip_window = skip_window
        
        if CHONKIE_AVAILABLE:
            # We wrap our batch_generate_embeddings to match Chonkie's expected interface if needed
            # For now, we'll use a simpler approach if Chonkie allows passing a callback
            # or we use one of its built-in providers if configured.
            
            # Since we want to use our provider-agnostic embeddings, we'll use a custom embedder wrapper
            class CustomEmbedder:
                def __init__(self):
                    pass
                def embed(self, texts: List[str]) -> List[List[float]]:
                    # Chonkie expects a synchronous call or we use a wrapper
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    if loop.is_running():
                        # This is tricky in async environments. 
                        # We might need to use a dedicated thread or similar.
                        # However, for Celery workers, it's usually okay.
                        import nest_asyncio
                        nest_asyncio.apply()
                        return asyncio.run(batch_generate_embeddings(texts))
                    else:
                        return asyncio.run(batch_generate_embeddings(texts))

            self.chunker = SemanticChunker(
                embedding_model="sentence-transformers/all-minilm-l6-v2", # Default fast local model for boundaries
                threshold=self.threshold,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                mode="sdpm" if self.skip_window > 0 else "regular"
            )
        else:
            self.chunker = None

    async def chunk_text(self, text: str, filename: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Chunks text using Chonkie's semantic strategy.
        Returns a list of dicts with 'text' and 'metadata'.
        """
        if not text:
            return []

        if not CHONKIE_AVAILABLE or not self.chunker:
            return self._basic_fallback_chunking(text, filename)

        try:
            logger.info(f"🧩 [CHONKIE] Chunking text ({len(text)} chars) semantically...")
            start_time = os.times().elapsed
            
            # Chonkie's chunk() method
            chunks = self.chunker.chunk(text)
            
            result = []
            for i, chunk in enumerate(chunks):
                result.append({
                    "text": chunk.text,
                    "metadata": {
                        "chunk_index": i,
                        "chunk_size": len(chunk.text),
                        "filename": filename,
                        "strategy": "chonkie_semantic_sdpm"
                    }
                })
            
            logger.info(f"✅ [CHONKIE] Generated {len(result)} semantic chunks.")
            return result
            
        except Exception as e:
            logger.error(f"❌ [CHONKIE] Error during semantic chunking: {e}")
            return self._basic_fallback_chunking(text, filename)

    def _basic_fallback_chunking(self, text: str, filename: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fallback to simple recursive chunking if Chonkie fails or is unavailable."""
        logger.warning("⚠️ Falling back to basic recursive chunking.")
        chunks = []
        # Simple split by paragraph/size
        paragraphs = text.split('\n\n')
        current_chunk = ""
        
        for p in paragraphs:
            if len(current_chunk) + len(p) < self.chunk_size:
                current_chunk += p + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        return [
            {
                "text": msg,
                "metadata": {"chunk_index": i, "filename": filename, "strategy": "basic_fallback"}
            } for i, msg in enumerate(chunks)
        ]

# Global instance with default settings
chunking_service = HierarchicalSemanticChunker()
