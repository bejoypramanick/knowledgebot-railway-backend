-- ============================================================================
-- 3NF NORMALIZED DATABASE SCHEMA
-- This schema follows Third Normal Form (3NF) principles:
-- - 1NF: All attributes are atomic (no arrays or repeating groups)
-- - 2NF: No partial dependencies (all non-key attributes depend on entire PK)
-- - 3NF: No transitive dependencies (non-key attributes don't depend on other non-key attributes)
-- ============================================================================

-- Ensure required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

-- REMOVED: update_updated_at_column() function - no longer using triggers

-- ============================================================================
-- CORE USER TABLES
-- ============================================================================

-- Users table (base user information)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_active ON users(is_active);

-- REMOVED: CREATE TRIGGER update_users_updated_at

COMMENT ON TABLE users IS 'Base user information for all system users';

-- ============================================================================
-- ROLE TABLES (Normalized - one table per role type)
-- ============================================================================

-- Admins table
CREATE TABLE admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    confirmation_token VARCHAR(255) UNIQUE,
    auto_generated_password VARCHAR(255),
    created_by_email VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    removed_at TIMESTAMP,
    CONSTRAINT valid_admin_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT valid_admin_status CHECK (status IN ('pending', 'confirmed', 'removed'))
);

CREATE INDEX idx_admins_email ON admins(email);
CREATE INDEX idx_admins_status ON admins(status);
CREATE INDEX idx_admins_token ON admins(confirmation_token);

COMMENT ON TABLE admins IS 'Admin users with elevated privileges';
COMMENT ON COLUMN admins.auto_generated_password IS 'Auto-generated password sent via email';

-- Human agents table
CREATE TABLE human_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    confirmation_token VARCHAR(255) UNIQUE,
    widget_link VARCHAR(500),
    auto_generated_password VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    removed_at TIMESTAMP,
    CONSTRAINT valid_agent_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT valid_agent_status CHECK (status IN ('pending', 'confirmed', 'removed'))
);

CREATE INDEX idx_human_agents_email ON human_agents(email);
CREATE INDEX idx_human_agents_status ON human_agents(status);
CREATE INDEX idx_human_agents_token ON human_agents(confirmation_token);

COMMENT ON TABLE human_agents IS 'Human agents who handle customer support';

-- User unique IDs (for display purposes)
CREATE TABLE user_unique_ids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    unique_id VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT user_unique_ids_email_role_key UNIQUE (email, role),
    CONSTRAINT user_unique_ids_role_check CHECK (role IN ('customer', 'agent', 'admin'))
);

CREATE INDEX idx_user_unique_ids_email ON user_unique_ids(email);
CREATE INDEX idx_user_unique_ids_role ON user_unique_ids(role);
CREATE INDEX idx_user_unique_ids_unique_id ON user_unique_ids(unique_id);

COMMENT ON TABLE user_unique_ids IS 'Unique display IDs for users across different roles';

-- User profiles (extended user information)
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uid VARCHAR(255) NOT NULL UNIQUE,  -- Firebase UID
    email VARCHAR(255),
    display_name VARCHAR(255),
    photo_url TEXT,
    role VARCHAR(50) DEFAULT 'user',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMPTZ,
    CONSTRAINT user_profiles_role_check CHECK (role IN ('user', 'agent', 'admin')),
    CONSTRAINT user_profiles_email_check CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_user_profiles_uid ON user_profiles(uid);
CREATE INDEX idx_user_profiles_email ON user_profiles(email);
CREATE INDEX idx_user_profiles_role ON user_profiles(role);

COMMENT ON TABLE user_profiles IS 'Extended user profile information for authenticated users';

-- ============================================================================
-- CONFIGURATION TABLES (Normalized by concern)
-- ============================================================================

-- Main configuration metadata (single row table)
CREATE TABLE configuration_metadata (
    id INTEGER PRIMARY KEY DEFAULT 1,
    default_user_role VARCHAR(50) DEFAULT 'user',
    hil_enabled BOOLEAN DEFAULT true,
    response_policy INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1),
    CONSTRAINT valid_default_role CHECK (default_user_role IN ('user', 'admin', 'human_agent'))
);

-- REMOVED: CREATE TRIGGER update_configuration_metadata_updated_at

COMMENT ON TABLE configuration_metadata IS 'Global configuration settings (single row)';
COMMENT ON COLUMN configuration_metadata.hil_enabled IS 'Human-in-the-Loop enabled flag';

