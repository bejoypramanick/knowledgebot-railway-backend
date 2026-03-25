CREATE SCHEMA IF NOT EXISTS public AUTHORIZATION pg_database_owner;
CREATE EXTENSION IF NOT EXISTS vector;

COMMENT ON SCHEMA public IS 'standard public schema';

CREATE TABLE IF NOT EXISTS public.admin_sessions ( id uuid DEFAULT uuidv7() NOT NULL, session_id varchar(36) NOT NULL, user_role_id uuid NOT NULL, email varchar(255) NOT NULL, role_name varchar(50) NOT NULL, ip_address varchar(45) NULL, user_agent text NULL, browser varchar(100) NULL, os varchar(100) NULL, device_type varchar(50) NULL, login_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, logout_at timestamptz NULL, last_activity_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, expires_at timestamptz NOT NULL, is_active bool DEFAULT true NOT NULL, logout_reason varchar(100) NULL, action_count int4 DEFAULT 0 NOT NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, CONSTRAINT admin_sessions_email_check CHECK (((email)::text <> ''::text)), CONSTRAINT admin_sessions_expires_in_future CHECK ((expires_at > login_at)), CONSTRAINT admin_sessions_logout_after_login CHECK (((logout_at IS NULL) OR (logout_at >= login_at))), CONSTRAINT admin_sessions_pkey PRIMARY KEY (id), CONSTRAINT admin_sessions_session_id_format CHECK (((session_id)::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text)), CONSTRAINT admin_sessions_session_id_key UNIQUE (session_id));
CREATE INDEX IF NOT EXISTS idx_admin_sessions_active_expires ON public.admin_sessions USING btree (is_active, expires_at) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_email_active_id ON public.admin_sessions USING btree (email, is_active, id DESC);

CREATE OR REPLACE TRIGGER admin_sessions_updated_at_trigger before
update
    on
    public.admin_sessions for each row execute function update_updated_at_column();

