-- Migration to add token_usage_log table for detailed token tracking
-- This allows correlating token usage with specific API calls and responses

-- Add the token_usage_log table
CREATE TABLE IF NOT EXISTS token_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL, -- 'gemini'
    model VARCHAR(100), -- specific model used
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost_cents INTEGER DEFAULT 0, -- cost in cents (for future billing)
    api_call_type VARCHAR(50), -- 'chat', 'rag', 'sentiment', 'summary', 'suggested_messages'
    request_metadata JSONB, -- additional request details
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_token_usage_log_session ON token_usage_log(session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider ON token_usage_log(provider);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_created_at ON token_usage_log(created_at DESC);

-- Add comment
COMMENT ON TABLE token_usage_log IS 'Detailed token usage log for correlating usage with specific API calls';

COMMIT;