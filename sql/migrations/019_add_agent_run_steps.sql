-- Migration 019: Track individual agent run steps (model turns + tool calls)
-- Each user message triggers an agent run with multiple steps:
--   Step 1: Model decides to call FileSearch (output = tool call JSON)
--   Step 2: Tool returns results (input to next model call)
--   Step 3: Model generates final response
-- This table captures each step so token usage adds up transparently.
-- Run manually on Railway Postgres BEFORE deploying code.

CREATE TABLE IF NOT EXISTS agent_run_steps (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_message_id uuid NULL,  -- FK to the user chat_message that triggered this run
    step_number int4 NOT NULL,  -- 1-based sequential step within the run
    step_type varchar(30) NOT NULL,  -- 'model_request', 'model_response'
    part_type varchar(30) NOT NULL,  -- 'system_prompt', 'user_prompt', 'text', 'tool_call', 'tool_return', 'thinking'
    tool_name varchar(100) NULL,  -- e.g. 'file_search' (for tool_call/tool_return parts)
    content_preview text DEFAULT '',  -- first 1000 chars of content
    char_count int4 DEFAULT 0,
    word_count int4 DEFAULT 0,
    token_count int4 DEFAULT 0,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_run_steps_session ON agent_run_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_user_msg ON agent_run_steps(user_message_id);
