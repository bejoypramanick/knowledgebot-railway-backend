-- Migration 018: Add granular prompt component breakdown columns
-- Tracks characters, words, and tokens for each component of the prompt:
--   system_prompt, conversation_history, tool_definitions, user_message (text only)
-- These are stored on the USER message row (since the prompt is assembled for the user turn)
-- Run manually on Railway Postgres BEFORE deploying code

-- System prompt breakdown
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS system_prompt_char_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS system_prompt_word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS system_prompt_token_count int4 DEFAULT 0;

-- Conversation history breakdown
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS history_char_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS history_word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS history_token_count int4 DEFAULT 0;

-- Tool definitions breakdown
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_def_char_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_def_word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_def_token_count int4 DEFAULT 0;

-- User message text breakdown (chars/words already computed; this adds dedicated columns for clarity)
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS user_msg_char_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS user_msg_word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS user_msg_token_count int4 DEFAULT 0;

-- Bot response text breakdown
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS bot_response_char_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS bot_response_word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS bot_response_token_count int4 DEFAULT 0;

-- Session-level aggregates for prompt component breakdown
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_system_prompt_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_history_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_tool_def_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_user_msg_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_bot_response_token_count int4 DEFAULT 0;
