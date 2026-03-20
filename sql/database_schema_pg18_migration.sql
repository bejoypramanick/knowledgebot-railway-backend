SET statement_timeout = '60s';
SET lock_timeout = '20s';

CREATE SCHEMA IF NOT EXISTS public AUTHORIZATION pg_database_owner;

SET jit = on;
SET random_page_cost = 1.1;
SET effective_cache_size = '3GB';
SET work_mem = '25MB';

DO $$
BEGIN
    IF NOT (current_setting('server_version_num')::integer >= 180000) THEN
        RAISE WARNING 'PostgreSQL 18+ required. Current version: %', current_setting('server_version');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    email varchar(255) NOT NULL UNIQUE,
    is_active bool DEFAULT true,
    last_login_at timestamptz NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_user_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users USING btree (email);
CREATE INDEX IF NOT EXISTS idx_users_is_active_id ON public.users(is_active, id DESC);

ALTER TABLE public.users OWNER TO postgres;
GRANT ALL ON TABLE public.users TO postgres;
GRANT ALL ON TABLE public.users TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.roles (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    role_name varchar(50) NOT NULL UNIQUE,
    role_description text,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_roles_role_name ON public.roles USING btree (role_name);

ALTER TABLE public.roles OWNER TO postgres;
GRANT ALL ON TABLE public.roles TO postgres;
GRANT ALL ON TABLE public.roles TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.user_role_mapping (
    user_role_id uuid PRIMARY KEY DEFAULT uuidv7(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
    is_active bool DEFAULT true,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT user_role_mapping_user_role_key UNIQUE (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_role_mapping_user_id ON public.user_role_mapping USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_role_id ON public.user_role_mapping USING btree (role_id);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_is_active_id ON public.user_role_mapping(is_active, user_role_id DESC);

ALTER TABLE public.user_role_mapping OWNER TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    session_id varchar(255) NOT NULL UNIQUE,
    user_role_id uuid REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
    started_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    last_activity_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    ended_at timestamptz NULL,
    is_active bool DEFAULT true,
    message_count int4 DEFAULT 0,
    sentiment varchar(20) CHECK ((sentiment)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text, ('neutral'::character varying)::text])),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    archive_status varchar(20) DEFAULT 'active'::character varying CHECK ((archive_status)::text = ANY (ARRAY[('active'::character varying)::text, ('closed'::character varying)::text, ('archived'::character varying)::text, ('transferred'::character varying)::text])),
    conversation_summary text,
    feedback_type varchar(20) CHECK ((feedback_type)::text = ANY (ARRAY['positive'::text, 'negative'::text])),
    feedback_provided_at timestamptz,
    is_message_read bool DEFAULT false,
    file_search_store_id varchar(255),
    cached_content_id varchar(255)
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_session_id ON public.chat_sessions USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_id_user ON public.chat_sessions(archive_status, id DESC, user_role_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active_id ON public.chat_sessions(is_active, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment_id ON public.chat_sessions(sentiment, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_file_search_id ON public.chat_sessions(file_search_store_id) WHERE file_search_store_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_summary_fts ON public.chat_sessions USING gin(to_tsvector('english'::regconfig, coalesce(conversation_summary, '')));

ALTER TABLE public.chat_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    session_id uuid NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    "role" varchar(50) NOT NULL,
    "content" text NOT NULL,
    used_rag bool DEFAULT false,
    used_postgres bool DEFAULT false,
    confidence_score numeric(3, 2),
    sources jsonb DEFAULT '[]'::jsonb,
    is_message_read bool DEFAULT false,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON public.chat_messages USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_id ON public.chat_messages(role, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_unread ON public.chat_messages(session_id, is_message_read) WHERE is_message_read = false;
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_fts ON public.chat_messages USING gin(to_tsvector('english'::regconfig, "content"));

ALTER TABLE public.chat_messages OWNER TO postgres;
GRANT ALL ON TABLE public.chat_messages TO postgres;
GRANT ALL ON TABLE public.chat_messages TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.session_assignments (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    session_id uuid NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    user_role_id uuid NOT NULL REFERENCES public.user_role_mapping(user_role_id) ON DELETE CASCADE,
    status varchar(50) DEFAULT 'active'::character varying CHECK ((status)::text = ANY (ARRAY[('waiting'::character varying)::text, ('active'::character varying)::text, ('transferred'::character varying)::text, ('ended'::character varying)::text])),
    assigned_at timestamp DEFAULT CURRENT_TIMESTAMP,
    ended_at timestamp NULL,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_session_assignments_session ON public.session_assignments USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_status ON public.session_assignments(user_role_id, status);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_id ON public.session_assignments(status, id DESC);

ALTER TABLE public.session_assignments OWNER TO postgres;
GRANT ALL ON TABLE public.session_assignments TO postgres;
GRANT ALL ON TABLE public.session_assignments TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.file_uploads (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    user_role_id uuid REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
    original_filename varchar(500) NOT NULL,
    display_name varchar(500),
    file_extension varchar(50),
    gemini_file_name varchar(500),
    gemini_file_uri text,
    gemini_state varchar(50) DEFAULT 'pending'::character varying,
    sha256_hash varchar(64),
    file_size int8,
    mime_type varchar(100),
    metadata jsonb DEFAULT '{}'::jsonb,
    "version" int4 DEFAULT 1,
    processed_by_docling boolean DEFAULT false,
    docling_processing_time_ms int4,
    docling_images_extracted int4 DEFAULT 0,
    docling_images_with_ocr int4 DEFAULT 0,
    processing_status varchar(20) DEFAULT 'pending'::character varying CHECK ((processing_status)::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text])),
    error_message text,
    s3_key text,
    processed_content_s3_key text,
    celery_task_id varchar(255),
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_file_uploads_user_status ON public.file_uploads(user_role_id, processing_status);
CREATE INDEX IF NOT EXISTS idx_file_uploads_status_id ON public.file_uploads(processing_status, id DESC);
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_pending ON public.file_uploads(id DESC) WHERE processing_status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_file_uploads_docling ON public.file_uploads(id DESC) WHERE processed_by_docling = true;

ALTER TABLE public.file_uploads OWNER TO postgres;
GRANT ALL ON TABLE public.file_uploads TO postgres;
GRANT ALL ON TABLE public.file_uploads TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.scraped_websites (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    user_role_id uuid REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
    original_url text NOT NULL,
    "domain" varchar(500),
    title varchar(500),
    description text,
    pages_scraped int4 DEFAULT 0,
    content_length int4 DEFAULT 0,
    gemini_state varchar(50) DEFAULT 'pending'::character varying,
    gemini_file_name varchar(500),
    gemini_file_uri text,
    metadata jsonb DEFAULT '{}'::jsonb,
    "version" int4 DEFAULT 1,
    processing_status varchar(20) DEFAULT 'pending'::character varying CHECK ((processing_status)::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text, ('deleted'::character varying)::text])),
    error_message text,
    celery_task_id varchar(255),
    depth int4 DEFAULT 0,
    parent_id uuid REFERENCES public.scraped_websites(id) ON DELETE CASCADE,
    crawl_session_id int4,
    processed_content_s3_key text,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scraped_websites_user_role_id ON public.scraped_websites USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_status_id ON public.scraped_websites(processing_status, id DESC);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain ON public.scraped_websites USING btree (domain);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_pending ON public.scraped_websites(id DESC) WHERE processing_status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_scraped_websites_hierarchy ON public.scraped_websites(crawl_session_id, parent_id, depth);

ALTER TABLE public.scraped_websites OWNER TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.persona_configurations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    persona_name varchar(100) NOT NULL UNIQUE,
    persona_description text,
    system_prompt text NOT NULL,
    is_active bool DEFAULT false,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_persona_configurations_persona_name ON public.persona_configurations USING btree (persona_name);
CREATE INDEX IF NOT EXISTS idx_persona_configurations_is_active_id ON public.persona_configurations(is_active DESC, id DESC);

ALTER TABLE public.persona_configurations OWNER TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.widget_configuration (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    display_name varchar(255) DEFAULT 'GLOBISTAAN'::character varying,
    initial_message text DEFAULT 'Hi! What can I help you with?'::text,
    auto_show_duration int4 DEFAULT 30,
    keep_showing_suggested bool DEFAULT false,
    theme varchar(50) DEFAULT 'light'::character varying,
    primary_color varchar(7) DEFAULT '#007bff'::character varying,
    use_primary_for_header bool DEFAULT true,
    chat_bubble_color varchar(7) DEFAULT '#f8f9fa'::character varying,
    align_bubble varchar(10) DEFAULT 'right'::character varying,
    display_chatbot bool DEFAULT true,
    profile_picture_url text,
    chat_icon_url text,
    profile_picture_filename varchar(255),
    chat_icon_filename varchar(255),
    profile_zoom numeric(3, 2) DEFAULT 1.00,
    chat_icon_zoom numeric(3, 2) DEFAULT 1.00,
    profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb,
    chat_icon_position jsonb DEFAULT '{"x": 20, "y": 20}'::jsonb,
    hil_enabled bool DEFAULT true,
    response_policy int4 DEFAULT 30,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP,
    hil_disabled_message text DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.'::text,
    is_singleton bool DEFAULT true NOT NULL,
    CONSTRAINT widget_config_singleton UNIQUE (is_singleton),
    CONSTRAINT widget_config_singleton_check CHECK (is_singleton = true)
);

ALTER TABLE public.widget_configuration OWNER TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.widget_suggested_messages (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    widget_config_id uuid NOT NULL REFERENCES public.widget_configuration(id) ON DELETE CASCADE,
    message_text text NOT NULL,
    display_order int4 DEFAULT 0,
    is_active bool DEFAULT true,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_widget_suggested_messages_config_id ON public.widget_suggested_messages USING btree (widget_config_id);
CREATE INDEX IF NOT EXISTS idx_widget_suggested_messages_display_order ON public.widget_suggested_messages USING btree (display_order);

ALTER TABLE public.widget_suggested_messages OWNER TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.security_settings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    setting_name varchar(100) NOT NULL UNIQUE,
    setting_value text,
    setting_type varchar(50) DEFAULT 'string'::character varying CHECK ((setting_type)::text = ANY (ARRAY[('string'::character varying)::text, ('integer'::character varying)::text, ('boolean'::character varying)::text, ('json'::character varying)::text])),
    description text,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_security_settings_setting_name ON public.security_settings USING btree (setting_name);

ALTER TABLE public.security_settings OWNER TO postgres;
GRANT ALL ON TABLE public.security_settings TO postgres;
GRANT ALL ON TABLE public.security_settings TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.llm_providers (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    provider_name varchar(100) NOT NULL UNIQUE,
    token_limit int8 DEFAULT 0,
    token_used int8 DEFAULT 0,
    is_active bool DEFAULT true,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_providers_provider_name ON public.llm_providers USING btree (provider_name);
CREATE INDEX IF NOT EXISTS idx_llm_providers_is_active_id ON public.llm_providers(is_active DESC, id DESC);

ALTER TABLE public.llm_providers OWNER TO postgres;
GRANT ALL ON TABLE public.llm_providers TO postgres;
GRANT ALL ON TABLE public.llm_providers TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.api_usage (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    api_provider varchar(100) NOT NULL,
    api_endpoint varchar(255),
    http_method varchar(10),
    request_size_bytes int4 DEFAULT 0,
    response_size_bytes int4 DEFAULT 0,
    tokens_input int4 DEFAULT 0,
    tokens_output int4 DEFAULT 0,
    user_email varchar(255),
    request_metadata jsonb DEFAULT '{}'::jsonb,
    last_used_at timestamptz,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_usage_provider_id ON public.api_usage(api_provider, id DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint ON public.api_usage USING btree (api_endpoint);
CREATE INDEX IF NOT EXISTS idx_api_usage_user_email ON public.api_usage USING btree (user_email);

ALTER TABLE public.api_usage OWNER TO postgres;
GRANT ALL ON TABLE public.api_usage TO postgres;
GRANT ALL ON TABLE public.api_usage TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.token_usage_log (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    session_id uuid REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    message_id uuid REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    provider varchar(50) NOT NULL,
    model varchar(100),
    prompt_tokens int4 DEFAULT 0,
    completion_tokens int4 DEFAULT 0,
    total_tokens int4 DEFAULT 0,
    cost_cents int4 DEFAULT 0,
    api_call_type varchar(50),
    request_metadata jsonb,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_token_usage_log_session_id ON public.token_usage_log USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_message_id ON public.token_usage_log USING btree (message_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider_id ON public.token_usage_log(provider, id DESC);

ALTER TABLE public.token_usage_log OWNER TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.metrics (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    metric_type varchar(100) NOT NULL,
    metric_name varchar(255) NOT NULL,
    value numeric(20, 4),
    unit varchar(50),
    tags jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT metrics_type_name_unique UNIQUE (metric_type, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_metrics_type_id ON public.metrics(metric_type, id DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON public.metrics USING btree (metric_name);

ALTER TABLE public.metrics OWNER TO postgres;
GRANT ALL ON TABLE public.metrics TO postgres;
GRANT ALL ON TABLE public.metrics TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.notifications (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    user_email varchar(255) NOT NULL,
    title varchar(500) NOT NULL,
    message text NOT NULL,
    "type" varchar(20) DEFAULT 'info'::character varying CHECK (("type")::text = ANY (ARRAY[('info'::character varying)::text, ('success'::character varying)::text, ('warning'::character varying)::text, ('error'::character varying)::text])),
    is_read bool DEFAULT false,
    read_at timestamptz,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_is_read ON public.notifications(user_email, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_type_id ON public.notifications("type", id DESC);

ALTER TABLE public.notifications OWNER TO postgres;
GRANT ALL ON TABLE public.notifications TO postgres;
GRANT ALL ON TABLE public.notifications TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.notification_settings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    user_email varchar(255) NOT NULL,
    notification_type varchar(100) NOT NULL,
    is_enabled bool DEFAULT true,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.notification_settings OWNER TO postgres;
GRANT ALL ON TABLE public.notification_settings TO postgres;
GRANT ALL ON TABLE public.notification_settings TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.service_health_checks (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    response_time_ms INTEGER,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_service_health_checks_service_checked
    ON public.service_health_checks(service_name, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_status_checked
    ON public.service_health_checks(status, checked_at DESC) WHERE status != 'healthy';

ALTER TABLE public.service_health_checks OWNER TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.admin_sessions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    session_id VARCHAR(36) UNIQUE NOT NULL,
    user_role_id uuid NOT NULL,
    email VARCHAR(255) NOT NULL CHECK (email != ''),
    role_name VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    browser VARCHAR(100),
    os VARCHAR(100),
    device_type VARCHAR(50),
    login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    logout_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    logout_reason VARCHAR(100),
    action_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT admin_sessions_session_id_format
        CHECK (session_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT admin_sessions_logout_after_login
        CHECK (logout_at IS NULL OR logout_at >= login_at),
    CONSTRAINT admin_sessions_expires_in_future
        CHECK (expires_at > login_at)
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_email_active_id
    ON public.admin_sessions(email, is_active, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_active_expires
    ON public.admin_sessions(is_active, expires_at) WHERE is_active = true;

ALTER TABLE public.admin_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.admin_sessions TO postgres;
GRANT ALL ON TABLE public.admin_sessions TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.admin_actions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    action_id VARCHAR(36) UNIQUE NOT NULL,
    session_id uuid NOT NULL REFERENCES public.admin_sessions(id) ON DELETE CASCADE,
    user_role_id uuid NOT NULL,
    email VARCHAR(255) NOT NULL CHECK (email != ''),
    role_name VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    action_category VARCHAR(50) NOT NULL,
    http_method VARCHAR(10),
    endpoint VARCHAR(255),
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    request_params JSONB,
    request_body JSONB,
    response_status INTEGER,
    response_body JSONB,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    success BOOLEAN NOT NULL DEFAULT true,
    error_message TEXT,
    error_code VARCHAR(50),
    ip_address VARCHAR(45),
    user_agent TEXT,
    correlation_id VARCHAR(36),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT admin_actions_action_id_format
        CHECK (action_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
);

CREATE INDEX IF NOT EXISTS idx_admin_actions_category_id
    ON public.admin_actions(action_category, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_email_id
    ON public.admin_actions(email, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_session_id
    ON public.admin_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_admin_actions_failed
    ON public.admin_actions(id DESC) WHERE success = false;

ALTER TABLE public.admin_actions OWNER TO postgres;
GRANT ALL ON TABLE public.admin_actions TO postgres;
GRANT ALL ON TABLE public.admin_actions TO pg_database_owner;

CREATE OR REPLACE VIEW public.admin_sessions_analytics AS
SELECT
    DATE(login_at) as login_date,
    COUNT(*) as total_sessions,
    COUNT(DISTINCT email) as unique_users,
    COUNT(*) FILTER (WHERE is_active = true) as active_sessions,
    AVG(EXTRACT(EPOCH FROM (COALESCE(logout_at, CURRENT_TIMESTAMP) - login_at))) as avg_duration_seconds,
    MAX(EXTRACT(EPOCH FROM (COALESCE(logout_at, CURRENT_TIMESTAMP) - login_at))) as max_duration_seconds
FROM admin_sessions
GROUP BY DATE(login_at)
ORDER BY login_date DESC;

CREATE OR REPLACE VIEW public.admin_actions_analytics AS
SELECT
    action_category,
    COUNT(*) as total_actions,
    COUNT(*) FILTER (WHERE success = true) as successful_actions,
    COUNT(*) FILTER (WHERE success = false) as failed_actions,
    ROUND(100.0 * COUNT(*) FILTER (WHERE success = true) / COUNT(*), 2) as success_rate_percent,
    ROUND(AVG(duration_ms), 2) as avg_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    MIN(duration_ms) as min_duration_ms
FROM admin_actions
GROUP BY action_category
ORDER BY total_actions DESC;

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF (NEW IS DISTINCT FROM OLD) THEN
        NEW.updated_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$function$;

ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO public;

DROP TRIGGER IF EXISTS users_updated_at_trigger ON public.users;
CREATE TRIGGER users_updated_at_trigger BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS roles_updated_at_trigger ON public.roles;
CREATE TRIGGER roles_updated_at_trigger BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS user_role_mapping_updated_at_trigger ON public.user_role_mapping;
CREATE TRIGGER user_role_mapping_updated_at_trigger BEFORE UPDATE ON public.user_role_mapping FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS chat_sessions_updated_at_trigger ON public.chat_sessions;
CREATE TRIGGER chat_sessions_updated_at_trigger BEFORE UPDATE ON public.chat_sessions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS chat_messages_updated_at_trigger ON public.chat_messages;
CREATE TRIGGER chat_messages_updated_at_trigger BEFORE UPDATE ON public.chat_messages FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS session_assignments_updated_at_trigger ON public.session_assignments;
CREATE TRIGGER session_assignments_updated_at_trigger BEFORE UPDATE ON public.session_assignments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS file_uploads_updated_at_trigger ON public.file_uploads;
CREATE TRIGGER file_uploads_updated_at_trigger BEFORE UPDATE ON public.file_uploads FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS scraped_websites_updated_at_trigger ON public.scraped_websites;
CREATE TRIGGER scraped_websites_updated_at_trigger BEFORE UPDATE ON public.scraped_websites FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS persona_configurations_updated_at_trigger ON public.persona_configurations;
CREATE TRIGGER persona_configurations_updated_at_trigger BEFORE UPDATE ON public.persona_configurations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS widget_configuration_updated_at_trigger ON public.widget_configuration;
CREATE TRIGGER widget_configuration_updated_at_trigger BEFORE UPDATE ON public.widget_configuration FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS widget_suggested_messages_updated_at_trigger ON public.widget_suggested_messages;
CREATE TRIGGER widget_suggested_messages_updated_at_trigger BEFORE UPDATE ON public.widget_suggested_messages FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS security_settings_updated_at_trigger ON public.security_settings;
CREATE TRIGGER security_settings_updated_at_trigger BEFORE UPDATE ON public.security_settings FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS llm_providers_updated_at_trigger ON public.llm_providers;
CREATE TRIGGER llm_providers_updated_at_trigger BEFORE UPDATE ON public.llm_providers FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS api_usage_updated_at_trigger ON public.api_usage;
CREATE TRIGGER api_usage_updated_at_trigger BEFORE UPDATE ON public.api_usage FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS token_usage_log_updated_at_trigger ON public.token_usage_log;
CREATE TRIGGER token_usage_log_updated_at_trigger BEFORE UPDATE ON public.token_usage_log FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS metrics_updated_at_trigger ON public.metrics;
CREATE TRIGGER metrics_updated_at_trigger BEFORE UPDATE ON public.metrics FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS notifications_updated_at_trigger ON public.notifications;
CREATE TRIGGER notifications_updated_at_trigger BEFORE UPDATE ON public.notifications FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS notification_settings_updated_at_trigger ON public.notification_settings;
CREATE TRIGGER notification_settings_updated_at_trigger BEFORE UPDATE ON public.notification_settings FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS admin_sessions_updated_at_trigger ON public.admin_sessions;
CREATE TRIGGER admin_sessions_updated_at_trigger BEFORE UPDATE ON public.admin_sessions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;
GRANT USAGE ON SCHEMA public TO postgres;

INSERT INTO public.roles (role_name, role_description)
VALUES
    ('admin', 'System administrator with full access'),
    ('human_agent', 'Human agent who can handle sessions'),
    ('user', 'Regular user with basic access')
ON CONFLICT (role_name) DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO public.persona_configurations (persona_name, persona_description, system_prompt, is_active)
VALUES
    ('KnowledgeBot', 'Helpful AI assistant', 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management.', true),
    ('Custom', 'User customizable', '', false),
    ('Friendly Receptionist', 'Warm receptionist', 'You are a warm and professional Friendly Receptionist.', false),
    ('Upselling Assistant', 'Strategic upselling', 'You are a strategic Upselling Assistant.', false),
    ('Fast Paced Problem Solver', 'Quick solutions', 'You are a Fast Paced Problem Solver.', false),
    ('Knowledge Based Expert', 'Documentation expert', 'You are a Knowledge Based Expert.', false),
    ('The Agile Troubleshooter', 'Diagnostic solver', 'You are The Agile Troubleshooter.', false),
    ('The Welcoming Guide', 'Onboarding specialist', 'You are The Welcoming Guide.', false)
ON CONFLICT (persona_name) DO NOTHING;

DO $$
DECLARE
    v_user_id uuid;
    v_admin_role_id uuid;
    v_agent_role_id uuid;
BEGIN
    INSERT INTO public.users (email)
    VALUES ('globistaan@gmail.com')
    ON CONFLICT (email) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_user_id;

    SELECT id INTO v_admin_role_id FROM public.roles WHERE role_name = 'admin';
    SELECT id INTO v_agent_role_id FROM public.roles WHERE role_name = 'human_agent';

    INSERT INTO public.user_role_mapping (user_id, role_id)
    VALUES (v_user_id, v_admin_role_id), (v_user_id, v_agent_role_id)
    ON CONFLICT (user_id, role_id) DO UPDATE SET
        is_active = true,
        updated_at = CURRENT_TIMESTAMP;
END $$;

INSERT INTO public.widget_configuration (display_name)
VALUES ('GLOBISTAAN')
ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW public.v_pg18_skip_scan_candidates AS
SELECT
    schemaname,
    relname as tablename,
    indexrelname as indexname,
    idx_scan,
    CASE
        WHEN idx_scan > 0 THEN 'ACTIVE'
        ELSE 'UNUSED'
    END as status
FROM pg_stat_user_indexes
WHERE indexrelname LIKE '%_id' OR indexrelname LIKE '%_status%'
ORDER BY idx_scan DESC;

CREATE OR REPLACE VIEW public.v_pg18_virtual_columns AS
SELECT
    table_schema,
    table_name,
    column_name,
    data_type,
    'VIRTUAL' as column_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND generation_expression IS NOT NULL;

CREATE OR REPLACE VIEW public.v_pg18_uuid_primary_keys AS
SELECT
    n.nspname as schemaname,
    c.relname as tablename,
    a.attname as column_name,
    t.typname as column_type,
    CASE
        WHEN t.typname = 'uuid' THEN 'UUID v7 (PG18)'
        WHEN t.typname = 'int4' THEN 'SERIAL4 (Legacy)'
        ELSE t.typname
    END as key_type
FROM pg_class c
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_index i ON c.oid = i.indrelid
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
JOIN pg_type t ON a.atttypid = t.oid
WHERE n.nspname = 'public'
  AND i.indisprimary
ORDER BY n.nspname, c.relname;

RESET statement_timeout;
RESET lock_timeout;

SELECT
    'PostgreSQL 18 Migration Complete' as status,
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') as tables,
    (SELECT COUNT(*) FROM information_schema.views WHERE table_schema = 'public') as views,
    (SELECT COUNT(*) FROM pg_stat_user_indexes) as indexes;