-- Notification settings (normalized)
CREATE TABLE notification_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    setting_name VARCHAR(100) NOT NULL UNIQUE,
    is_enabled BOOLEAN DEFAULT false,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notification_settings_name ON notification_settings(setting_name);

-- REMOVED: CREATE TRIGGER update_notification_settings_updated_at

COMMENT ON TABLE notification_settings IS 'Notification configuration settings';

-- Security settings (normalized)
CREATE TABLE security_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    setting_name VARCHAR(100) NOT NULL UNIQUE,
    setting_value TEXT,
    setting_type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_setting_type CHECK (setting_type IN ('string', 'integer', 'boolean', 'json'))
);

CREATE INDEX idx_security_settings_name ON security_settings(setting_name);

-- REMOVED: CREATE TRIGGER update_security_settings_updated_at

COMMENT ON TABLE security_settings IS 'Security configuration settings';

-- LLM Provider configurations (normalized)
CREATE TABLE llm_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_name VARCHAR(100) NOT NULL UNIQUE,
    token_limit BIGINT DEFAULT 0,
    token_used BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_llm_providers_name ON llm_providers(provider_name);
CREATE INDEX idx_llm_providers_active ON llm_providers(is_active);

-- REMOVED: CREATE TRIGGER update_llm_providers_updated_at

COMMENT ON TABLE llm_providers IS 'LLM provider configurations and token usage';

-- Persona configurations (normalized)
CREATE TABLE persona_configurations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    persona_name VARCHAR(100) NOT NULL UNIQUE,
    system_prompt TEXT NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_persona_configurations_name ON persona_configurations(persona_name);
CREATE INDEX idx_persona_configurations_active ON persona_configurations(is_active);

-- REMOVED: CREATE TRIGGER update_persona_configurations_updated_at

COMMENT ON TABLE persona_configurations IS 'AI persona configurations with system prompts';

-- ============================================================================
-- WIDGET CONFIGURATION TABLES (Normalized)
-- ============================================================================

-- Widget main configuration
CREATE TABLE widget_configuration (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(255) DEFAULT 'GLOBISTAAN',
    initial_message TEXT DEFAULT 'Hi! What can I help you with?',
    auto_show_duration INTEGER DEFAULT 4,
    keep_showing_suggested BOOLEAN DEFAULT true,
    theme VARCHAR(20) DEFAULT 'light',
    primary_color VARCHAR(7) DEFAULT '#3B81F6',
    use_primary_for_header BOOLEAN DEFAULT true,
    chat_bubble_color VARCHAR(7) DEFAULT '#3B81F6',
    align_bubble VARCHAR(10) DEFAULT 'right',
    profile_picture_url TEXT,
    chat_icon_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_theme CHECK (theme IN ('light', 'dark')),
    CONSTRAINT valid_align CHECK (align_bubble IN ('left', 'right'))
);

CREATE INDEX idx_widget_config_updated_at ON widget_configuration(updated_at);

-- REMOVED: CREATE TRIGGER update_widget_config_updated_at

COMMENT ON TABLE widget_configuration IS 'Widget display and behavior configuration';

-- Widget suggested messages (normalized - no more arrays!)
CREATE TABLE widget_suggested_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    widget_config_id INTEGER NOT NULL REFERENCES widget_configuration(id) ON DELETE CASCADE,
    message_text TEXT NOT NULL,
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_widget_suggested_messages_config ON widget_suggested_messages(widget_config_id);
CREATE INDEX idx_widget_suggested_messages_order ON widget_suggested_messages(display_order);
CREATE INDEX idx_widget_suggested_messages_active ON widget_suggested_messages(is_active);

COMMENT ON TABLE widget_suggested_messages IS 'Suggested messages for widget (normalized from array)';

-- Widget scripts
CREATE TABLE widget_scripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_id VARCHAR(255),
    script_content TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    install_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_widget_scripts_config_id ON widget_scripts(config_id);
CREATE INDEX idx_widget_scripts_is_active ON widget_scripts(is_active);

COMMENT ON TABLE widget_scripts IS 'Widget installation scripts';

-- ============================================================================
-- CHAT SESSION TABLES (Normalized)
-- ============================================================================

-- Chat sessions
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) NOT NULL UNIQUE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    message_count INTEGER DEFAULT 0,
    sentiment VARCHAR(20),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_sentiment CHECK (sentiment IN ('positive', 'negative', 'neutral'))
);

