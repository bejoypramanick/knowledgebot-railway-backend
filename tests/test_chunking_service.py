import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

async def test_chunking_service():
    print("🚀 Testing Chunking Service...")
    
    # Mock Chonkie if not installed to test fallback
    # But let's try to see if we can test the real thing if it's there
    from shared.chunking_service import chunking_service
    
    test_text = """
# Introduction
This is a test document for hierarchical semantic chunking.
It has multiple paragraphs and sections.

## Section 1: Semantic Context
Semantic chunking should group these sentences together because they are about the same topic.
The topic here is how LLMs process information in chunks.
If the similarity is high, they stay together.

## Section 2: Structure
This section is different. It discusses document structure.
Headers, lists, and tables are important for understanding.
| Key | Value |
| --- | --- |
| Provider | Chonkie |
| Strategy | SDPM |

## Conclusion
Final thoughts on the integration.
    """
    
    print(f"📄 Input text length: {len(test_text)} chars")
    
    chunks = await chunking_service.chunk_text(test_text, filename="test.md")
    
    print(f"✅ Generated {len(chunks)} chunks")
    for i, chunk in enumerate(chunks):
        print(f"\n--- Chunk {i} ({chunk['metadata']['strategy']}) ---")
        print(chunk['text'][:100] + "...")
        print(f"Metadata: {chunk['metadata']}")

if __name__ == "__main__":
    asyncio.run(test_chunking_service())
