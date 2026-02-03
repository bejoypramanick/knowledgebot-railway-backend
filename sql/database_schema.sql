-- PostgreSQL Database Schema for KnowledgeBot Backend
-- 3NF Normalized Schema - All tables follow Third Normal Form
-- Consolidated from all migration files

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Drop and recreate schema (for clean setup)
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public AUTHORIZATION pg_database_owner;

COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form';

-- Core Tables

-- Admins table
CREATE TABLE public.admins (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email varchar(255) NOT NULL,
    created_by_email varchar(255) NULL,
    created_at timestamp DEFAULT now() NULL,
    removed_at timestamp NULL,
    CONSTRAINT admins_email_key UNIQUE (email),
    CONSTRAINT admins_pkey PRIMARY KEY (id),
    CONSTRAINT check_email_domain CHECK (((email)::text ~* '@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'::text)),
    CONSTRAINT valid_admin_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text))
);
CREATE INDEX idx_admins_email ON public.admins USING btree (email);
CREATE INDEX idx_admins_email_domain ON public.admins USING btree (split_part((email)::text, '@'::text, 2));
COMMENT ON TABLE public.admins IS 'Admin users with immediate activation (no confirmation needed)';

-- Human agents table
CREATE TABLE public.human_agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email varchar(255) NOT NULL,
    widget_link varchar(500) NULL,
    created_at timestamp DEFAULT now() NULL,
    removed_at timestamp NULL,
    CONSTRAINT check_email_domain CHECK (((email)::text ~* '@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'::text)),
    CONSTRAINT human_agents_email_key UNIQUE (email),
    CONSTRAINT human_agents_pkey PRIMARY KEY (id),
    CONSTRAINT valid_agent_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text))
);
CREATE INDEX idx_human_agents_email ON public.human_agents USING btree (email);
CREATE INDEX idx_human_agents_email_domain ON public.human_agents USING btree (split_part((email)::text, '@'::text, 2));
COMMENT ON TABLE public.human_agents IS 'Human agents with immediate activation (no confirmation needed)';

-- Users table
CREATE TABLE public.users (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    email varchar(255) NOT NULL,
    display_name varchar(255) NULL,
    email_verified bool DEFAULT false NULL,
    photo_url text NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    last_login_at timestamptz NULL,
    CONSTRAINT users_email_key UNIQUE (email),
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT valid_user_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text))
);
CREATE INDEX idx_users_email ON public.users USING btree (email);
CREATE INDEX idx_users_created_at ON public.users USING btree (created_at DESC);
COMMENT ON TABLE public.users IS 'User accounts from Firebase Auth';

