-- ============================================================================
-- MINIMAL SCHEMA - Only tables required by current codebase
-- ============================================================================
-- Based on analysis of actual table usage in backend services
-- Removed: users, user_profiles (replaced by role-based tables)

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by_email VARCHAR(255),
    CONSTRAINT valid_admin_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_admins_email ON admins(email);
CREATE INDEX idx_admins_status ON admins(status);
CREATE INDEX idx_admins_email_status ON admins(email, status);

-- Human Agents table
CREATE TABLE human_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    confirmation_token VARCHAR(255) UNIQUE,
    auto_generated_password VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by_email VARCHAR(255),
    CONSTRAINT valid_agent_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_human_agents_email ON human_agents(email);
CREATE INDEX idx_human_agents_status ON human_agents(status);
CREATE INDEX idx_human_agents_email_status ON human_agents(email, status);

-- User Unique IDs table (for generating unique IDs)
CREATE TABLE user_unique_ids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    unique_id VARCHAR(255) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_uid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT unique_email_role UNIQUE (email, role)
);

CREATE INDEX idx_user_unique_ids_email ON user_unique_ids(email);
CREATE INDEX idx_user_unique_ids_unique_id ON user_unique_ids(unique_id);
CREATE INDEX idx_user_unique_ids_email_role ON user_unique_ids(email, role);

-- ============================================================================
-- CONFIGURATION TABLES
-- ============================================================================

-- Configuration Metadata table
CREATE TABLE configuration_metadata (
    id INTEGER PRIMARY KEY DEFAULT 1,
    default_user_role VARCHAR(50) DEFAULT 'user',
    hil_enabled BOOLEAN DEFAULT true,
    response_policy INTEGER DEFAULT 30,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
);

-- Notification Settings table
CREATE TABLE notification_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    setting_name VARCHAR(100) NOT NULL UNIQUE,
    is_enabled BOOLEAN DEFAULT false,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notification_settings_name ON notification_settings(setting_name);

-- Security Settings table
CREATE TABLE security_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    setting_name VARCHAR(100) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    setting_type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_security_settings_name ON security_settings(setting_name);

-- LLM Providers table
CREATE TABLE llm_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_name VARCHAR(100) NOT NULL UNIQUE,
    token_limit INTEGER DEFAULT 0,
    token_used INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_llm_providers_name ON llm_providers(provider_name);
CREATE INDEX idx_llm_providers_active ON llm_providers(is_active);

-- Persona Configurations table
CREATE TABLE persona_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_name VARCHAR(255) NOT NULL UNIQUE,
    system_prompt TEXT NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_persona_configurations_name ON persona_configurations(persona_name);
CREATE INDEX idx_persona_configurations_active ON persona_configurations(is_active);

-- ============================================================================
-- WIDGET TABLES
-- ============================================================================

-- Widget Configuration table
CREATE TABLE widget_configuration (
    id INTEGER PRIMARY KEY DEFAULT 1,
    display_name VARCHAR(255) DEFAULT 'AI Assistant',
    initial_message TEXT DEFAULT 'Hi! How can I help you today?',
    theme VARCHAR(50) DEFAULT 'light',
    position VARCHAR(50) DEFAULT 'bottom-right',
    primary_color VARCHAR(7) DEFAULT '#3B82F6',
    secondary_color VARCHAR(7) DEFAULT '#6B7280',
    background_color VARCHAR(7) DEFAULT '#FFFFFF',
    text_color VARCHAR(7) DEFAULT '#111827',
    border_radius VARCHAR(20) DEFAULT '12px',
    show_powered_by BOOLEAN DEFAULT true,
    powered_by_text VARCHAR(255) DEFAULT 'Powered by KnowledgeBot',
    allow_file_upload BOOLEAN DEFAULT false,
    allow_screenshot BOOLEAN DEFAULT false,
    max_file_size_mb INTEGER DEFAULT 10,
    allowed_file_types TEXT DEFAULT 'image/*,application/pdf,text/*',
    enable_voice_input BOOLEAN DEFAULT false,
    enable_typing_indicator BOOLEAN DEFAULT true,
    enable_message_timestamps BOOLEAN DEFAULT false,
    enable_user_feedback BOOLEAN DEFAULT true,
    enable_message_reactions BOOLEAN DEFAULT false,
    enable_quick_responses BOOLEAN DEFAULT true,
    enable_auto_scroll BOOLEAN DEFAULT true,
    enable_dark_mode_toggle BOOLEAN DEFAULT false,
    enable_fullscreen_mode BOOLEAN DEFAULT false,
    enable_export_chat BOOLEAN DEFAULT false,
    enable_clear_chat BOOLEAN DEFAULT false,
    enable_sound_notifications BOOLEAN DEFAULT false,
    enable_browser_notifications BOOLEAN DEFAULT false,
    enable_email_notifications BOOLEAN DEFAULT false,
    enable_push_notifications BOOLEAN DEFAULT false,
    zoom_level DECIMAL(3,2) DEFAULT 1.00,
    horizontal_position VARCHAR(20) DEFAULT '20px',
    vertical_position VARCHAR(20) DEFAULT '20px',
    width VARCHAR(20) DEFAULT '380px',
    height VARCHAR(20) DEFAULT '600px',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_widget_config CHECK (id = 1)
);