CREATE INDEX idx_chat_sessions_session_id ON chat_sessions(session_id);
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX idx_chat_sessions_sentiment ON chat_sessions(sentiment);
CREATE INDEX idx_chat_sessions_is_active ON chat_sessions(is_active);
CREATE INDEX idx_chat_sessions_last_activity ON chat_sessions(last_activity_at DESC);

-- REMOVED: CREATE TRIGGER update_chat_sessions_updated_at

COMMENT ON TABLE chat_sessions IS 'Chat session tracking';
COMMENT ON COLUMN chat_sessions.sentiment IS 'Overall sentiment analyzed by LLM';

-- Session assignments (normalized - replaces human_agent_sessions)
CREATE TABLE session_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    assignee_email VARCHAR(255) NOT NULL,
    assignee_type VARCHAR(20) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    assigned_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    CONSTRAINT valid_assignee_type CHECK (assignee_type IN ('agent', 'admin')),
    CONSTRAINT valid_assignment_status CHECK (status IN ('waiting', 'active', 'transferred', 'ended'))
);

CREATE INDEX idx_session_assignments_session ON session_assignments(session_id);
CREATE INDEX idx_session_assignments_assignee ON session_assignments(assignee_email);
CREATE INDEX idx_session_assignments_type ON session_assignments(assignee_type);
CREATE INDEX idx_session_assignments_status ON session_assignments(status);
CREATE INDEX idx_session_assignments_assigned_at ON session_assignments(assigned_at DESC);

COMMENT ON TABLE session_assignments IS 'Tracks which agent/admin is assigned to each session';

-- Chat messages
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    used_rag BOOLEAN DEFAULT false,
    used_postgres BOOLEAN DEFAULT false,
    used_neon_db BOOLEAN DEFAULT false,
    used_internet_search BOOLEAN DEFAULT false,
    confidence_score NUMERIC(3,2),
    sources JSONB DEFAULT '[]'::jsonb,
    usage_info JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_role CHECK (role IN ('user', 'agent', 'bot', 'system'))
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at DESC);
CREATE INDEX idx_chat_messages_role ON chat_messages(role);

COMMENT ON TABLE chat_messages IS 'Individual chat messages within sessions';

-- Chat feedback (normalized - removed derived session_feedback)
CREATE TABLE chat_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    feedback_type VARCHAR(20) NOT NULL,
    user_type VARCHAR(20) DEFAULT 'customer',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT valid_feedback_type CHECK (feedback_type IN ('positive', 'negative')),
    CONSTRAINT valid_user_type CHECK (user_type IN ('customer', 'agent'))
);

CREATE INDEX idx_chat_feedback_message ON chat_feedback(message_id);
CREATE INDEX idx_chat_feedback_session ON chat_feedback(session_id);
CREATE INDEX idx_chat_feedback_type ON chat_feedback(feedback_type);
CREATE INDEX idx_chat_feedback_user_type ON chat_feedback(user_type);

COMMENT ON TABLE chat_feedback IS 'User feedback on chat messages';

-- ============================================================================
-- FILE AND CONTENT TABLES
-- ============================================================================

-- File uploads
CREATE TABLE file_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    original_filename VARCHAR(500) NOT NULL,
    display_name VARCHAR(500),
    file_extension VARCHAR(50),
    cloudflare_r2_url TEXT,
    cloudflare_r2_key VARCHAR(500),
    gemini_file_name VARCHAR(500),
    gemini_file_uri TEXT,
    mime_type VARCHAR(255),
    size_bytes BIGINT,
    sha256_hash VARCHAR(64),
    r2_upload_status VARCHAR(50) DEFAULT 'pending',
    gemini_upload_status VARCHAR(50) DEFAULT 'pending',
    gemini_state VARCHAR(50),
    uploaded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    gemini_processed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_file_uploads_user_id ON file_uploads(user_id);
CREATE INDEX idx_file_uploads_gemini_file_name ON file_uploads(gemini_file_name);
CREATE INDEX idx_file_uploads_gemini_state ON file_uploads(gemini_state);
CREATE INDEX idx_file_uploads_r2_key ON file_uploads(cloudflare_r2_key);
CREATE INDEX idx_file_uploads_uploaded_at ON file_uploads(uploaded_at DESC);

-- REMOVED: CREATE TRIGGER update_file_uploads_updated_at

COMMENT ON TABLE file_uploads IS 'Uploaded files with cloud storage references';