-- Chat sessions table
CREATE TABLE public.chat_sessions (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    session_id varchar(255) NOT NULL,
    user_id uuid NULL,
    started_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    last_activity_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    ended_at timestamptz NULL,
    is_active bool DEFAULT true NULL,
    message_count int4 DEFAULT 0 NULL,
    sentiment varchar(20) NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    archive_status varchar(20) DEFAULT 'active'::character varying NULL,
    conversation_summary text NULL,
    file_search_store_id varchar(255) NULL,
    cached_content_id varchar(255) NULL,
    CONSTRAINT chat_sessions_archive_status_check CHECK (((archive_status)::text = ANY ((ARRAY['active'::character varying, 'closed'::character varying, 'archived'::character varying, 'transferred'::character varying])::text[]))),
    CONSTRAINT chat_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT chat_sessions_session_id_key UNIQUE (session_id),
    CONSTRAINT chat_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL,
    CONSTRAINT valid_sentiment CHECK (((sentiment)::text = ANY ((ARRAY['positive'::character varying, 'negative'::character varying, 'neutral'::character varying])::text[])))
);
CREATE INDEX idx_chat_sessions_archive_status ON public.chat_sessions USING btree (archive_status);
CREATE INDEX idx_chat_sessions_archive_status_updated ON public.chat_sessions USING btree (archive_status, updated_at DESC);
CREATE INDEX idx_chat_sessions_cached_content_id ON public.chat_sessions USING btree (cached_content_id);
CREATE INDEX idx_chat_sessions_conversation_summary ON public.chat_sessions USING gin (to_tsvector('english'::regconfig, conversation_summary));
CREATE INDEX idx_chat_sessions_file_search_store_id ON public.chat_sessions USING btree (file_search_store_id);
CREATE INDEX idx_chat_sessions_is_active ON public.chat_sessions USING btree (is_active);
CREATE INDEX idx_chat_sessions_last_activity ON public.chat_sessions USING btree (last_activity_at DESC);
CREATE INDEX idx_chat_sessions_sentiment ON public.chat_sessions USING btree (sentiment);
CREATE INDEX idx_chat_sessions_session_id ON public.chat_sessions USING btree (session_id);
CREATE INDEX idx_chat_sessions_user_id ON public.chat_sessions USING btree (user_id);
COMMENT ON TABLE public.chat_sessions IS 'Chat session tracking';
COMMENT ON COLUMN public.chat_sessions.sentiment IS 'Overall sentiment analyzed by LLM';
COMMENT ON COLUMN public.chat_sessions.archive_status IS 'Session status: active (ongoing), closed (finished), archived (manually archived), transferred (moved to another agent)';
COMMENT ON COLUMN public.chat_sessions.conversation_summary IS 'AI-generated summary of the conversation, created when session ends';
COMMENT ON COLUMN public.chat_sessions.file_search_store_id IS 'Gemini FileSearchStore ID for RAG optimization';
COMMENT ON COLUMN public.chat_sessions.cached_content_id IS 'Gemini cached content ID for 90% cost discount';

-- Chat messages table
CREATE TABLE public.chat_messages (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    session_id uuid NOT NULL,
    role varchar(50) NOT NULL,
    content text NOT NULL,
    used_rag bool DEFAULT false NULL,
    used_postgres bool DEFAULT false NULL,
    used_neon_db bool DEFAULT false NULL,
    used_internet_search bool DEFAULT false NULL,
    confidence_score numeric(3, 2) NULL,
    sources jsonb DEFAULT '[]'::jsonb NULL,
    usage_info jsonb DEFAULT '{}'::jsonb NULL,
    rating int4 NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT chat_messages_pkey PRIMARY KEY (id),
    CONSTRAINT valid_role CHECK (((role)::text = ANY ((ARRAY['user'::character varying, 'agent'::character varying, 'bot'::character varying, 'system'::character varying])::text[]))),
    CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    CONSTRAINT valid_rating CHECK ((rating >= 1 AND rating <= 5))
);
CREATE INDEX idx_chat_messages_created_at ON public.chat_messages USING btree (created_at DESC);
CREATE INDEX idx_chat_messages_role ON public.chat_messages USING btree (role);
CREATE INDEX idx_chat_messages_role_created_at ON public.chat_messages USING btree (role, created_at DESC);
CREATE INDEX idx_chat_messages_session_id ON public.chat_messages USING btree (session_id);
CREATE INDEX idx_chat_messages_rating ON public.chat_messages USING btree (rating);
COMMENT ON TABLE public.chat_messages IS 'Individual chat messages within sessions';

-- Session assignments table
CREATE TABLE public.session_assignments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    assignee_email varchar(255) NOT NULL,
    assignee_type varchar(20) NOT NULL,
    status varchar(50) DEFAULT 'active'::character varying NULL,
    assigned_at timestamp DEFAULT now() NULL,
    ended_at timestamp NULL,
    CONSTRAINT session_assignments_pkey PRIMARY KEY (id),
    CONSTRAINT valid_assignee_type CHECK (((assignee_type)::text = ANY ((ARRAY['agent'::character varying, 'admin'::character varying])::text[]))),
    CONSTRAINT valid_assignment_status CHECK (((status)::text = ANY ((ARRAY['waiting'::character varying, 'active'::character varying, 'transferred'::character varying, 'ended'::character varying])::text[]))),
    CONSTRAINT session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_session_assignments_assigned_at ON public.session_assignments USING btree (assigned_at DESC);