-- Widget Suggested Messages table
CREATE TABLE widget_suggested_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    widget_config_id INTEGER NOT NULL DEFAULT 1,
    message_text TEXT NOT NULL,
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (widget_config_id) REFERENCES widget_configuration(id) ON DELETE CASCADE
);

CREATE INDEX idx_widget_suggested_messages_config_id ON widget_suggested_messages(widget_config_id);
CREATE INDEX idx_widget_suggested_messages_active ON widget_suggested_messages(is_active);

-- Widget Scripts table (referenced in schema but may not be actively used)
CREATE TABLE widget_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    script_name VARCHAR(255) NOT NULL UNIQUE,
    script_content TEXT NOT NULL,
    script_type VARCHAR(50) DEFAULT 'javascript',
    is_active BOOLEAN DEFAULT true,
    execution_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_widget_scripts_name ON widget_scripts(script_name);
CREATE INDEX idx_widget_scripts_active ON widget_scripts(is_active);

-- ============================================================================
-- SESSION MANAGEMENT TABLES
-- ============================================================================

-- Session Assignments table (used for tracking chat assignments)
CREATE TABLE session_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    assignee_email VARCHAR(255),
    assignee_type VARCHAR(50) DEFAULT 'agent',
    status VARCHAR(50) DEFAULT 'active',
    assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_session_assignments_session_id ON session_assignments(session_id);
CREATE INDEX idx_session_assignments_assignee_email ON session_assignments(assignee_email);
CREATE INDEX idx_session_assignments_status ON session_assignments(status);

-- ============================================================================
-- KNOWLEDGE BASE TABLES
-- ============================================================================

-- File Uploads table (used for knowledge base file management)
CREATE TABLE file_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255),
    file_path TEXT,
    file_size BIGINT,
    mime_type VARCHAR(100),
    gemini_file_id VARCHAR(255),
    gemini_file_name VARCHAR(255),
    gemini_state VARCHAR(50) DEFAULT 'PENDING',
    user_email VARCHAR(255),
    upload_source VARCHAR(50) DEFAULT 'widget',
    processing_status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_file_uploads_user_email ON file_uploads(user_email);
CREATE INDEX idx_file_uploads_gemini_state ON file_uploads(gemini_state);
CREATE INDEX idx_file_uploads_processing_status ON file_uploads(processing_status);

-- Scraped Websites table (used for website scraping)
CREATE TABLE scraped_websites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    title VARCHAR(500),
    content TEXT,
    gemini_file_id VARCHAR(255),
    gemini_file_name VARCHAR(255),
    gemini_state VARCHAR(50) DEFAULT 'PENDING',
    scraping_status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scraped_websites_url ON scraped_websites(url);
CREATE INDEX idx_scraped_websites_gemini_state ON scraped_websites(gemini_state);
CREATE INDEX idx_scraped_websites_scraping_status ON scraped_websites(scraping_status);

