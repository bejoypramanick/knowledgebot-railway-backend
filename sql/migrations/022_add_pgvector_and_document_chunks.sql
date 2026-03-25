-- ==============================================================================
-- Add pgvector Extension and Document Chunks Table
-- ==============================================================================
-- Description: Enables the pgvector extension for vector similarity search
-- and creates the document_chunks table to store semantic chunks and their embeddings.
-- ==============================================================================

-- 1. Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create the document_chunks table
CREATE TABLE IF NOT EXISTS public.document_chunks (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Link to the source document (either a file upload or scraped website)
    file_id uuid REFERENCES public.file_uploads(id) ON DELETE CASCADE,
    website_id uuid REFERENCES public.scraped_websites(id) ON DELETE CASCADE,
    
    -- Ensure chunk belongs to exactly one source
    CONSTRAINT chunk_source_check CHECK (
        (file_id IS NOT NULL AND website_id IS NULL) OR
        (file_id IS NULL AND website_id IS NOT NULL)
    ),
    
    -- Chunk metadata and content
    chunk_index integer NOT NULL,
    content text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    
    -- Embedding vector (1536 dimensions is standard for OpenAI / common open source models)
    -- This dimension might need to change if using a model with a different output size
    embedding vector(1536), 
    
    created_at timestamp with time zone DEFAULT now()
);

-- 3. Add table comments
COMMENT ON TABLE public.document_chunks IS 'Stores semantic text chunks and their vector embeddings for RAG retrieval';
COMMENT ON COLUMN public.document_chunks.file_id IS 'Reference to the uploaded file source';
COMMENT ON COLUMN public.document_chunks.website_id IS 'Reference to the scraped website source';
COMMENT ON COLUMN public.document_chunks.chunk_index IS 'Sequential index of the chunk within the document';
COMMENT ON COLUMN public.document_chunks.content IS 'The plaintext or markdown content of the chunk';
COMMENT ON COLUMN public.document_chunks.metadata IS 'JSON metadata (e.g., page number, headers, table data)';
COMMENT ON COLUMN public.document_chunks.embedding IS 'The vector embedding of the chunk content';

-- 4. Create an HNSW index for fast approximate nearest neighbor search
-- Note: 'vector_cosine_ops' optimizes for cosine distance, which is standard for most embeddings
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
ON public.document_chunks 
USING hnsw (embedding vector_cosine_ops);

-- 5. Create indexes on foreign keys to optimize cascading deletes and lookups
CREATE INDEX IF NOT EXISTS idx_document_chunks_file_id ON public.document_chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_website_id ON public.document_chunks(website_id);