CREATE INDEX idx_session_assignments_assignee ON public.session_assignments USING btree (assignee_email);
CREATE INDEX idx_session_assignments_session ON public.session_assignments USING btree (session_id);
CREATE INDEX idx_session_assignments_status ON public.session_assignments USING btree (status);
CREATE INDEX idx_session_assignments_type ON public.session_assignments USING btree (assignee_type);
COMMENT ON TABLE public.session_assignments IS 'Tracks which agent/admin is assigned to each session';

-- File uploads table (R2 removed - database only)
CREATE TABLE public.file_uploads (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    original_filename varchar(500) NOT NULL,
    display_name varchar(500) NULL,
    file_extension varchar(50) NULL,
    gemini_file_name varchar(500) NULL,
    gemini_file_uri text NULL,
    mime_type varchar(255) NULL,
    size_bytes bigint NULL,
    sha256_hash varchar(64) NULL,
    gemini_upload_status varchar(50) DEFAULT 'pending'::character varying NULL,
    gemini_state varchar(50) NULL,
    uploaded_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    gemini_processed_at timestamptz NULL,
    expires_at timestamptz NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    version integer DEFAULT 1 NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL
);
CREATE INDEX idx_file_uploads_user_id ON public.file_uploads(user_id);
CREATE INDEX idx_file_uploads_gemini_file_name ON public.file_uploads(gemini_file_name);
CREATE INDEX idx_file_uploads_gemini_state ON public.file_uploads(gemini_state);
CREATE INDEX idx_file_uploads_uploaded_at ON public.file_uploads(uploaded_at DESC);
COMMENT ON TABLE public.file_uploads IS 'Uploaded files with Gemini FileSearch integration';

-- Configuration Tables

-- Configuration metadata table
CREATE TABLE public.configuration_metadata (
    id integer DEFAULT 1 NOT NULL,
    default_user_role varchar(50) DEFAULT 'user'::character varying NULL,
    hil_enabled bool DEFAULT true NULL,
    response_policy integer DEFAULT 30 NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    hil_disabled_message text DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.'::text NULL,
    CONSTRAINT configuration_metadata_pkey PRIMARY KEY (id),
    CONSTRAINT single_row CHECK ((id = 1)),
    CONSTRAINT valid_default_role CHECK (((default_user_role)::text = ANY ((ARRAY['user'::character varying, 'admin'::character varying, 'human_agent'::character varying])::text[])))
);
COMMENT ON TABLE public.configuration_metadata IS 'Global configuration settings (single row)';
COMMENT ON COLUMN public.configuration_metadata.hil_enabled IS 'Human-in-the-Loop enabled flag';