ALTER TABLE public.admin_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.admin_sessions TO postgres;
GRANT ALL ON TABLE public.admin_sessions TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.api_usage ( id uuid DEFAULT uuidv7() NOT NULL, api_provider varchar(100) NOT NULL, api_endpoint varchar(255) NULL, http_method varchar(10) NULL, request_size_bytes int4 DEFAULT 0 NULL, response_size_bytes int4 DEFAULT 0 NULL, tokens_input int4 DEFAULT 0 NULL, tokens_output int4 DEFAULT 0 NULL, user_email varchar(255) NULL, request_metadata jsonb DEFAULT '{}'::jsonb NULL, last_used_at timestamptz NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, token_cost_cents int4 GENERATED ALWAYS AS (tokens_input * 3 + tokens_output * 12) STORED NULL, total_request_response_bytes int4 GENERATED ALWAYS AS (COALESCE(request_size_bytes, 0) + COALESCE(response_size_bytes, 0)) STORED NULL, CONSTRAINT api_usage_pkey PRIMARY KEY (id));
CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint_perf ON public.api_usage USING btree (api_endpoint, http_method, created_at DESC) INCLUDE (response_size_bytes, tokens_output, token_cost_cents);
CREATE INDEX IF NOT EXISTS idx_api_usage_expensive_calls ON public.api_usage USING btree (created_at DESC) INCLUDE (api_provider, tokens_output, request_size_bytes, token_cost_cents) WHERE (token_cost_cents > 1000);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider_activity ON public.api_usage USING btree (api_provider, created_at DESC) INCLUDE (http_method, tokens_input, tokens_output, user_email, token_cost_cents);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider_id ON public.api_usage USING btree (api_provider, id DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_user_activity ON public.api_usage USING btree (user_email, created_at DESC) INCLUDE (api_provider, api_endpoint, tokens_input, tokens_output, token_cost_cents);

CREATE OR REPLACE TRIGGER api_usage_updated_at_trigger before
update
    on
    public.api_usage for each row execute function update_updated_at_column();

ALTER TABLE public.api_usage OWNER TO postgres;
GRANT ALL ON TABLE public.api_usage TO postgres;
GRANT ALL ON TABLE public.api_usage TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.llm_providers ( id uuid DEFAULT uuidv7() NOT NULL, provider_name varchar(100) NOT NULL, token_limit int8 DEFAULT 0 NULL, token_used int8 DEFAULT 0 NULL, is_active bool DEFAULT true NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, tokens_remaining int8 GENERATED ALWAYS AS (token_limit - token_used) STORED NULL, token_utilization_percent numeric(5, 2) GENERATED ALWAYS AS (
CASE
    WHEN token_limit = 0 THEN 0::numeric
    ELSE round(token_used::numeric / token_limit::numeric * 100::numeric, 2)
END) STORED NULL, CONSTRAINT llm_providers_pkey PRIMARY KEY (id), CONSTRAINT llm_providers_provider_name_key UNIQUE (provider_name));
CREATE INDEX IF NOT EXISTS idx_llm_providers_critical ON public.llm_providers USING btree (provider_name) WHERE ((tokens_remaining < 100000) AND (is_active = true));
CREATE INDEX IF NOT EXISTS idx_llm_providers_is_active_id ON public.llm_providers USING btree (is_active DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_llm_providers_lookup ON public.llm_providers USING btree (provider_name) INCLUDE (is_active, token_limit, token_used, tokens_remaining);

CREATE OR REPLACE TRIGGER llm_providers_updated_at_trigger before
update
    on
    public.llm_providers for each row execute function update_updated_at_column();

ALTER TABLE public.llm_providers OWNER TO postgres;
GRANT ALL ON TABLE public.llm_providers TO postgres;
GRANT ALL ON TABLE public.llm_providers TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.metrics ( id uuid DEFAULT uuidv7() NOT NULL, metric_type varchar(100) NOT NULL, metric_name varchar(255) NOT NULL, value numeric(20, 4) NULL, unit varchar(50) NULL, tags jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT metrics_pkey PRIMARY KEY (id), CONSTRAINT metrics_type_name_unique UNIQUE (metric_type, metric_name));
CREATE INDEX IF NOT EXISTS idx_metrics_name_covering ON public.metrics USING btree (metric_name, created_at DESC) INCLUDE (metric_type, value);
CREATE INDEX IF NOT EXISTS idx_metrics_type_covering ON public.metrics USING btree (metric_type, created_at DESC) INCLUDE (metric_name, value);
CREATE INDEX IF NOT EXISTS idx_metrics_type_id ON public.metrics USING btree (metric_type, id DESC);

CREATE OR REPLACE TRIGGER metrics_updated_at_trigger before
update
    on
    public.metrics for each row execute function update_updated_at_column();

ALTER TABLE public.metrics OWNER TO postgres;
GRANT ALL ON TABLE public.metrics TO postgres;
GRANT ALL ON TABLE public.metrics TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.notification_settings ( id uuid DEFAULT uuidv7() NOT NULL, user_email varchar(255) NOT NULL, notification_type varchar(100) NOT NULL, is_enabled bool DEFAULT true NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT notification_settings_pkey PRIMARY KEY (id));

CREATE OR REPLACE TRIGGER notification_settings_updated_at_trigger before
update
    on
    public.notification_settings for each row execute function update_updated_at_column();

ALTER TABLE public.notification_settings OWNER TO postgres;
GRANT ALL ON TABLE public.notification_settings TO postgres;
GRANT ALL ON TABLE public.notification_settings TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.notifications ( id uuid DEFAULT uuidv7() NOT NULL, user_email varchar(255) NOT NULL, title varchar(500) NOT NULL, message text NOT NULL, "type" varchar(20) DEFAULT 'info'::character varying NULL, is_read bool DEFAULT false NULL, read_at timestamptz NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT notifications_pkey PRIMARY KEY (id), CONSTRAINT notifications_type_check CHECK (((type)::text = ANY (ARRAY[('info'::character varying)::text, ('success'::character varying)::text, ('warning'::character varying)::text, ('error'::character varying)::text]))));
CREATE INDEX IF NOT EXISTS idx_notifications_type_id ON public.notifications USING btree (type, id DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON public.notifications USING btree (user_email) WHERE (is_read = false);
CREATE INDEX IF NOT EXISTS idx_notifications_user_covering ON public.notifications USING btree (user_email, created_at DESC) INCLUDE (is_read, type, message);
CREATE INDEX IF NOT EXISTS idx_notifications_user_is_read ON public.notifications USING btree (user_email, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_user_status ON public.notifications USING btree (user_email, is_read, created_at DESC);

CREATE OR REPLACE TRIGGER notifications_updated_at_trigger before
update
    on
    public.notifications for each row execute function update_updated_at_column();

ALTER TABLE public.notifications OWNER TO postgres;
GRANT ALL ON TABLE public.notifications TO postgres;
GRANT ALL ON TABLE public.notifications TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.persona_configurations ( id uuid DEFAULT uuidv7() NOT NULL, persona_name varchar(100) NOT NULL, persona_description text NULL, system_prompt text NOT NULL, is_active bool DEFAULT false NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT persona_configurations_persona_name_key UNIQUE (persona_name), CONSTRAINT persona_configurations_pkey PRIMARY KEY (id));
CREATE INDEX IF NOT EXISTS idx_persona_active_info ON public.persona_configurations USING btree (is_active, persona_name) INCLUDE (system_prompt, persona_description) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_persona_configurations_is_active_id ON public.persona_configurations USING btree (is_active DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_persona_configurations_persona_name ON public.persona_configurations USING btree (persona_name);
CREATE INDEX IF NOT EXISTS idx_persona_description_fts ON public.persona_configurations USING gin (to_tsvector('english'::regconfig, COALESCE(persona_description, ''::text))) WHERE (persona_description IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_persona_prompt_fts ON public.persona_configurations USING gin (to_tsvector('english'::regconfig, system_prompt));

CREATE OR REPLACE TRIGGER persona_configurations_updated_at_trigger before
update
    on
    public.persona_configurations for each row execute function update_updated_at_column();

ALTER TABLE public.persona_configurations OWNER TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.roles ( id uuid DEFAULT uuidv7() NOT NULL, role_name varchar(50) NOT NULL, role_description text NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT roles_pkey PRIMARY KEY (id), CONSTRAINT roles_role_name_key UNIQUE (role_name));
CREATE INDEX IF NOT EXISTS idx_roles_description_fts ON public.roles USING gin (to_tsvector('english'::regconfig, COALESCE(role_description, ''::text))) WHERE (role_description IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_roles_role_name ON public.roles USING btree (role_name);

CREATE OR REPLACE TRIGGER roles_updated_at_trigger before
update
    on
    public.roles for each row execute function update_updated_at_column();

ALTER TABLE public.roles OWNER TO postgres;
GRANT ALL ON TABLE public.roles TO postgres;
GRANT ALL ON TABLE public.roles TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.security_settings ( id uuid DEFAULT uuidv7() NOT NULL, setting_name varchar(100) NOT NULL, setting_value text NULL, setting_type varchar(50) DEFAULT 'string'::character varying NULL, description text NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT security_settings_pkey PRIMARY KEY (id), CONSTRAINT security_settings_setting_name_key UNIQUE (setting_name), CONSTRAINT security_settings_setting_type_check CHECK (((setting_type)::text = ANY (ARRAY[('string'::character varying)::text, ('integer'::character varying)::text, ('boolean'::character varying)::text, ('json'::character varying)::text]))));
CREATE INDEX IF NOT EXISTS idx_security_settings_lookup ON public.security_settings USING btree (setting_name) INCLUDE (setting_value, setting_type);
CREATE INDEX IF NOT EXISTS idx_security_settings_setting_name ON public.security_settings USING btree (setting_name);
CREATE INDEX IF NOT EXISTS idx_security_settings_type ON public.security_settings USING btree (setting_type) INCLUDE (setting_name, setting_value);

CREATE OR REPLACE TRIGGER security_settings_updated_at_trigger before
update
    on
    public.security_settings for each row execute function update_updated_at_column();

ALTER TABLE public.security_settings OWNER TO postgres;
GRANT ALL ON TABLE public.security_settings TO postgres;
GRANT ALL ON TABLE public.security_settings TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.service_health_checks ( id uuid DEFAULT uuidv7() NOT NULL, service_name varchar(100) NOT NULL, status varchar(20) NOT NULL, response_time_ms int4 NULL, checked_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, error_message text NULL, metadata jsonb NULL, CONSTRAINT service_health_checks_pkey PRIMARY KEY (id));
CREATE INDEX IF NOT EXISTS idx_service_health_checks_service_checked ON public.service_health_checks USING btree (service_name, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_status_checked ON public.service_health_checks USING btree (status, checked_at DESC) WHERE ((status)::text <> 'healthy'::text);

ALTER TABLE public.service_health_checks OWNER TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.users ( id uuid DEFAULT uuidv7() NOT NULL, email varchar(255) NOT NULL, is_active bool DEFAULT true NULL, last_login_at timestamptz NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, email_domain varchar(255) GENERATED ALWAYS AS (SUBSTRING(email FROM POSITION(('@'::text) IN (email)) + 1)) STORED NULL, CONSTRAINT users_email_key UNIQUE (email), CONSTRAINT users_pkey PRIMARY KEY (id), CONSTRAINT valid_user_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text)));
CREATE INDEX IF NOT EXISTS idx_users_active ON public.users USING btree (created_at DESC) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_users_email_active ON public.users USING btree (email, is_active);
CREATE INDEX IF NOT EXISTS idx_users_email_covering ON public.users USING btree (email) INCLUDE (is_active, last_login_at, created_at);
CREATE INDEX IF NOT EXISTS idx_users_is_active_id ON public.users USING btree (is_active, id DESC);

CREATE OR REPLACE TRIGGER users_updated_at_trigger before
update
    on
    public.users for each row execute function update_updated_at_column();

ALTER TABLE public.users OWNER TO postgres;
GRANT ALL ON TABLE public.users TO postgres;
GRANT ALL ON TABLE public.users TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.widget_configuration ( id uuid DEFAULT uuidv7() NOT NULL, display_name varchar(255) DEFAULT 'GLOBISTAAN'::character varying NULL, initial_message text DEFAULT 'Hi! What can I help you with?'::text NULL, auto_show_duration int4 DEFAULT 30 NULL, keep_showing_suggested bool DEFAULT false NULL, theme varchar(50) DEFAULT 'light'::character varying NULL, primary_color varchar(7) DEFAULT '#007bff'::character varying NULL, use_primary_for_header bool DEFAULT true NULL, chat_bubble_color varchar(7) DEFAULT '#f8f9fa'::character varying NULL, align_bubble varchar(10) DEFAULT 'right'::character varying NULL, display_chatbot bool DEFAULT true NULL, profile_picture_url text NULL, chat_icon_url text NULL, profile_picture_filename varchar(255) NULL, chat_icon_filename varchar(255) NULL, profile_zoom numeric(3, 2) DEFAULT 1.00 NULL, chat_icon_zoom numeric(3, 2) DEFAULT 1.00 NULL, profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL, chat_icon_position jsonb DEFAULT '{"x": 20, "y": 20}'::jsonb NULL, hil_enabled bool DEFAULT true NULL, response_policy int4 DEFAULT 30 NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, hil_disabled_message text DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.'::text NULL, is_singleton bool DEFAULT true NOT NULL, CONSTRAINT widget_config_singleton UNIQUE (is_singleton), CONSTRAINT widget_config_singleton_check CHECK ((is_singleton = true)), CONSTRAINT widget_configuration_pkey PRIMARY KEY (id));
CREATE INDEX IF NOT EXISTS idx_widget_display_config ON public.widget_configuration USING btree (display_chatbot) INCLUDE (hil_enabled, response_policy, display_name, theme) WHERE (display_chatbot = true);
CREATE INDEX IF NOT EXISTS idx_widget_theme_config ON public.widget_configuration USING btree (theme) INCLUDE (primary_color, chat_bubble_color, display_chatbot);

CREATE OR REPLACE TRIGGER widget_configuration_updated_at_trigger before
update
    on
    public.widget_configuration for each row execute function update_updated_at_column();

ALTER TABLE public.widget_configuration OWNER TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.admin_actions ( id uuid DEFAULT uuidv7() NOT NULL, action_id varchar(36) NOT NULL, session_id uuid NOT NULL, user_role_id uuid NOT NULL, email varchar(255) NOT NULL, role_name varchar(50) NOT NULL, action_type varchar(100) NOT NULL, action_category varchar(50) NOT NULL, http_method varchar(10) NULL, endpoint varchar(255) NULL, resource_type varchar(100) NULL, resource_id varchar(255) NULL, request_params jsonb NULL, request_body jsonb NULL, response_status int4 NULL, response_body jsonb NULL, duration_ms int4 NULL, success bool DEFAULT true NOT NULL, error_message text NULL, error_code varchar(50) NULL, ip_address varchar(45) NULL, user_agent text NULL, correlation_id varchar(36) NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL, CONSTRAINT admin_actions_action_id_format CHECK (((action_id)::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text)), CONSTRAINT admin_actions_action_id_key UNIQUE (action_id), CONSTRAINT admin_actions_duration_ms_check CHECK (((duration_ms IS NULL) OR (duration_ms >= 0))), CONSTRAINT admin_actions_email_check CHECK (((email)::text <> ''::text)), CONSTRAINT admin_actions_pkey PRIMARY KEY (id), CONSTRAINT admin_actions_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.admin_sessions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_admin_actions_category_id ON public.admin_actions USING btree (action_category, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_email_id ON public.admin_actions USING btree (email, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_failed ON public.admin_actions USING btree (id DESC) WHERE (success = false);
CREATE INDEX IF NOT EXISTS idx_admin_actions_session_id ON public.admin_actions USING btree (session_id);

ALTER TABLE public.admin_actions OWNER TO postgres;
GRANT ALL ON TABLE public.admin_actions TO postgres;
GRANT ALL ON TABLE public.admin_actions TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.user_role_mapping ( user_role_id uuid DEFAULT uuidv7() NOT NULL, user_id uuid NOT NULL, role_id uuid NOT NULL, is_active bool DEFAULT true NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT user_role_mapping_pkey PRIMARY KEY (user_role_id), CONSTRAINT user_role_mapping_user_role_key UNIQUE NULLS NOT DISTINCT (user_id, role_id), CONSTRAINT user_role_mapping_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE, CONSTRAINT user_role_mapping_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_active ON public.user_role_mapping USING btree (user_id, is_active) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_is_active_id ON public.user_role_mapping USING btree (is_active, user_role_id DESC);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_role_covering ON public.user_role_mapping USING btree (role_id) INCLUDE (user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_user_covering ON public.user_role_mapping USING btree (user_id) INCLUDE (role_id, is_active, created_at);

CREATE OR REPLACE TRIGGER user_role_mapping_updated_at_trigger before
update
    on
    public.user_role_mapping for each row execute function update_updated_at_column();

ALTER TABLE public.user_role_mapping OWNER TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.widget_suggested_messages ( id uuid DEFAULT uuidv7() NOT NULL, widget_config_id uuid NOT NULL, message_text text NOT NULL, display_order int4 DEFAULT 0 NULL, is_active bool DEFAULT true NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT widget_suggested_messages_pkey PRIMARY KEY (id), CONSTRAINT widget_suggested_messages_widget_config_id_fkey FOREIGN KEY (widget_config_id) REFERENCES public.widget_configuration(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_widget_messages_active ON public.widget_suggested_messages USING btree (widget_config_id) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_widget_messages_config_active ON public.widget_suggested_messages USING btree (widget_config_id, is_active, display_order) INCLUDE (message_text);
CREATE INDEX IF NOT EXISTS idx_widget_messages_config_order ON public.widget_suggested_messages USING btree (widget_config_id, display_order) INCLUDE (message_text, is_active);

CREATE OR REPLACE TRIGGER widget_suggested_messages_updated_at_trigger before
update
    on
    public.widget_suggested_messages for each row execute function update_updated_at_column();

ALTER TABLE public.widget_suggested_messages OWNER TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.chat_sessions ( id uuid DEFAULT uuidv7() NOT NULL, user_role_id uuid NULL, started_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, last_activity_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, ended_at timestamptz NULL, is_active bool DEFAULT true NULL, message_count int4 DEFAULT 0 NULL, sentiment varchar(20) NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, archive_status varchar(20) DEFAULT 'active'::character varying NULL, feedback_type varchar(20) NULL, feedback_provided_at timestamptz NULL, duration_minutes numeric GENERATED ALWAYS AS (round(EXTRACT(epoch FROM COALESCE(ended_at, last_activity_at) - started_at) / 60.0, 2)) STORED NULL, sentiment_score int4 GENERATED ALWAYS AS (
CASE
    WHEN sentiment::text = 'positive'::text THEN 1
    WHEN sentiment::text = 'negative'::text THEN '-1'::integer
    ELSE 0
END) STORED NULL, is_session_read bool DEFAULT false NULL, total_output_chars int4 DEFAULT 0 NULL, total_character_count int4 DEFAULT 0 NULL, total_word_count int4 DEFAULT 0 NULL, total_token_count int4 DEFAULT 0 NULL, total_message_token_count int4 DEFAULT 0 NULL, total_prompt_token_count int4 DEFAULT 0 NULL, total_completion_token_count int4 DEFAULT 0 NULL, total_system_prompt_token_count int4 DEFAULT 0 NULL, total_history_token_count int4 DEFAULT 0 NULL, total_tool_def_token_count int4 DEFAULT 0 NULL, total_user_msg_token_count int4 DEFAULT 0 NULL, total_bot_response_token_count int4 DEFAULT 0 NULL, CONSTRAINT chat_sessions_archive_status_check CHECK (((archive_status)::text = ANY (ARRAY[('active'::character varying)::text, ('closed'::character varying)::text, ('archived'::character varying)::text, ('transferred'::character varying)::text]))), CONSTRAINT chat_sessions_feedback_type_check CHECK (((feedback_type)::text = ANY (ARRAY['positive'::text, 'negative'::text]))), CONSTRAINT chat_sessions_pkey PRIMARY KEY (id), CONSTRAINT chat_sessions_sentiment_check CHECK (((sentiment)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text, ('neutral'::character varying)::text]))), CONSTRAINT chat_sessions_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_active_recent ON public.chat_sessions USING btree (created_at DESC) WHERE ((is_active = true) AND ((archive_status)::text = 'active'::text));
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_activity ON public.chat_sessions USING btree (archive_status, last_activity_at DESC) INCLUDE (is_active, message_count) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_id_user ON public.chat_sessions USING btree (archive_status, id DESC, user_role_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_status_covering ON public.chat_sessions USING btree (archive_status) INCLUDE (updated_at, is_active, message_count, user_role_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_analysis ON public.chat_sessions USING btree (user_role_id, feedback_type, feedback_provided_at DESC) INCLUDE (feedback_type, created_at) WHERE (feedback_type IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active_id ON public.chat_sessions USING btree (is_active, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_metadata_model ON public.chat_sessions USING btree (((metadata ->> 'model'::text))) INCLUDE (created_at, user_role_id) WHERE ((metadata ->> 'model'::text) IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment_analysis ON public.chat_sessions USING btree (sentiment, created_at DESC) WHERE (sentiment IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment_id ON public.chat_sessions USING btree (sentiment, id DESC);

COMMENT ON COLUMN public.chat_sessions.duration_minutes IS 'Computed virtual column: session duration in minutes. Calculated on SELECT, never stored.';

CREATE OR REPLACE TRIGGER chat_sessions_updated_at_trigger before
update
    on
    public.chat_sessions for each row execute function update_updated_at_column();

ALTER TABLE public.chat_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.file_uploads ( id uuid DEFAULT uuidv7() NOT NULL, user_role_id uuid NULL, original_filename varchar(500) NOT NULL, display_name varchar(500) NULL, file_extension varchar(50) NULL, gemini_file_name varchar(500) NULL, gemini_file_uri text NULL, gemini_state varchar(50) DEFAULT 'pending'::character varying NULL, sha256_hash varchar(64) NULL, file_size int8 NULL, mime_type varchar(100) NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, "version" int4 DEFAULT 1 NULL, processed_by_extractor bool DEFAULT false NULL, extractor_processing_time_ms int4 NULL, extractor_images_extracted int4 DEFAULT 0 NULL, extractor_images_with_ocr int4 DEFAULT 0 NULL, processing_status varchar(20) DEFAULT 'pending'::character varying NULL, error_message text NULL, s3_key text NULL, processed_content_s3_key text NULL, celery_task_id varchar(255) NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, char_count int4 DEFAULT 0 NULL, gemini_processed_at timestamptz NULL, is_processing bool GENERATED ALWAYS AS (processing_status::text = ANY (ARRAY['pending'::character varying, 'processing'::character varying]::text[])) STORED NULL, file_category varchar(50) GENERATED ALWAYS AS (
CASE
    WHEN file_extension::text = ANY (ARRAY['pdf'::character varying, 'docx'::character varying, 'xlsx'::character varying, 'pptx'::character varying, 'txt'::character varying, 'doc'::character varying, 'xls'::character varying, 'odt'::character varying]::text[]) THEN 'document'::text
    WHEN file_extension::text = ANY (ARRAY['jpg'::character varying, 'png'::character varying, 'gif'::character varying, 'svg'::character varying, 'webp'::character varying, 'bmp'::character varying, 'tiff'::character varying]::text[]) THEN 'image'::text
    WHEN file_extension::text = ANY (ARRAY['mp4'::character varying, 'mov'::character varying, 'avi'::character varying, 'mkv'::character varying, 'webm'::character varying, 'flv'::character varying]::text[]) THEN 'video'::text
    WHEN file_extension::text = ANY (ARRAY['mp3'::character varying, 'wav'::character varying, 'm4a'::character varying, 'flac'::character varying, 'ogg'::character varying, 'aac'::character varying]::text[]) THEN 'audio'::text
    ELSE 'other'::text
END) STORED NULL, is_successful bool GENERATED ALWAYS AS (processing_status::text = 'completed'::text) STORED NULL, filestore_character_count int4 DEFAULT 0 NULL, filestore_word_count int4 DEFAULT 0 NULL, filestore_token_count int4 DEFAULT 0 NULL, total_tables_count int4 DEFAULT 0 NULL, total_table_rows_input int4 DEFAULT 0 NULL, total_table_chars_input int4 DEFAULT 0 NULL, total_table_chars_output int4 DEFAULT 0 NULL, total_table_input_tokens int4 DEFAULT 0 NULL, total_table_output_tokens int4 DEFAULT 0 NULL, total_pages int4 DEFAULT 0 NULL, CONSTRAINT file_uploads_pkey PRIMARY KEY (id), CONSTRAINT valid_processing_status CHECK (((processing_status)::text = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'failed'::text, 'cancelled'::text, 'deleted'::text]))), CONSTRAINT file_uploads_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_file_uploads_completed_lookup ON public.file_uploads USING btree (gemini_file_name) INCLUDE (display_name, processed_content_s3_key, file_size, file_category) WHERE ((processing_status)::text = 'completed'::text);
CREATE INDEX IF NOT EXISTS idx_file_uploads_extractor ON public.file_uploads USING btree (id DESC) WHERE (processed_by_extractor = true);
CREATE INDEX IF NOT EXISTS idx_file_uploads_extractor_perf ON public.file_uploads USING btree (extractor_processing_time_ms DESC) INCLUDE (extractor_images_extracted, extractor_images_with_ocr, processed_by_extractor) WHERE ((processed_by_extractor = true) AND (extractor_processing_time_ms > 0));
CREATE INDEX IF NOT EXISTS idx_file_uploads_failed ON public.file_uploads USING btree (created_at DESC) INCLUDE (error_message, processing_status, display_name) WHERE ((processing_status)::text = 'failed'::text);
CREATE INDEX IF NOT EXISTS idx_file_uploads_gemini_sync ON public.file_uploads USING btree (gemini_state, created_at DESC) INCLUDE (gemini_file_uri, s3_key, gemini_file_name) WHERE ((gemini_state)::text <> 'completed'::text);
CREATE INDEX IF NOT EXISTS idx_file_uploads_processed_content_s3_key ON public.file_uploads USING btree (processed_content_s3_key);
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_active ON public.file_uploads USING btree (processing_status, created_at DESC) INCLUDE (display_name, user_role_id, file_category) WHERE ((processing_status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying])::text[]));
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_key ON public.file_uploads USING btree (s3_key);
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_processed ON public.file_uploads USING btree (processed_content_s3_key) INCLUDE (display_name, created_at, char_count) WHERE (processed_content_s3_key IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_file_uploads_status_id ON public.file_uploads USING btree (processing_status, id DESC);
CREATE INDEX IF NOT EXISTS idx_file_uploads_user_files ON public.file_uploads USING btree (user_role_id, processing_status, created_at DESC) INCLUDE (display_name, file_size, file_category);
CREATE INDEX IF NOT EXISTS idx_file_uploads_user_status ON public.file_uploads USING btree (user_role_id, processing_status);

COMMENT ON COLUMN public.file_uploads.is_processing IS 'Computed virtual column: true if processing_status is pending or processing';

CREATE OR REPLACE TRIGGER file_uploads_updated_at_trigger before
update
    on
    public.file_uploads for each row execute function update_updated_at_column();

ALTER TABLE public.file_uploads OWNER TO postgres;
GRANT ALL ON TABLE public.file_uploads TO postgres;
GRANT ALL ON TABLE public.file_uploads TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.scraped_websites ( id uuid DEFAULT uuidv7() NOT NULL, user_role_id uuid NULL, original_url text NOT NULL, "domain" varchar(500) NULL, title varchar(500) NULL, description text NULL, pages_scraped int4 DEFAULT 0 NULL, file_size int4 DEFAULT 0 NULL, gemini_state varchar(50) DEFAULT 'pending'::character varying NULL, gemini_file_name varchar(500) NULL, gemini_file_uri text NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, "version" int4 DEFAULT 1 NULL, processing_status varchar(20) DEFAULT 'pending'::character varying NULL, error_message text NULL, celery_task_id varchar(255) NULL, "depth" int4 DEFAULT 0 NULL, parent_id uuid NULL, crawl_session_id int4 NULL, processed_content_s3_key text NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, char_count int4 DEFAULT 0 NULL, gemini_processed_at timestamptz NULL, is_root_page bool GENERATED ALWAYS AS (parent_id IS NULL) STORED NULL, url_domain varchar(500) GENERATED ALWAYS AS ("substring"(original_url, '://([^/?#]+)'::text)) STORED NULL, filestore_character_count int4 DEFAULT 0 NULL, filestore_word_count int4 DEFAULT 0 NULL, filestore_token_count int4 DEFAULT 0 NULL, total_tables_count int4 DEFAULT 0 NULL, total_table_rows_input int4 DEFAULT 0 NULL, total_table_chars_input int4 DEFAULT 0 NULL, total_table_chars_output int4 DEFAULT 0 NULL, total_table_input_tokens int4 DEFAULT 0 NULL, total_table_output_tokens int4 DEFAULT 0 NULL, CONSTRAINT scraped_websites_pkey PRIMARY KEY (id), CONSTRAINT scraped_websites_processing_status_check CHECK (((processing_status)::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text, ('deleted'::character varying)::text]))), CONSTRAINT scraped_websites_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.scraped_websites(id) ON DELETE CASCADE, CONSTRAINT scraped_websites_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain ON public.scraped_websites USING btree (domain);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain_content ON public.scraped_websites USING btree (domain) INCLUDE (title, pages_scraped, char_count) WHERE ((processing_status)::text = 'completed'::text);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain_processed ON public.scraped_websites USING btree (domain, processing_status, created_at DESC) INCLUDE (pages_scraped, file_size, url_domain);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_failed_analysis ON public.scraped_websites USING btree (created_at DESC) INCLUDE (error_message, celery_task_id, domain, processing_status) WHERE ((processing_status)::text = 'failed'::text);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_hierarchy ON public.scraped_websites USING btree (crawl_session_id, parent_id, depth);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_large_content ON public.scraped_websites USING btree (file_size DESC, created_at) WHERE (file_size > 1000000);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_metadata_retry ON public.scraped_websites USING btree (((metadata ->> 'retry_count'::text))) INCLUDE (domain, processing_status) WHERE (((metadata ->> 'retry_count'::text) IS NOT NULL) AND ((processing_status)::text = 'failed'::text));
CREATE INDEX IF NOT EXISTS idx_scraped_websites_metadata_source ON public.scraped_websites USING btree (((metadata ->> 'source_type'::text)), processing_status) INCLUDE (domain, created_at) WHERE ((metadata ->> 'source_type'::text) IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_parent_hierarchy ON public.scraped_websites USING btree (parent_id, created_at DESC) INCLUDE (processing_status, depth, pages_scraped, is_root_page) WHERE (parent_id IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processed_content_s3_key ON public.scraped_websites USING btree (processed_content_s3_key);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_active ON public.scraped_websites USING btree (processing_status, created_at DESC) INCLUDE (domain, pages_scraped, file_size, url_domain) WHERE ((processing_status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying])::text[]));
CREATE INDEX IF NOT EXISTS idx_scraped_websites_session_hierarchy ON public.scraped_websites USING btree (crawl_session_id, parent_id, created_at DESC) INCLUDE (processing_status, depth, pages_scraped);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_status_id ON public.scraped_websites USING btree (processing_status, id DESC);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_url_lookup ON public.scraped_websites USING btree (original_url, processing_status, created_at DESC) INCLUDE (title, domain, url_domain) WHERE ((processing_status)::text <> 'deleted'::text);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_user_role_id ON public.scraped_websites USING btree (user_role_id);

CREATE OR REPLACE TRIGGER scraped_websites_updated_at_trigger before
update
    on
    public.scraped_websites for each row execute function update_updated_at_column();

ALTER TABLE public.scraped_websites OWNER TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.session_assignments ( id uuid DEFAULT uuidv7() NOT NULL, session_id uuid NOT NULL, user_role_id uuid NOT NULL, status varchar(50) DEFAULT 'active'::character varying NULL, assigned_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, ended_at timestamptz NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT session_assignments_pkey PRIMARY KEY (id), CONSTRAINT session_assignments_status_check CHECK (((status)::text = ANY (ARRAY[('waiting'::character varying)::text, ('active'::character varying)::text, ('transferred'::character varying)::text, ('ended'::character varying)::text]))), CONSTRAINT session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE, CONSTRAINT session_assignments_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_session_assignments_active ON public.session_assignments USING btree (user_role_id, assigned_at DESC) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'waiting'::character varying])::text[]));
CREATE INDEX IF NOT EXISTS idx_session_assignments_agent_workload ON public.session_assignments USING btree (user_role_id, status, assigned_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_assignments_session ON public.session_assignments USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_covering ON public.session_assignments USING btree (status) INCLUDE (session_id, user_role_id, assigned_at);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_id ON public.session_assignments USING btree (status, id DESC);
CREATE INDEX IF NOT EXISTS idx_session_assignments_transferred ON public.session_assignments USING btree (user_role_id, assigned_at DESC) WHERE ((status)::text = 'transferred'::text);
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_status ON public.session_assignments USING btree (user_role_id, status);

CREATE OR REPLACE TRIGGER session_assignments_updated_at_trigger before
update
    on
    public.session_assignments for each row execute function update_updated_at_column();

ALTER TABLE public.session_assignments OWNER TO postgres;
GRANT ALL ON TABLE public.session_assignments TO postgres;
GRANT ALL ON TABLE public.session_assignments TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.tables_metadata ( id uuid DEFAULT uuidv7() NOT NULL, file_upload_id uuid NULL, scraped_website_id uuid NULL, table_index int4 DEFAULT 0 NULL, table_column_count_input int4 DEFAULT 0 NULL, table_row_count_input int4 DEFAULT 0 NULL, table_character_count_input int4 DEFAULT 0 NULL, table_word_count_input int4 DEFAULT 0 NULL, table_word_count_output int4 DEFAULT 0 NULL, table_character_count_output int4 DEFAULT 0 NULL, table_input_token_count int4 DEFAULT 0 NULL, table_output_token_count int4 DEFAULT 0 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT tables_metadata_has_parent CHECK (((file_upload_id IS NOT NULL) OR (scraped_website_id IS NOT NULL))), CONSTRAINT tables_metadata_pkey PRIMARY KEY (id), CONSTRAINT tables_metadata_file_upload_id_fkey FOREIGN KEY (file_upload_id) REFERENCES public.file_uploads(id) ON DELETE CASCADE, CONSTRAINT tables_metadata_scraped_website_id_fkey FOREIGN KEY (scraped_website_id) REFERENCES public.scraped_websites(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_tables_metadata_file_upload_id ON public.tables_metadata USING btree (file_upload_id);
CREATE INDEX IF NOT EXISTS idx_tables_metadata_reporting ON public.tables_metadata USING btree (created_at DESC, table_input_token_count, table_output_token_count);
CREATE INDEX IF NOT EXISTS idx_tables_metadata_scraped_website_id ON public.tables_metadata USING btree (scraped_website_id);

ALTER TABLE public.tables_metadata OWNER TO postgres;
GRANT ALL ON TABLE public.tables_metadata TO postgres;

CREATE TABLE IF NOT EXISTS public.agent_run_steps ( id uuid DEFAULT gen_random_uuid() NOT NULL, session_id uuid NOT NULL, user_message_id uuid NULL, step_number int4 NOT NULL, step_type varchar(30) NOT NULL, part_type varchar(30) NOT NULL, tool_name varchar(100) NULL, content_preview text DEFAULT ''::text NULL, char_count int4 DEFAULT 0 NULL, word_count int4 DEFAULT 0 NULL, token_count int4 DEFAULT 0 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT agent_run_steps_pkey PRIMARY KEY (id), CONSTRAINT agent_run_steps_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_session ON public.agent_run_steps USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_user_msg ON public.agent_run_steps USING btree (user_message_id);

ALTER TABLE public.agent_run_steps OWNER TO postgres;
GRANT ALL ON TABLE public.agent_run_steps TO postgres;

CREATE TABLE IF NOT EXISTS public.chat_messages ( id uuid DEFAULT uuidv7() NOT NULL, session_id uuid NOT NULL, "role" varchar(50) NOT NULL, "content" text NOT NULL, used_rag bool DEFAULT false NULL, used_postgres bool DEFAULT false NULL, confidence_score numeric(3, 2) NULL, sources jsonb DEFAULT '[]'::jsonb NULL, is_message_read bool DEFAULT false NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, character_count int4 DEFAULT 0 NULL, word_count int4 DEFAULT 0 NULL, token_count int4 DEFAULT 0 NULL, message_token_count int4 DEFAULT 0 NULL, prompt_token_count int4 DEFAULT 0 NULL, completion_token_count int4 DEFAULT 0 NULL, system_prompt_char_count int4 DEFAULT 0 NULL, system_prompt_word_count int4 DEFAULT 0 NULL, system_prompt_token_count int4 DEFAULT 0 NULL, history_char_count int4 DEFAULT 0 NULL, history_word_count int4 DEFAULT 0 NULL, history_token_count int4 DEFAULT 0 NULL, tool_def_char_count int4 DEFAULT 0 NULL, tool_def_word_count int4 DEFAULT 0 NULL, tool_def_token_count int4 DEFAULT 0 NULL, user_msg_char_count int4 DEFAULT 0 NULL, user_msg_word_count int4 DEFAULT 0 NULL, user_msg_token_count int4 DEFAULT 0 NULL, bot_response_char_count int4 DEFAULT 0 NULL, bot_response_word_count int4 DEFAULT 0 NULL, bot_response_token_count int4 DEFAULT 0 NULL, system_prompt_text text DEFAULT ''::text NULL, history_text text DEFAULT ''::text NULL, tool_def_text text DEFAULT ''::text NULL, CONSTRAINT chat_messages_pkey PRIMARY KEY (id), CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_fts ON public.chat_messages USING gin (to_tsvector('english'::regconfig, content));
CREATE INDEX IF NOT EXISTS idx_chat_messages_low_confidence ON public.chat_messages USING btree (session_id, confidence_score) WHERE ((confidence_score < 0.75) AND (used_rag = true));
CREATE INDEX IF NOT EXISTS idx_chat_messages_rag_analysis ON public.chat_messages USING btree (session_id, used_rag, created_at DESC) INCLUDE (confidence_score);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_id ON public.chat_messages USING btree (role, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_session ON public.chat_messages USING btree (role, created_at DESC) INCLUDE (session_id, used_rag);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON public.chat_messages USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_ordered ON public.chat_messages USING btree (session_id, created_at DESC) INCLUDE (role, used_rag, confidence_score);
CREATE INDEX IF NOT EXISTS idx_chat_messages_unread_covering ON public.chat_messages USING btree (session_id, is_message_read) INCLUDE (role, created_at, content) WHERE (is_message_read = false);

CREATE OR REPLACE TRIGGER chat_messages_updated_at_trigger before
update
    on
    public.chat_messages for each row execute function update_updated_at_column();

ALTER TABLE public.chat_messages OWNER TO postgres;
GRANT ALL ON TABLE public.chat_messages TO postgres;
GRANT ALL ON TABLE public.chat_messages TO pg_database_owner;

CREATE TABLE IF NOT EXISTS public.token_usage_log ( id uuid DEFAULT uuidv7() NOT NULL, session_id uuid NULL, message_id uuid NULL, provider varchar(50) NOT NULL, model varchar(100) NULL, prompt_tokens int4 DEFAULT 0 NULL, completion_tokens int4 DEFAULT 0 NULL, total_tokens int4 DEFAULT 0 NULL, cost_cents int4 DEFAULT 0 NULL, api_call_type varchar(50) NULL, request_metadata jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, model_provider_key varchar(200) GENERATED ALWAYS AS ((((provider::text || ':'::text) || COALESCE(model, 'unknown'::character varying)::text))) STORED NULL, calculated_cost_cents int4 GENERATED ALWAYS AS (round(prompt_tokens::numeric * 0.00001 + completion_tokens::numeric * 0.00004)::integer) STORED NULL, CONSTRAINT token_usage_log_pkey PRIMARY KEY (id), CONSTRAINT token_usage_log_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE, CONSTRAINT token_usage_log_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_message_id ON public.token_usage_log USING btree (message_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider_created ON public.token_usage_log USING btree (provider, created_at DESC);
COMMENT ON INDEX public.idx_token_usage_log_provider_created IS 'B-tree compound index enabling skip scans. Use for time-range analytics queries that skip provider binding.';
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider_id ON public.token_usage_log USING btree (provider, id DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_reporting ON public.token_usage_log USING btree (created_at DESC, prompt_tokens, completion_tokens) INCLUDE (cost_cents, api_call_type);
CREATE INDEX IF NOT EXISTS idx_token_usage_message_tracking ON public.token_usage_log USING btree (message_id, created_at DESC) INCLUDE (provider, total_tokens, cost_cents, api_call_type) WHERE (message_id IS NOT NULL);

CREATE OR REPLACE TRIGGER token_usage_log_updated_at_trigger before
update
    on
    public.token_usage_log for each row execute function update_updated_at_column();

ALTER TABLE public.token_usage_log OWNER TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO pg_database_owner;

CREATE OR REPLACE VIEW public.admin_actions_analytics
AS SELECT action_category,
    count(*) AS total_actions,
    count(*) FILTER (WHERE success = true) AS successful_actions,
    count(*) FILTER (WHERE success = false) AS failed_actions,
    round(100.0 * count(*) FILTER (WHERE success = true)::numeric / count(*)::numeric, 2) AS success_rate_percent,
    round(avg(duration_ms), 2) AS avg_duration_ms,
    max(duration_ms) AS max_duration_ms,
    min(duration_ms) AS min_duration_ms
   FROM admin_actions
  GROUP BY action_category
  ORDER BY (count(*)) DESC;

ALTER TABLE public.admin_actions_analytics OWNER TO postgres;
GRANT ALL ON TABLE public.admin_actions_analytics TO postgres;

CREATE OR REPLACE VIEW public.admin_sessions_analytics
AS SELECT date(login_at) AS login_date,
    count(*) AS total_sessions,
    count(DISTINCT email) AS unique_users,
    count(*) FILTER (WHERE is_active = true) AS active_sessions,
    avg(EXTRACT(epoch FROM COALESCE(logout_at, CURRENT_TIMESTAMP) - login_at)) AS avg_duration_seconds,
    max(EXTRACT(epoch FROM COALESCE(logout_at, CURRENT_TIMESTAMP) - login_at)) AS max_duration_seconds
   FROM admin_sessions
  GROUP BY (date(login_at))
  ORDER BY (date(login_at)) DESC;

ALTER TABLE public.admin_sessions_analytics OWNER TO postgres;
GRANT ALL ON TABLE public.admin_sessions_analytics TO postgres;

CREATE OR REPLACE VIEW public.v_pg18_skip_scan_candidates
AS SELECT schemaname,
    relname AS tablename,
    indexrelname AS indexname,
    idx_scan,
        CASE
            WHEN idx_scan > 0 THEN 'ACTIVE'::text
            ELSE 'UNUSED'::text
        END AS status
   FROM pg_stat_user_indexes
  WHERE indexrelname ~~ '%_id'::text OR indexrelname ~~ '%_status%'::text
  ORDER BY idx_scan DESC;

ALTER TABLE public.v_pg18_skip_scan_candidates OWNER TO postgres;
GRANT ALL ON TABLE public.v_pg18_skip_scan_candidates TO postgres;

CREATE OR REPLACE VIEW public.v_pg18_uuid_primary_keys
AS SELECT n.nspname AS schemaname,
    c.relname AS tablename,
    a.attname AS column_name,
    t.typname AS column_type,
        CASE
            WHEN t.typname = 'uuid'::name THEN 'UUID v7 (PG18)'::name
            WHEN t.typname = 'int4'::name THEN 'SERIAL4 (Legacy)'::name
            ELSE t.typname
        END AS key_type
   FROM pg_class c
     JOIN pg_namespace n ON c.relnamespace = n.oid
     JOIN pg_index i ON c.oid = i.indrelid
     JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
     JOIN pg_type t ON a.atttypid = t.oid
  WHERE n.nspname = 'public'::name AND i.indisprimary
  ORDER BY n.nspname, c.relname;

ALTER TABLE public.v_pg18_uuid_primary_keys OWNER TO postgres;
GRANT ALL ON TABLE public.v_pg18_uuid_primary_keys TO postgres;

CREATE OR REPLACE VIEW public.v_pg18_virtual_columns
AS SELECT table_schema,
    table_name,
    column_name,
    data_type,
    'VIRTUAL'::text AS column_type
   FROM information_schema.columns
  WHERE table_schema::name = 'public'::name AND generation_expression IS NOT NULL;

ALTER TABLE public.v_pg18_virtual_columns OWNER TO postgres;
GRANT ALL ON TABLE public.v_pg18_virtual_columns TO postgres;

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
$function$
;

ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO public;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO postgres;

GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;
GRANT USAGE ON SCHEMA public TO postgres;

CREATE TABLE IF NOT EXISTS public.document_chunks (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id uuid NOT NULL,
    document_type varchar(20) NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    embedding halfvec(768),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT document_chunks_type_check CHECK (document_type IN ('file', 'website'))
);

DO $$ 
BEGIN 
    -- 1. Check if we need to migrate from vector to halfvec
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'document_chunks' AND column_name = 'embedding'
        AND data_type = 'USER-DEFINED' -- vector is usually user-defined
    ) THEN
        BEGIN
            -- 2. Drop legacy index first to avoid "operator class" errors during type change
            DROP INDEX IF EXISTS public.idx_document_chunks_embedding;
            
            -- 3. Perform type migration
            ALTER TABLE public.document_chunks ALTER COLUMN embedding TYPE halfvec(768);
            
            RAISE NOTICE '✅ Successfully migrated document_chunks.embedding to halfvec(768)';
        EXCEPTION WHEN OTHERS THEN
            -- If it's already a halfvec, postgres might still error on 'vector_cosine_ops' mismatch
            RAISE NOTICE 'Skipping halfvec migration: %', SQLERRM;
        END;
    END IF;
END $$;

-- 4. Recreate index using correct halfvec operator class
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
ON public.document_chunks USING hnsw (embedding halfvec_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_document_chunks_content_fts 
ON public.document_chunks USING GIN (to_tsvector('english', content));

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON public.document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_type ON public.document_chunks(document_type);

ALTER TABLE public.document_chunks OWNER TO postgres;
GRANT ALL ON TABLE public.document_chunks TO postgres;
GRANT ALL ON TABLE public.document_chunks TO pg_database_owner;