-- ============================================================================
-- ANALYTICS TABLES
-- ============================================================================

-- API Usage table (used for tracking API usage)
CREATE TABLE api_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR(255),
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status_code INTEGER,
    response_time_ms INTEGER,
    request_size_bytes BIGINT,
    response_size_bytes BIGINT,
    user_agent TEXT,
    ip_address INET,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_api_usage_user_email ON api_usage(user_email);
CREATE INDEX idx_api_usage_endpoint ON api_usage(endpoint);
CREATE INDEX idx_api_usage_created_at ON api_usage(created_at);

-- Metrics table (used for system metrics)
CREATE TABLE metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_type VARCHAR(100) NOT NULL,
    metric_name VARCHAR(255) NOT NULL,
    value DECIMAL(15,4),
    unit VARCHAR(50),
    user_id UUID,
    file_upload_id UUID,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_upload_id) REFERENCES file_uploads(id) ON DELETE SET NULL
);

CREATE INDEX idx_metrics_type ON metrics(metric_type);
CREATE INDEX idx_metrics_name ON metrics(metric_name);
CREATE INDEX idx_metrics_user_id ON metrics(user_id);
CREATE INDEX idx_metrics_created_at ON metrics(created_at);

-- ============================================================================
-- NOTIFICATIONS TABLES
-- ============================================================================

-- Notifications table (used for user notifications)
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    type VARCHAR(50) DEFAULT 'info',
    is_read BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notifications_user_email ON notifications(user_email);
CREATE INDEX idx_notifications_is_read ON notifications(is_read);
CREATE INDEX idx_notifications_type ON notifications(type);
CREATE INDEX idx_notifications_created_at ON notifications(created_at);

-- ============================================================================
-- EMAIL TABLES
-- ============================================================================

-- Email OAuth Credentials table (used for email services)
CREATE TABLE email_oauth_credentials (
    id INTEGER PRIMARY KEY DEFAULT 1,
    provider VARCHAR(50) DEFAULT 'gmail',
    client_id TEXT,
    client_secret TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_email_oauth_config CHECK (id = 1)
);

-- ============================================================================
-- CHAT TABLES
-- ============================================================================

-- Chat Sessions table
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) UNIQUE NOT NULL,
    user_email VARCHAR(255),
    user_name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',
    assigned_to VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    total_messages INTEGER DEFAULT 0,
    user_satisfaction_rating DECIMAL(2,1),
    feedback_text TEXT,
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    referrer TEXT,
    source VARCHAR(100) DEFAULT 'widget'
);

CREATE INDEX idx_chat_sessions_session_id ON chat_sessions(session_id);
CREATE INDEX idx_chat_sessions_user_email ON chat_sessions(user_email);
CREATE INDEX idx_chat_sessions_status ON chat_sessions(status);
CREATE INDEX idx_chat_sessions_assigned_to ON chat_sessions(assigned_to);
CREATE INDEX idx_chat_sessions_created_at ON chat_sessions(created_at);
CREATE INDEX idx_chat_sessions_last_activity ON chat_sessions(last_activity_at);

-- Chat Messages table
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    message_id VARCHAR(255),
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_role ON chat_messages(role);
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at);

-- Chat Feedback table
CREATE TABLE chat_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    feedback_type VARCHAR(50) NOT NULL,
    rating INTEGER,
    feedback_text TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_feedback_session_id ON chat_feedback(session_id);
CREATE INDEX idx_chat_feedback_type ON chat_feedback(feedback_type);
CREATE INDEX idx_chat_feedback_created_at ON chat_feedback(created_at);

-- ============================================================================
-- TOKEN USAGE TABLES
-- ============================================================================

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert default configuration metadata
INSERT INTO configuration_metadata (id, default_user_role, hil_enabled, response_policy)
VALUES (1, 'user', true, 30)
ON CONFLICT (id) DO NOTHING;