-- Widget configuration table
CREATE TABLE public.widget_configuration (
    id serial4 NOT NULL,
    display_name varchar(255) DEFAULT 'GLOBISTAAN'::character varying NULL,
    initial_message text DEFAULT 'Hi! What can I help you with?'::text NULL,
    auto_show_duration integer DEFAULT 4 NULL,
    keep_showing_suggested bool DEFAULT true NULL,
    theme varchar(20) DEFAULT 'light'::character varying NULL,
    primary_color varchar(7) DEFAULT '#3B81F6'::character varying NULL,
    use_primary_for_header bool DEFAULT true NULL,
    chat_bubble_color varchar(7) DEFAULT '#3B81F6'::character varying NULL,
    align_bubble varchar(10) DEFAULT 'right'::character varying NULL,
    profile_picture_url text NULL,
    chat_icon_url text NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    profile_zoom numeric(3, 2) DEFAULT 1.00 NULL,
    chat_icon_zoom numeric(3, 2) DEFAULT 1.00 NULL,
    profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL,
    chat_icon_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL,
    profile_picture_filename varchar(255) NULL,
    chat_icon_filename varchar(255) NULL,
    display_chatbot bool DEFAULT true NULL,
    CONSTRAINT valid_align CHECK (((align_bubble)::text = ANY ((ARRAY['left'::character varying, 'right'::character varying])::text[]))),
    CONSTRAINT valid_theme CHECK (((theme)::text = ANY ((ARRAY['light'::character varying, 'dark'::character varying])::text[]))),
    CONSTRAINT widget_configuration_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_widget_config_chat_icon_position ON public.widget_configuration USING gin (chat_icon_position);
CREATE INDEX idx_widget_config_chat_icon_zoom ON public.widget_configuration USING btree (chat_icon_zoom);
CREATE INDEX idx_widget_config_profile_position ON public.widget_configuration USING gin (profile_position);
CREATE INDEX idx_widget_config_profile_zoom ON public.widget_configuration USING btree (profile_zoom);
CREATE INDEX idx_widget_config_updated_at ON public.widget_configuration USING btree (updated_at);
COMMENT ON TABLE public.widget_configuration IS 'Widget display and behavior configuration';
COMMENT ON COLUMN public.widget_configuration.profile_zoom IS 'Zoom level for profile picture (1.00 = 100%)';
COMMENT ON COLUMN public.widget_configuration.chat_icon_zoom IS 'Zoom level for chat icon (1.00 = 100%)';
COMMENT ON COLUMN public.widget_configuration.profile_position IS 'Position offset for profile picture as JSON {"x": number, "y": number}';
COMMENT ON COLUMN public.widget_configuration.chat_icon_position IS 'Position offset for chat icon as JSON {"x": number, "y": number}';

-- Widget suggested messages table
CREATE TABLE public.widget_suggested_messages (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    widget_config_id integer NOT NULL,
    message_text text NOT NULL,
    display_order integer DEFAULT 0 NULL,
    is_active bool DEFAULT true NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT widget_suggested_messages_pkey PRIMARY KEY (id),
    CONSTRAINT widget_suggested_messages_widget_config_id_fkey FOREIGN KEY (widget_config_id) REFERENCES public.widget_configuration(id) ON DELETE CASCADE
);
CREATE INDEX idx_widget_suggested_messages_active ON public.widget_suggested_messages USING btree (is_active);
CREATE INDEX idx_widget_suggested_messages_config ON public.widget_suggested_messages USING btree (widget_config_id);
CREATE INDEX idx_widget_suggested_messages_order ON public.widget_suggested_messages USING btree (display_order);
COMMENT ON TABLE public.widget_suggested_messages IS 'Suggested messages for widget (normalized from array)';

-- Security settings table
CREATE TABLE public.security_settings (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    setting_name varchar(100) NOT NULL,
    setting_value text NULL,
    setting_type varchar(50) DEFAULT 'string'::character varying NULL,
    description text NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT security_settings_pkey PRIMARY KEY (id),
    CONSTRAINT security_settings_setting_name_key UNIQUE (setting_name),
    CONSTRAINT valid_setting_type CHECK (((setting_type)::text = ANY ((ARRAY['string'::character varying, 'integer'::character varying, 'boolean'::character varying, 'json'::character varying])::text[])))
);
CREATE INDEX idx_security_settings_name ON public.security_settings USING btree (setting_name);
COMMENT ON TABLE public.security_settings IS 'Security configuration settings';

-- LLM providers table
CREATE TABLE public.llm_providers (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    provider_name varchar(100) NOT NULL,
    token_limit bigint DEFAULT 0 NULL,
    token_used bigint DEFAULT 0 NULL,
    is_active bool DEFAULT true NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT llm_providers_pkey PRIMARY KEY (id),
    CONSTRAINT llm_providers_provider_name_key UNIQUE (provider_name)
);
CREATE INDEX idx_llm_providers_active ON public.llm_providers USING btree (is_active);
CREATE INDEX idx_llm_providers_name ON public.llm_providers USING btree (provider_name);
COMMENT ON TABLE public.llm_providers IS 'LLM provider configurations and token usage';

-- Persona configurations table
CREATE TABLE public.persona_configurations (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    persona_name varchar(100) NOT NULL,
    system_prompt text NOT NULL,
    is_active bool DEFAULT false NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT persona_configurations_persona_name_key UNIQUE (persona_name),
    CONSTRAINT persona_configurations_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_persona_configurations_active ON public.persona_configurations USING btree (is_active);
CREATE INDEX idx_persona_configurations_name ON public.persona_configurations USING btree (persona_name);
COMMENT ON TABLE public.persona_configurations IS 'AI persona configurations with system prompts';

-- Utility Tables

-- Notifications table
CREATE TABLE public.notifications (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    user_email varchar(255) NOT NULL,
    title varchar(500) NOT NULL,
    message text NOT NULL,
    type varchar(50) DEFAULT 'info'::character varying NULL,
    is_read bool DEFAULT false NULL,
    read_at timestamptz NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT notifications_pkey PRIMARY KEY (id),
    CONSTRAINT valid_notification_type CHECK (((type)::text = ANY ((ARRAY['info'::character varying, 'success'::character varying, 'warning'::character varying, 'error'::character varying])::text[])))
);
CREATE INDEX idx_notifications_created_at ON public.notifications USING btree (created_at DESC);
CREATE INDEX idx_notifications_is_read ON public.notifications USING btree (is_read);
CREATE INDEX idx_notifications_user_email ON public.notifications USING btree (user_email);
CREATE INDEX idx_notifications_user_read ON public.notifications USING btree (user_email, is_read);
COMMENT ON TABLE public.notifications IS 'User notifications';

-- Chat feedback table
CREATE TABLE public.chat_feedback (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    message_id varchar(255) NOT NULL,
    session_id varchar(255) NOT NULL,
    feedback_type varchar(20) NOT NULL,
    user_type varchar(20) DEFAULT 'customer'::character varying NULL,
    created_at timestamp DEFAULT now() NULL,
    CONSTRAINT chat_feedback_pkey PRIMARY KEY (id),
    CONSTRAINT valid_feedback_type CHECK (((feedback_type)::text = ANY ((ARRAY['positive'::character varying, 'negative'::character varying])::text[]))),
    CONSTRAINT valid_user_type CHECK (((user_type)::text = ANY ((ARRAY['customer'::character varying, 'agent'::character varying])::text[])))
);
CREATE INDEX idx_chat_feedback_created_at ON public.chat_feedback USING btree (created_at DESC);
CREATE INDEX idx_chat_feedback_message ON public.chat_feedback USING btree (message_id);
CREATE INDEX idx_chat_feedback_session ON public.chat_feedback USING btree (session_id);
CREATE INDEX idx_chat_feedback_type ON public.chat_feedback USING btree (feedback_type);
CREATE INDEX idx_chat_feedback_user_type ON public.chat_feedback USING btree (user_type);
COMMENT ON TABLE public.chat_feedback IS 'User feedback on chat messages';

-- Token usage log table
CREATE TABLE public.token_usage_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NULL,
    message_id uuid NULL,
    provider varchar(50) NOT NULL,
    model varchar(100) NULL,
    prompt_tokens integer DEFAULT 0 NULL,
    completion_tokens integer DEFAULT 0 NULL,
    total_tokens integer DEFAULT 0 NULL,
    cost_cents integer DEFAULT 0 NULL,
    api_call_type varchar(50) NULL,
    request_metadata jsonb NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    cache_read_tokens integer DEFAULT 0 NULL,
    cache_write_tokens integer DEFAULT 0 NULL,
    input_audio_tokens integer DEFAULT 0 NULL,
    cache_audio_read_tokens integer DEFAULT 0 NULL,
    CONSTRAINT token_usage_log_pkey PRIMARY KEY (id),
    CONSTRAINT token_usage_log_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    CONSTRAINT token_usage_log_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_token_usage_log_created_at ON public.token_usage_log USING btree (created_at DESC);
CREATE INDEX idx_token_usage_log_provider ON public.token_usage_log USING btree (provider);
CREATE INDEX idx_token_usage_log_session ON public.token_usage_log USING btree (session_id);
COMMENT ON TABLE public.token_usage_log IS 'Detailed token usage log for correlating usage with specific API calls';

-- Metrics table
CREATE TABLE public.metrics (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    metric_type varchar(100) NOT NULL,
    metric_name varchar(255) NOT NULL,
    value numeric(20, 4) NULL,
    unit varchar(50) NULL,
    user_email varchar(255) NULL,
    session_id uuid NULL,
    file_upload_id uuid NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    recorded_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT metrics_pkey PRIMARY KEY (id),
    CONSTRAINT metrics_file_upload_id_fkey FOREIGN KEY (file_upload_id) REFERENCES public.file_uploads(id) ON DELETE SET NULL,
    CONSTRAINT metrics_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE SET NULL
);
CREATE INDEX idx_metrics_name ON public.metrics USING btree (metric_name);
CREATE INDEX idx_metrics_recorded_at ON public.metrics USING btree (recorded_at DESC);
CREATE INDEX idx_metrics_type ON public.metrics USING btree (metric_type);
CREATE INDEX idx_metrics_user_email ON public.metrics USING btree (user_email);
COMMENT ON TABLE public.metrics IS 'System metrics and performance tracking';

-- Email OAuth credentials table
CREATE TABLE public.email_oauth_credentials (
    id integer DEFAULT 1 NOT NULL,
    client_id varchar(500) NOT NULL,
    client_secret varchar(500) NOT NULL,
    refresh_token text NOT NULL,
    updated_at timestamp DEFAULT now() NULL,
    CONSTRAINT email_oauth_credentials_pkey PRIMARY KEY (id),
    CONSTRAINT single_row CHECK ((id = 1))
);
COMMENT ON TABLE public.email_oauth_credentials IS 'Email service OAuth credentials (single row)';

-- User unique IDs table
CREATE TABLE public.user_unique_ids (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    email varchar(255) NOT NULL,
    unique_id varchar(100) NOT NULL,
    role varchar(50) NOT NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT user_unique_ids_email_role_key UNIQUE (email, role),
    CONSTRAINT user_unique_ids_pkey PRIMARY KEY (id),
    CONSTRAINT user_unique_ids_role_check CHECK (((role)::text = ANY ((ARRAY['customer'::character varying, 'agent'::character varying, 'admin'::character varying])::text[]))),
    CONSTRAINT user_unique_ids_unique_id_key UNIQUE (unique_id)
);
CREATE INDEX idx_user_unique_ids_email ON public.user_unique_ids USING btree (email);
CREATE INDEX idx_user_unique_ids_role ON public.user_unique_ids USING btree (role);
CREATE INDEX idx_user_unique_ids_unique_id ON public.user_unique_ids USING btree (unique_id);
COMMENT ON TABLE public.user_unique_ids IS 'Unique display IDs for users across different roles';

-- Scraped websites table
CREATE TABLE public.scraped_websites (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    user_id uuid NULL,
    original_url text NOT NULL,
    domain varchar(500) NULL,
    title varchar(1000) NULL,
    content_length integer NULL,
    pages_scraped integer DEFAULT 1 NULL,
    gemini_file_name varchar(500) NULL,
    gemini_file_uri text NULL,
    mime_type varchar(255) DEFAULT 'text/markdown'::character varying NULL,
    size_bytes bigint NULL,
    gemini_state varchar(50) NULL,
    scraped_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    gemini_processed_at timestamptz NULL,
    expires_at timestamptz NULL,
    scraping_config jsonb DEFAULT '{}'::jsonb NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    version integer DEFAULT 1 NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT scraped_websites_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_scraped_websites_domain ON public.scraped_websites USING btree (domain);
CREATE INDEX idx_scraped_websites_gemini_file_name ON public.scraped_websites USING btree (gemini_file_name);
CREATE INDEX idx_scraped_websites_gemini_state ON public.scraped_websites USING btree (gemini_state);
CREATE INDEX idx_scraped_websites_scraped_at ON public.scraped_websites USING btree (scraped_at DESC);
CREATE INDEX idx_scraped_websites_user_id ON public.scraped_websites USING btree (user_id);
COMMENT ON TABLE public.scraped_websites IS 'Scraped website content for knowledge base';

-- API usage table
CREATE TABLE public.api_usage (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    api_provider varchar(100) NOT NULL,
    api_endpoint varchar(255) NULL,
    http_method varchar(10) NULL,
    request_size_bytes integer NULL,
    response_size_bytes integer NULL,
    status_code integer NULL,
    cost_usd numeric(10, 6) NULL,
    tokens_input integer NULL,
    tokens_output integer NULL,
    user_email varchar(255) NULL,
    session_id uuid NULL,
    duration_ms integer NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT api_usage_pkey PRIMARY KEY (id),
    CONSTRAINT api_usage_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE SET NULL
);
CREATE INDEX idx_api_usage_created_at ON public.api_usage USING btree (created_at DESC);
CREATE INDEX idx_api_usage_provider ON public.api_usage USING btree (api_provider);
CREATE INDEX idx_api_usage_user_email ON public.api_usage USING btree (user_email);
COMMENT ON TABLE public.api_usage IS 'API usage tracking and analytics';
COMMENT ON COLUMN public.api_usage.user_email IS 'User email address (from Firebase auth)';

-- Widget scripts table
CREATE TABLE public.widget_scripts (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    config_id varchar(255) NULL,
    script_content text NOT NULL,
    version integer DEFAULT 1 NULL,
    is_active bool DEFAULT true NULL,
    install_count integer DEFAULT 0 NULL,
    last_used_at timestamptz NULL,
    metadata jsonb DEFAULT '{}'::jsonb NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT widget_scripts_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_widget_scripts_config_id ON public.widget_scripts USING btree (config_id);
CREATE INDEX idx_widget_scripts_is_active ON public.widget_scripts USING btree (is_active);
COMMENT ON TABLE public.widget_scripts IS 'Widget installation scripts';

-- Functions

-- Update session feedback function
CREATE OR REPLACE FUNCTION public.update_session_feedback(session_uuid uuid)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    session_id_str VARCHAR(255);
    positive_count INTEGER;
    negative_count INTEGER;
    final_feedback VARCHAR(20);
BEGIN
    -- Get the session_id string from the UUID
    SELECT cs.session_id INTO session_id_str
    FROM chat_sessions cs
    WHERE cs.id = session_uuid;
    
    IF session_id_str IS NULL THEN
        RETURN;
    END IF;
    
    -- Count positive and negative feedback for this session
    SELECT 
        COUNT(*) FILTER (WHERE feedback_type = 'positive'),
        COUNT(*) FILTER (WHERE feedback_type = 'negative')
    INTO positive_count, negative_count
    FROM chat_feedback
    WHERE session_id = session_id_str;
    
    -- Determine session-level feedback
    -- If there's any negative feedback, mark as negative
    -- Otherwise, if there's positive feedback, mark as positive
    -- If no feedback, leave as NULL
    IF negative_count > 0 THEN
        final_feedback := 'negative';
    ELSIF positive_count > 0 THEN
        final_feedback := 'positive';
    ELSE
        final_feedback := NULL;
    END IF;
    
    -- Update the session
    UPDATE chat_sessions
    SET session_feedback = final_feedback,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = session_uuid;
END;
$function$
;

-- Permissions
GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;
GRANT USAGE ON SCHEMA public TO postgres;
