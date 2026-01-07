-- Database Migrations for Chatbot Configuration Features
-- Run these migrations on your database

-- 1. Human Agents Table
CREATE TABLE IF NOT EXISTS human_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'removed'
    confirmation_token VARCHAR(255) UNIQUE,
    widget_link VARCHAR(500),
    auto_generated_password VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    removed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_human_agents_email ON human_agents(email);
CREATE INDEX IF NOT EXISTS idx_human_agents_status ON human_agents(status);
CREATE INDEX IF NOT EXISTS idx_human_agents_token ON human_agents(confirmation_token);

-- 2. Human Agent Sessions Table
CREATE TABLE IF NOT EXISTS human_agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_session_id VARCHAR(255) NOT NULL,
    agent_email VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'waiting', -- 'waiting', 'connected', 'ended'
    created_at TIMESTAMP DEFAULT NOW(),
    connected_at TIMESTAMP,
    ended_at TIMESTAMP,
    FOREIGN KEY (agent_email) REFERENCES human_agents(email)
);

CREATE INDEX IF NOT EXISTS idx_human_agent_sessions_customer ON human_agent_sessions(customer_session_id);
CREATE INDEX IF NOT EXISTS idx_human_agent_sessions_agent ON human_agent_sessions(agent_email);
CREATE INDEX IF NOT EXISTS idx_human_agent_sessions_status ON human_agent_sessions(status);

-- 3. Chat Feedback Table
CREATE TABLE IF NOT EXISTS chat_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    feedback_type VARCHAR(20) NOT NULL, -- 'positive', 'negative'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_feedback_message ON chat_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_session ON chat_feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_type ON chat_feedback(feedback_type);

-- 4. Token Usage Cache Table (Optional - for caching)
CREATE TABLE IF NOT EXISTS token_usage_cache (
    provider VARCHAR(50) PRIMARY KEY, -- 'gemini', 'openai'
    used BIGINT NOT NULL,
    available BIGINT NOT NULL,
    limit_value BIGINT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- 5. Update chatbot_configurations table (if it exists)
-- Add new columns for response policy, system prompt, and persona
DO $$ 
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'chatbot_configurations') THEN
        ALTER TABLE chatbot_configurations 
        ADD COLUMN IF NOT EXISTS response_policy INTEGER DEFAULT 30,
        ADD COLUMN IF NOT EXISTS system_prompt TEXT,
        ADD COLUMN IF NOT EXISTS selected_persona VARCHAR(100) DEFAULT 'friendly-receptionist';
    END IF;
END $$;

-- 6. Update llm_tokens column in chatbot_configurations (migrate deepseek to openai)
-- Note: This assumes llm_tokens is stored as JSONB. Adjust if using different format.
DO $$ 
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns 
               WHERE table_name = 'chatbot_configurations' 
               AND column_name = 'llm_tokens') THEN
        -- Update JSONB column to migrate deepseek to openai
        UPDATE chatbot_configurations
        SET llm_tokens = jsonb_set(
            llm_tokens::jsonb - 'deepseek',
            '{openai}',
            llm_tokens::jsonb->'deepseek'
        )
        WHERE llm_tokens::jsonb ? 'deepseek' 
        AND NOT (llm_tokens::jsonb ? 'openai');
    END IF;
END $$;