-- Scraped websites
CREATE TABLE scraped_websites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    original_url TEXT NOT NULL,
    domain VARCHAR(500),
    title VARCHAR(1000),
    content_length INTEGER,
    pages_scraped INTEGER DEFAULT 1,
    gemini_file_name VARCHAR(500),
    gemini_file_uri TEXT,
    mime_type VARCHAR(255) DEFAULT 'text/markdown',
    size_bytes BIGINT,
    gemini_state VARCHAR(50),
    scraped_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    gemini_processed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    scraping_config JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scraped_websites_user_id ON scraped_websites(user_id);
CREATE INDEX idx_scraped_websites_domain ON scraped_websites(domain);
CREATE INDEX idx_scraped_websites_gemini_file_name ON scraped_websites(gemini_file_name);
CREATE INDEX idx_scraped_websites_gemini_state ON scraped_websites(gemini_state);
CREATE INDEX idx_scraped_websites_scraped_at ON scraped_websites(scraped_at DESC);

-- REMOVED: CREATE TRIGGER update_scraped_websites_updated_at

COMMENT ON TABLE scraped_websites IS 'Scraped website content for knowledge base';

-- ============================================================================
-- MONITORING AND ANALYTICS TABLES
-- ============================================================================

-- API usage tracking
CREATE TABLE api_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    api_provider VARCHAR(100) NOT NULL,
    api_endpoint VARCHAR(255),
    http_method VARCHAR(10),
    request_size_bytes INTEGER,
    response_size_bytes INTEGER,
    status_code INTEGER,
    cost_usd NUMERIC(10,6),
    tokens_input INTEGER,
    tokens_output INTEGER,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    duration_ms INTEGER,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_api_usage_provider ON api_usage(api_provider);
CREATE INDEX idx_api_usage_user_id ON api_usage(user_id);
CREATE INDEX idx_api_usage_created_at ON api_usage(created_at DESC);

COMMENT ON TABLE api_usage IS 'API usage tracking and analytics';

-- Metrics
CREATE TABLE metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric_type VARCHAR(100) NOT NULL,
    metric_name VARCHAR(255) NOT NULL,
    value NUMERIC(20,4),
    unit VARCHAR(50),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    file_upload_id UUID REFERENCES file_uploads(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_metrics_type ON metrics(metric_type);
CREATE INDEX idx_metrics_name ON metrics(metric_name);
CREATE INDEX idx_metrics_user_id ON metrics(user_id);
CREATE INDEX idx_metrics_recorded_at ON metrics(recorded_at DESC);

COMMENT ON TABLE metrics IS 'System metrics and performance tracking';

-- ============================================================================
-- NOTIFICATION AND COMMUNICATION TABLES
-- ============================================================================

-- Notifications
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'info',
    is_read BOOLEAN DEFAULT false,
    read_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_notification_type CHECK (type IN ('info', 'success', 'warning', 'error'))
);

CREATE INDEX idx_notifications_user_email ON notifications(user_email);
CREATE INDEX idx_notifications_is_read ON notifications(is_read);
CREATE INDEX idx_notifications_user_read ON notifications(user_email, is_read);
CREATE INDEX idx_notifications_created_at ON notifications(created_at DESC);

COMMENT ON TABLE notifications IS 'User notifications';