-- Insert default notification settings
INSERT INTO notification_settings (setting_name, is_enabled, description) VALUES
('user_interactions', true, 'Send notifications for user interactions'),
('error_alerts', true, 'Send notifications for system errors'),
('feedback_requests', false, 'Request feedback from users after conversations')
ON CONFLICT (setting_name) DO NOTHING;

-- Insert default security settings
INSERT INTO security_settings (setting_name, setting_value, setting_type, description) VALUES
('response_timeout', '30', 'integer', 'Maximum response time in seconds'),
('max_requests_per_minute', '60', 'integer', 'Rate limiting for API requests'),
('enable_cors', 'true', 'boolean', 'Enable Cross-Origin Resource Sharing')
ON CONFLICT (setting_name) DO NOTHING;

-- Insert default LLM providers
INSERT INTO llm_providers (provider_name, token_limit, token_used, is_active) VALUES
('gemini', 1000000, 0, true),
('openai', 1000000, 0, false),
('deepseek', 1000000, 0, false)
ON CONFLICT (provider_name) DO NOTHING;

-- Insert default persona configurations
INSERT INTO persona_configurations (persona_name, system_prompt, is_active) VALUES
('default', 'You are a helpful AI assistant that provides accurate and helpful responses.', true),
('professional', 'You are a professional AI assistant specializing in business and technical support.', false),
('friendly', 'You are a friendly and approachable AI assistant focused on customer satisfaction.', false)
ON CONFLICT (persona_name) DO NOTHING;

-- Insert default widget configuration
INSERT INTO widget_configuration (id, display_name, initial_message) VALUES
(1, 'AI Assistant', 'Hi! How can I help you today?')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- PERMISSIONS
-- ============================================================================

-- Grant permissions to postgres user (Railway default)
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
ALTER TABLE session_assignments OWNER TO postgres;
ALTER TABLE chat_sessions OWNER TO postgres;
ALTER TABLE chat_messages OWNER TO postgres;
ALTER TABLE chat_feedback OWNER TO postgres;
ALTER TABLE file_uploads OWNER TO postgres;
ALTER TABLE scraped_websites OWNER TO postgres;
ALTER TABLE api_usage OWNER TO postgres;
ALTER TABLE metrics OWNER TO postgres;
ALTER TABLE notifications OWNER TO postgres;
ALTER TABLE email_oauth_credentials OWNER TO postgres;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE admins IS 'Admin users with elevated permissions (profile data from Firebase)';
COMMENT ON TABLE human_agents IS 'Human agent users for customer support (profile data from Firebase)';
COMMENT ON TABLE user_unique_ids IS 'Unique ID mappings for users across different roles';
COMMENT ON TABLE configuration_metadata IS 'Global configuration settings and metadata';
COMMENT ON TABLE notification_settings IS 'System-wide notification preferences';
COMMENT ON TABLE security_settings IS 'Security and rate limiting settings';
COMMENT ON TABLE llm_providers IS 'LLM provider configurations and token tracking';
COMMENT ON TABLE persona_configurations IS 'AI persona configurations and prompts';
COMMENT ON TABLE widget_configuration IS 'Chat widget appearance and behavior settings';
COMMENT ON TABLE widget_suggested_messages IS 'Pre-configured suggested messages for the widget';
COMMENT ON TABLE widget_scripts IS 'Custom scripts for widget functionality';
COMMENT ON TABLE session_assignments IS 'Chat session assignments to agents';
COMMENT ON TABLE chat_sessions IS 'Chat conversation sessions with metadata';
COMMENT ON TABLE chat_messages IS 'Individual messages within chat sessions';
COMMENT ON TABLE chat_feedback IS 'User feedback and ratings for conversations';
COMMENT ON TABLE file_uploads IS 'Uploaded files for knowledge base processing';
COMMENT ON TABLE scraped_websites IS 'Scraped website content for knowledge base';
COMMENT ON TABLE api_usage IS 'API usage tracking and analytics';
COMMENT ON TABLE metrics IS 'System metrics and performance data';
COMMENT ON TABLE notifications IS 'User notifications and alerts';
COMMENT ON TABLE email_oauth_credentials IS 'Email service OAuth credentials';