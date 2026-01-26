-- Add caching columns to chat_sessions table for optimized agent management
-- This enables storing FileSearchStore and cached content IDs for session optimization

-- Check if columns exist before adding them
DO $$
BEGIN
    -- Add file_search_store_id column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_sessions' 
        AND column_name = 'file_search_store_id'
    ) THEN
        ALTER TABLE chat_sessions 
        ADD COLUMN file_search_store_id VARCHAR(255);
        
        CREATE INDEX idx_chat_sessions_file_search_store_id 
        ON chat_sessions(file_search_store_id);
        
        RAISE NOTICE 'Added file_search_store_id column to chat_sessions';
    END IF;
    
    -- Add cached_content_id column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'chat_sessions' 
        AND column_name = 'cached_content_id'
    ) THEN
        ALTER TABLE chat_sessions 
        ADD COLUMN cached_content_id VARCHAR(255);
        
        CREATE INDEX idx_chat_sessions_cached_content_id 
        ON chat_sessions(cached_content_id);
        
        RAISE NOTICE 'Added cached_content_id column to chat_sessions';
    END IF;
END $$;

-- Add comments for documentation
COMMENT ON COLUMN chat_sessions.file_search_store_id IS 'Gemini FileSearchStore ID for RAG optimization';
COMMENT ON COLUMN chat_sessions.cached_content_id IS 'Gemini cached content ID for 90% cost discount';

-- Grant permissions to postgres user
GRANT USAGE ON SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