-- Email OAuth credentials (single row table)
CREATE TABLE email_oauth_credentials (
    id INTEGER PRIMARY KEY DEFAULT 1,
    client_id VARCHAR(500) NOT NULL,
    client_secret VARCHAR(500) NOT NULL,
    refresh_token TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

COMMENT ON TABLE email_oauth_credentials IS 'Email service OAuth credentials (single row)';

-- ============================================================================
-- CACHE AND TEMPORARY TABLES
-- ============================================================================

-- Token usage cache
CREATE TABLE token_usage_cache (
    provider VARCHAR(50) PRIMARY KEY,
    used BIGINT NOT NULL,
    available BIGINT NOT NULL,
    limit_value BIGINT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE token_usage_cache IS 'Cached token usage for quick lookups';

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Unified user roles view
CREATE OR REPLACE VIEW user_roles AS
SELECT 
    email,
    'admin' AS role,
    'confirmed' AS status,
    confirmed_at AS role_assigned_at
FROM admins
WHERE status = 'confirmed'
UNION ALL
SELECT 
    email,
    'human_agent' AS role,
    status,
    confirmed_at AS role_assigned_at
FROM human_agents
WHERE status = 'confirmed';

COMMENT ON VIEW user_roles IS 'Unified view of all user roles (admins and human agents)';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get user role function
CREATE OR REPLACE FUNCTION get_user_role(user_email VARCHAR)
RETURNS VARCHAR AS $$
DECLARE
    user_role VARCHAR(50);
BEGIN
    -- Check if user is an admin
    SELECT 'admin' INTO user_role
    FROM admins
    WHERE email = user_email AND status = 'confirmed'
    LIMIT 1;
    
    IF user_role IS NOT NULL THEN
        RETURN user_role;
    END IF;
    
    -- Check if user is a human agent
    SELECT 'human_agent' INTO user_role
    FROM human_agents
    WHERE email = user_email AND status = 'confirmed'
    LIMIT 1;
    
    IF user_role IS NOT NULL THEN
        RETURN user_role;
    END IF;
    
    -- Default to 'user'
    RETURN 'user';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_user_role(VARCHAR) IS 'Returns the role (admin, human_agent, or user) for a given email';

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert default configuration metadata
INSERT INTO configuration_metadata (id, default_user_role, hil_enabled, response_policy)
VALUES (1, 'user', true, 30)
ON CONFLICT (id) DO NOTHING;

-- Insert default notification settings
INSERT INTO notification_settings (setting_name, is_enabled, description) VALUES
('user_interactions_enabled', false, 'Enable notifications for user interactions'),
('error_alerts_enabled', false, 'Enable error alert notifications'),
('feedback_requests_enabled', true, 'Enable feedback request notifications')
ON CONFLICT (setting_name) DO NOTHING;

-- Insert default security settings
INSERT INTO security_settings (setting_name, setting_value, setting_type, description) VALUES
('response_timeout', '30', 'integer', 'Response timeout in seconds'),
('remove_pii', 'false', 'boolean', 'Remove personally identifiable information'),
('restrict_config', 'false', 'boolean', 'Restrict configuration access')
ON CONFLICT (setting_name) DO NOTHING;

-- Insert default LLM providers
INSERT INTO llm_providers (provider_name, token_limit, token_used, is_active) VALUES
('gemini', 20000, 0, true),
('deepseek', 150000, 0, true)
ON CONFLICT (provider_name) DO NOTHING;

-- Insert default persona
INSERT INTO persona_configurations (persona_name, system_prompt, is_active) VALUES
('friendly-receptionist', 'You are a friendly and helpful receptionist assistant.', true)
ON CONFLICT (persona_name) DO NOTHING;

-- Insert default widget configuration
INSERT INTO widget_configuration (id, display_name, initial_message) VALUES
(1, 'GLOBISTAAN', 'Hi! What can I help you with?')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- PERMISSIONS
-- ============================================================================

-- Grant permissions to postgres user
ALTER TABLE users OWNER TO postgres;
ALTER TABLE admins OWNER TO postgres;
ALTER TABLE human_agents OWNER TO postgres;
ALTER TABLE user_unique_ids OWNER TO postgres;
ALTER TABLE configuration_metadata OWNER TO postgres;
ALTER TABLE notification_settings OWNER TO postgres;
ALTER TABLE security_settings OWNER TO postgres;
ALTER TABLE llm_providers OWNER TO postgres;
ALTER TABLE persona_configurations OWNER TO postgres;
ALTER TABLE widget_configuration OWNER TO postgres;
ALTER TABLE widget_suggested_messages OWNER TO postgres;
ALTER TABLE widget_scripts OWNER TO postgres;
ALTER TABLE chat_sessions OWNER TO postgres;
ALTER TABLE session_assignments OWNER TO postgres;
ALTER TABLE chat_messages OWNER TO postgres;
ALTER TABLE chat_feedback OWNER TO postgres;
ALTER TABLE file_uploads OWNER TO postgres;
ALTER TABLE scraped_websites OWNER TO postgres;
ALTER TABLE api_usage OWNER TO postgres;
ALTER TABLE metrics OWNER TO postgres;
ALTER TABLE notifications OWNER TO postgres;
ALTER TABLE email_oauth_credentials OWNER TO postgres;
ALTER TABLE token_usage_cache OWNER TO postgres;
ALTER VIEW user_roles OWNER TO postgres;
ALTER FUNCTION get_user_role(VARCHAR) OWNER TO postgres;
ALTER FUNCTION update_updated_at_column() OWNER TO postgres;

-- ============================================================================
-- SCHEMA COMPLETE
-- ============================================================================

COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form';
