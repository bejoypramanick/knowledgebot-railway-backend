-- Configuration Tables for Chatbot and Widget Settings
-- Run this migration on your PostgreSQL database

-- Chatbot Configuration Table
CREATE TABLE IF NOT EXISTS chatbot_configuration (
    id SERIAL PRIMARY KEY,
    admin_user VARCHAR(255) NOT NULL DEFAULT 'GLOBISTAAN',
    admin_password_hash VARCHAR(255),  -- Store hashed password, not plain text
    human_agents TEXT[],  -- Array of email addresses
    user_interactions_enabled BOOLEAN DEFAULT false,
    error_alerts_enabled BOOLEAN DEFAULT false,
    feedback_requests_enabled BOOLEAN DEFAULT true,
    response_timeout INTEGER DEFAULT 30,  -- seconds
    remove_pii BOOLEAN DEFAULT false,
    restrict_config BOOLEAN DEFAULT false,
    response_policy INTEGER DEFAULT 30,  -- 0-100 slider value (Flexi to Strict)
    backup_logs BOOLEAN DEFAULT false,
    system_prompt TEXT,
    selected_persona VARCHAR(100) DEFAULT 'friendly-receptionist',
    llm_token_limit_gemini INTEGER DEFAULT 20000,
    llm_token_used_gemini INTEGER DEFAULT 0,
    llm_token_limit_deepseek INTEGER DEFAULT 150000,
    llm_token_used_deepseek INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(admin_user)
);

-- Widget Configuration Table
CREATE TABLE IF NOT EXISTS widget_configuration (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(255) DEFAULT 'GLOBISTAAN',
    initial_message TEXT DEFAULT 'Hi! What can I help you with?',
    auto_show_duration INTEGER DEFAULT 4,  -- seconds
    suggested_messages TEXT[],  -- Array of suggested messages
    keep_showing_suggested BOOLEAN DEFAULT true,
    theme VARCHAR(20) DEFAULT 'light',  -- 'light' or 'dark'
    primary_color VARCHAR(7) DEFAULT '#3B81F6',  -- Hex color code
    use_primary_for_header BOOLEAN DEFAULT true,
    chat_bubble_color VARCHAR(7) DEFAULT '#3B81F6',  -- Hex color code
    align_bubble VARCHAR(10) DEFAULT 'right',  -- 'left' or 'right'
    profile_picture_url TEXT,
    chat_icon_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_chatbot_config_admin_user ON chatbot_configuration(admin_user);
CREATE INDEX IF NOT EXISTS idx_widget_config_updated_at ON widget_configuration(updated_at);

-- Insert default configuration if not exists
INSERT INTO chatbot_configuration (admin_user, human_agents, system_prompt, selected_persona)
VALUES ('GLOBISTAAN', ARRAY[]::TEXT[], '', 'friendly-receptionist')
ON CONFLICT (admin_user) DO NOTHING;

INSERT INTO widget_configuration (display_name, initial_message)
VALUES ('GLOBISTAAN', 'Hi! What can I help you with?')
ON CONFLICT DO NOTHING;

-- Note: updated_at is handled in application code, not via triggers
-- This avoids trigger overhead and gives better control

