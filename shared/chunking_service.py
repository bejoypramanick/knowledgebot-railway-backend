import os
from typing import List, Dict, Any, Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chunking_service", "shared")

try:
    from chonkie import SemanticChunker
    CHONKIE_AVAILABLE = True
except ImportError:
    SemanticChunker = None
    CHONKIE_AVAILABLE = False

class HierarchicalSemanticChunker:
    """
    Service for advanced hierarchical semantic chunking using Chonkie.
    """
    def __init__(
        self, 
        chunk_size: int = int(os.getenv("CHONKIE_CHUNK_SIZE", "350")),
        chunk_overlap: int = int(os.getenv("CHONKIE_CHUNK_OVERLAP", "75")),
        threshold: float = float(os.getenv("CHONKIE_THRESHOLD", "0.5")),
        skip_window: int = int(os.getenv("CHONKIE_SKIP_WINDOW", "1"))
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.threshold = threshold
        self.skip_window = skip_window
        
        if not CHONKIE_AVAILABLE or SemanticChunker is None:
            raise RuntimeError("Chonkie is required for semantic chunking but is not installed.")

        self.chunker = SemanticChunker(
            embedding_model="sentence-transformers/all-minilm-l6-v2",
            threshold=self.threshold,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            mode="sdpm" if self.skip_window > 0 else "regular"
        )

    async def chunk_text(self, text: str, filename: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Chunks text using Chonkie's semantic strategy.
        Returns a list of dicts with 'text' and 'metadata'.
        """
        if not text:
            return []

        try:
            logger.info(f"🧩 [CHONKIE] Chunking text ({len(text)} chars) semantically...")
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
            raise

# Global instance with default settings
chunking_service = HierarchicalSemanticChunker()
