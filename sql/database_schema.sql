-- DROP SCHEMA public;

CREATE SCHEMA IF NOT EXISTS public AUTHORIZATION pg_database_owner;

COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form';

-- DROP SEQUENCE public.api_usage_id_seq;

CREATE SEQUENCE public.api_usage_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.api_usage_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.chat_feedback_id_seq;

CREATE SEQUENCE public.chat_feedback_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.chat_feedback_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.chat_messages_id_seq;

CREATE SEQUENCE public.chat_messages_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.chat_messages_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.chat_sessions_id_seq;

CREATE SEQUENCE public.chat_sessions_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.chat_sessions_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.file_uploads_id_seq;

CREATE SEQUENCE public.file_uploads_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.file_uploads_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.llm_providers_id_seq;

CREATE SEQUENCE public.llm_providers_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.llm_providers_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.metrics_id_seq;

CREATE SEQUENCE public.metrics_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.metrics_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.metrics_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.metrics_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.notification_settings_id_seq;

CREATE SEQUENCE public.notification_settings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.notification_settings_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.notification_settings_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.notification_settings_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.notifications_id_seq;

CREATE SEQUENCE public.notifications_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.notifications_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.notifications_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.notifications_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.persona_configurations_id_seq;

CREATE SEQUENCE public.persona_configurations_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.persona_configurations_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.persona_configurations_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.persona_configurations_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.scraped_websites_id_seq;

CREATE SEQUENCE public.scraped_websites_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.scraped_websites_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.scraped_websites_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.scraped_websites_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.security_settings_id_seq;

CREATE SEQUENCE public.security_settings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.security_settings_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.security_settings_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.security_settings_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.session_assignments_id_seq;

CREATE SEQUENCE public.session_assignments_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.session_assignments_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.session_assignments_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.session_assignments_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.token_usage_log_id_seq;

CREATE SEQUENCE public.token_usage_log_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.token_usage_log_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.token_usage_log_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.token_usage_log_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.users_id_seq;

CREATE SEQUENCE public.users_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.users_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.widget_configuration_id_seq;

CREATE SEQUENCE public.widget_configuration_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.widget_configuration_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.widget_scripts_id_seq;

CREATE SEQUENCE public.widget_scripts_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.widget_scripts_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_scripts_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_scripts_id_seq TO pg_database_owner;

-- DROP SEQUENCE public.widget_suggested_messages_id_seq;

CREATE SEQUENCE public.widget_suggested_messages_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.widget_suggested_messages_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_suggested_messages_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_suggested_messages_id_seq TO pg_database_owner;

-- public.api_usage definition

-- Drop table

-- DROP TABLE public.api_usage;

CREATE TABLE public.api_usage ( id serial4 NOT NULL, api_provider varchar(100) NOT NULL, api_endpoint varchar(255) NULL, http_method varchar(10) NULL, request_size_bytes int4 DEFAULT 0 NULL, response_size_bytes int4 DEFAULT 0 NULL, tokens_input int4 DEFAULT 0 NULL, tokens_output int4 DEFAULT 0 NULL, user_email varchar(255) NULL, request_metadata jsonb DEFAULT '{}'::jsonb NULL, last_used_at timestamptz NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT api_usage_pkey PRIMARY KEY (id));
CREATE INDEX idx_api_usage_created_at ON public.api_usage USING btree (created_at DESC);
CREATE INDEX idx_api_usage_endpoint ON public.api_usage USING btree (api_endpoint);
CREATE INDEX idx_api_usage_provider ON public.api_usage USING btree (api_provider);
CREATE INDEX idx_api_usage_user_email ON public.api_usage USING btree (user_email);
COMMENT ON TABLE public.api_usage IS 'API usage tracking and metrics';

-- Permissions

ALTER TABLE public.api_usage OWNER TO postgres;
GRANT ALL ON TABLE public.api_usage TO postgres;
GRANT ALL ON TABLE public.api_usage TO pg_database_owner;


-- public.chat_feedback definition

-- Drop table

-- DROP TABLE public.chat_feedback;

CREATE TABLE public.chat_feedback ( id serial4 NOT NULL, message_id varchar(255) NOT NULL, session_id varchar(255) NOT NULL, feedback_type varchar(20) NOT NULL, user_type varchar(20) DEFAULT 'customer'::character varying NULL, created_at timestamp DEFAULT now() NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT chat_feedback_pkey PRIMARY KEY (id), CONSTRAINT valid_feedback_type CHECK (((feedback_type)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text]))), CONSTRAINT valid_user_type CHECK (((user_type)::text = ANY (ARRAY[('customer'::character varying)::text, ('agent'::character varying)::text]))));
CREATE INDEX idx_chat_feedback_created_at ON public.chat_feedback USING btree (created_at DESC);
CREATE INDEX idx_chat_feedback_session ON public.chat_feedback USING btree (session_id);
CREATE INDEX idx_chat_feedback_type ON public.chat_feedback USING btree (feedback_type);
CREATE INDEX idx_chat_feedback_user_type ON public.chat_feedback USING btree (user_type);
COMMENT ON TABLE public.chat_feedback IS 'User feedback on chat messages';

-- Permissions

ALTER TABLE public.chat_feedback OWNER TO postgres;
GRANT ALL ON TABLE public.chat_feedback TO postgres;
GRANT ALL ON TABLE public.chat_feedback TO pg_database_owner;


-- public.llm_providers definition

-- Drop table

-- DROP TABLE public.llm_providers;

CREATE TABLE public.llm_providers ( id serial4 NOT NULL, provider_name varchar(100) NOT NULL, token_limit int8 DEFAULT 0 NULL, token_used int8 DEFAULT 0 NULL, is_active bool DEFAULT true NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT llm_providers_pkey PRIMARY KEY (id), CONSTRAINT llm_providers_provider_name_key UNIQUE (provider_name));
CREATE INDEX idx_llm_providers_is_active ON public.llm_providers USING btree (is_active);
CREATE INDEX idx_llm_providers_provider_name ON public.llm_providers USING btree (provider_name);
COMMENT ON TABLE public.llm_providers IS 'LLM provider token limits and usage tracking';

-- Permissions

ALTER TABLE public.llm_providers OWNER TO postgres;
GRANT ALL ON TABLE public.llm_providers TO postgres;
GRANT ALL ON TABLE public.llm_providers TO pg_database_owner;


-- public.metrics definition

-- Drop table

-- DROP TABLE public.metrics;

CREATE TABLE public.metrics ( id serial4 NOT NULL, metric_type varchar(100) NOT NULL, metric_name varchar(255) NOT NULL, value numeric(20, 4) NULL, unit varchar(50) NULL, tags jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT metrics_pkey PRIMARY KEY (id), CONSTRAINT metrics_type_name_unique UNIQUE (metric_type, metric_name));
CREATE INDEX idx_metrics_created_at ON public.metrics USING btree (created_at DESC);
CREATE INDEX idx_metrics_name ON public.metrics USING btree (metric_name);
CREATE INDEX idx_metrics_type ON public.metrics USING btree (metric_type);
COMMENT ON TABLE public.metrics IS 'System metrics and performance data';

-- Permissions

ALTER TABLE public.metrics OWNER TO postgres;
GRANT ALL ON TABLE public.metrics TO postgres;
GRANT ALL ON TABLE public.metrics TO pg_database_owner;


-- public.notifications definition

-- Drop table

-- DROP TABLE public.notifications;

CREATE TABLE public.notifications ( id serial4 NOT NULL, user_email varchar(255) NOT NULL, title varchar(500) NOT NULL, message text NOT NULL, "type" varchar(20) DEFAULT 'info'::character varying NULL, is_read bool DEFAULT false NULL, read_at timestamptz NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT notifications_pkey PRIMARY KEY (id), CONSTRAINT valid_notification_type CHECK (((type)::text = ANY (ARRAY[('info'::character varying)::text, ('success'::character varying)::text, ('warning'::character varying)::text, ('error'::character varying)::text]))));
CREATE INDEX idx_notifications_created_at ON public.notifications USING btree (created_at DESC);
CREATE INDEX idx_notifications_is_read ON public.notifications USING btree (is_read);
CREATE INDEX idx_notifications_user_email ON public.notifications USING btree (user_email);
CREATE INDEX idx_notifications_user_read ON public.notifications USING btree (user_email, is_read);
COMMENT ON TABLE public.notifications IS 'User notifications';

-- Permissions

ALTER TABLE public.notifications OWNER TO postgres;
GRANT ALL ON TABLE public.notifications TO postgres;
GRANT ALL ON TABLE public.notifications TO pg_database_owner;


-- public.persona_configurations definition

-- Drop table

-- DROP TABLE public.persona_configurations;

CREATE TABLE public.persona_configurations ( id serial4 NOT NULL, persona_name varchar(100) NOT NULL, system_prompt text NOT NULL, is_active bool DEFAULT false NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT persona_configurations_persona_name_key UNIQUE (persona_name), CONSTRAINT persona_configurations_pkey PRIMARY KEY (id));
CREATE INDEX idx_persona_configurations_is_active ON public.persona_configurations USING btree (is_active);
CREATE INDEX idx_persona_configurations_persona_name ON public.persona_configurations USING btree (persona_name);
COMMENT ON TABLE public.persona_configurations IS 'Chatbot persona configurations';

-- Permissions

ALTER TABLE public.persona_configurations OWNER TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO pg_database_owner;


-- public.security_settings definition

-- Drop table

-- DROP TABLE public.security_settings;

CREATE TABLE public.security_settings ( id serial4 NOT NULL, setting_name varchar(100) NOT NULL, setting_value text NULL, setting_type varchar(50) DEFAULT 'string'::character varying NULL, description text NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT security_settings_pkey PRIMARY KEY (id), CONSTRAINT security_settings_setting_name_key UNIQUE (setting_name), CONSTRAINT valid_setting_type CHECK (((setting_type)::text = ANY (ARRAY[('string'::character varying)::text, ('integer'::character varying)::text, ('boolean'::character varying)::text, ('json'::character varying)::text]))));
CREATE INDEX idx_security_settings_setting_name ON public.security_settings USING btree (setting_name);
COMMENT ON TABLE public.security_settings IS 'Security and configuration settings';

-- Permissions

ALTER TABLE public.security_settings OWNER TO postgres;
GRANT ALL ON TABLE public.security_settings TO postgres;
GRANT ALL ON TABLE public.security_settings TO pg_database_owner;


-- public.users definition

-- Drop table

-- DROP TABLE public.users;

CREATE TABLE public.users ( id serial4 NOT NULL, email varchar(255) NOT NULL, display_name varchar(255) NULL, email_verified bool DEFAULT false NULL, photo_url text NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, last_login_at timestamptz NULL, CONSTRAINT users_email_key UNIQUE (email), CONSTRAINT users_pkey PRIMARY KEY (id), CONSTRAINT valid_user_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text)));
CREATE INDEX idx_users_created_at ON public.users USING btree (created_at DESC);
CREATE INDEX idx_users_email ON public.users USING btree (email);
COMMENT ON TABLE public.users IS 'User accounts from Firebase Auth';

-- Permissions

ALTER TABLE public.users OWNER TO postgres;
GRANT ALL ON TABLE public.users TO postgres;
GRANT ALL ON TABLE public.users TO pg_database_owner;


-- public.roles definition

-- Drop table

-- DROP TABLE public.roles;

CREATE TABLE public.roles ( id serial4 NOT NULL, role_name varchar(50) NOT NULL, role_description text NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT roles_pkey PRIMARY KEY (id), CONSTRAINT roles_role_name_key UNIQUE (role_name));
CREATE INDEX idx_roles_role_name ON public.roles USING btree (role_name);
COMMENT ON TABLE public.roles IS 'User roles definition';

-- Permissions

ALTER TABLE public.roles OWNER TO postgres;
GRANT ALL ON TABLE public.roles TO postgres;
GRANT ALL ON TABLE public.roles TO pg_database_owner;


-- public.user_role_mapping definition

-- Drop table

-- DROP TABLE public.user_role_mapping;

CREATE TABLE public.user_role_mapping ( user_role_id serial4 NOT NULL, user_id int4 NOT NULL, role_id int4 NOT NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT user_role_mapping_pkey PRIMARY KEY (user_role_id), CONSTRAINT user_role_mapping_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE, CONSTRAINT user_role_mapping_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE, CONSTRAINT user_role_mapping_user_role_key UNIQUE (user_id, role_id));
CREATE INDEX idx_user_role_mapping_role_id ON public.user_role_mapping USING btree (role_id);
CREATE INDEX idx_user_role_mapping_user_id ON public.user_role_mapping USING btree (user_id);
COMMENT ON TABLE public.user_role_mapping IS 'Mapping between users and their roles';

-- Permissions

ALTER TABLE public.user_role_mapping OWNER TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO pg_database_owner;


-- Insert initial data

-- Insert users
INSERT INTO public.users (id, email, display_name, email_verified, created_at, updated_at) VALUES 
(1, 'globistaan@gmail.com', 'Globistaan Admin', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
(2, 'v.pramanick@gmail.com', 'Vijay Pramanick', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

-- Insert roles
INSERT INTO public.roles (id, role_name, role_description, created_at, updated_at) VALUES 
(1, 'admin', 'System administrator with full access', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
(2, 'human_agent', 'Human agent for customer support', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

-- Insert user role mappings
INSERT INTO public.user_role_mapping (user_id, role_id, created_at, updated_at) VALUES 
(1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
(1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
(2, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (user_id, role_id) DO NOTHING;


-- public.widget_configuration definition

-- Drop table

-- DROP TABLE public.widget_configuration;

CREATE TABLE public.widget_configuration ( id serial4 NOT NULL, display_name varchar(255) DEFAULT 'GLOBISTAAN'::character varying NULL, initial_message text DEFAULT 'Hi! What can I help you with?'::text NULL, auto_show_duration int4 DEFAULT 30 NULL, keep_showing_suggested bool DEFAULT false NULL, theme varchar(50) DEFAULT 'light'::character varying NULL, primary_color varchar(7) DEFAULT '#007bff'::character varying NULL, use_primary_for_header bool DEFAULT true NULL, chat_bubble_color varchar(7) DEFAULT '#f8f9fa'::character varying NULL, align_bubble varchar(10) DEFAULT 'right'::character varying NULL, display_chatbot bool DEFAULT true NULL, profile_picture_url text NULL, chat_icon_url text NULL, profile_picture_filename varchar(255) NULL, chat_icon_filename varchar(255) NULL, profile_zoom numeric(3, 2) DEFAULT 1.00 NULL, chat_icon_zoom numeric(3, 2) DEFAULT 1.00 NULL, profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL, chat_icon_position jsonb DEFAULT '{"x": 20, "y": 20}'::jsonb NULL, hil_enabled bool DEFAULT true NULL, response_policy int4 DEFAULT 30 NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, hil_disabled_message text DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.'::text NULL, CONSTRAINT single_row CHECK ((id = 1)), CONSTRAINT widget_configuration_pkey PRIMARY KEY (id));
CREATE INDEX idx_widget_configuration_display_chatbot ON public.widget_configuration USING btree (display_chatbot);
CREATE INDEX idx_widget_configuration_theme ON public.widget_configuration USING btree (theme);
COMMENT ON TABLE public.widget_configuration IS 'Widget appearance and behavior settings';

-- Permissions

ALTER TABLE public.widget_configuration OWNER TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO pg_database_owner;


-- public.widget_scripts definition

-- Drop table

-- DROP TABLE public.widget_scripts;

CREATE TABLE public.widget_scripts ( id serial4 NOT NULL, config_id varchar(255) NULL, script_content text NOT NULL, "version" int4 DEFAULT 1 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT widget_scripts_pkey PRIMARY KEY (id));
CREATE INDEX idx_widget_scripts_config_id ON public.widget_scripts USING btree (config_id);
CREATE INDEX idx_widget_scripts_version ON public.widget_scripts USING btree (version);
COMMENT ON TABLE public.widget_scripts IS 'Widget installation scripts and tracking';

-- Permissions

ALTER TABLE public.widget_scripts OWNER TO postgres;
GRANT ALL ON TABLE public.widget_scripts TO postgres;
GRANT ALL ON TABLE public.widget_scripts TO pg_database_owner;


-- public.chat_sessions definition

-- Drop table

-- DROP TABLE public.chat_sessions;

CREATE TABLE public.chat_sessions ( id serial4 NOT NULL, session_id varchar(255) NOT NULL, user_role_id int4 NULL, started_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, last_activity_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, ended_at timestamptz NULL, is_active bool DEFAULT true NULL, message_count int4 DEFAULT 0 NULL, sentiment varchar(20) NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, archive_status varchar(20) DEFAULT 'active'::character varying NULL, conversation_summary text NULL, file_search_store_id varchar(255) NULL, cached_content_id varchar(255) NULL, CONSTRAINT chat_sessions_archive_status_check CHECK (((archive_status)::text = ANY (ARRAY[('active'::character varying)::text, ('closed'::character varying)::text, ('archived'::character varying)::text, ('transferred'::character varying)::text]))), CONSTRAINT chat_sessions_pkey PRIMARY KEY (id), CONSTRAINT chat_sessions_session_id_key UNIQUE (session_id), CONSTRAINT valid_sentiment CHECK (((sentiment)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text, ('neutral'::character varying)::text]))), CONSTRAINT chat_sessions_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX idx_chat_sessions_archive_status ON public.chat_sessions USING btree (archive_status);
CREATE INDEX idx_chat_sessions_archive_status_updated ON public.chat_sessions USING btree (archive_status, updated_at DESC);
CREATE INDEX idx_chat_sessions_cached_content_id ON public.chat_sessions USING btree (cached_content_id);
CREATE INDEX idx_chat_sessions_conversation_summary ON public.chat_sessions USING gin (to_tsvector('english'::regconfig, conversation_summary));
CREATE INDEX idx_chat_sessions_file_search_store_id ON public.chat_sessions USING btree (file_search_store_id);
CREATE INDEX idx_chat_sessions_is_active ON public.chat_sessions USING btree (is_active);
CREATE INDEX idx_chat_sessions_last_activity ON public.chat_sessions USING btree (last_activity_at DESC);
CREATE INDEX idx_chat_sessions_sentiment ON public.chat_sessions USING btree (sentiment);
CREATE INDEX idx_chat_sessions_session_id ON public.chat_sessions USING btree (session_id);
CREATE INDEX idx_chat_sessions_user_role_id ON public.chat_sessions USING btree (user_role_id);
COMMENT ON TABLE public.chat_sessions IS 'Chat session tracking';

-- Column comments

COMMENT ON COLUMN public.chat_sessions.sentiment IS 'Overall sentiment analyzed by LLM';
COMMENT ON COLUMN public.chat_sessions.archive_status IS 'Session status: active (ongoing), closed (finished), archived (manually archived), transferred (moved to another agent)';
COMMENT ON COLUMN public.chat_sessions.conversation_summary IS 'AI-generated summary of the conversation, created when session ends';
COMMENT ON COLUMN public.chat_sessions.file_search_store_id IS 'Gemini FileSearchStore ID for RAG optimization';
COMMENT ON COLUMN public.chat_sessions.cached_content_id IS 'Gemini cached content ID for 90% cost discount';

-- Permissions

ALTER TABLE public.chat_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO pg_database_owner;


-- public.file_uploads definition

-- Drop table

-- DROP TABLE public.file_uploads;

CREATE TABLE public.file_uploads ( id serial4 NOT NULL, user_role_id int4 NULL, original_filename varchar(500) NOT NULL, display_name varchar(500) NULL, file_extension varchar(50) NULL, gemini_file_name varchar(500) NULL, gemini_file_uri text NULL, gemini_state varchar(50) DEFAULT 'pending'::character varying NULL, sha256_hash varchar(64) NULL, file_size int8 NULL, mime_type varchar(100) NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, "version" int4 DEFAULT 1 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT file_uploads_pkey PRIMARY KEY (id), CONSTRAINT file_uploads_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX idx_file_uploads_created_at ON public.file_uploads USING btree (created_at DESC);
CREATE INDEX idx_file_uploads_gemini_file_name ON public.file_uploads USING btree (gemini_file_name);
CREATE INDEX idx_file_uploads_gemini_state ON public.file_uploads USING btree (gemini_state);
CREATE INDEX idx_file_uploads_user_role_id ON public.file_uploads USING btree (user_role_id);
COMMENT ON TABLE public.file_uploads IS 'Uploaded files with Gemini FileSearch integration';

-- Permissions

ALTER TABLE public.file_uploads OWNER TO postgres;
GRANT ALL ON TABLE public.file_uploads TO postgres;
GRANT ALL ON TABLE public.file_uploads TO pg_database_owner;


-- public.scraped_websites definition

-- Drop table

-- DROP TABLE public.scraped_websites;

CREATE TABLE public.scraped_websites ( id serial4 NOT NULL, user_role_id int4 NULL, original_url text NOT NULL, "domain" varchar(500) NULL, title varchar(500) NULL, description text NULL, pages_scraped int4 DEFAULT 0 NULL, content_length int4 DEFAULT 0 NULL, gemini_state varchar(50) DEFAULT 'pending'::character varying NULL, gemini_file_name varchar(500) NULL, gemini_file_uri text NULL, metadata jsonb DEFAULT '{}'::jsonb NULL, "version" int4 DEFAULT 1 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT scraped_websites_pkey PRIMARY KEY (id), CONSTRAINT scraped_websites_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL);
CREATE INDEX idx_scraped_websites_domain ON public.scraped_websites USING btree (domain);
CREATE INDEX idx_scraped_websites_gemini_state ON public.scraped_websites USING btree (gemini_state);
CREATE INDEX idx_scraped_websites_original_url ON public.scraped_websites USING btree (original_url);
CREATE INDEX idx_scraped_websites_user_role_id ON public.scraped_websites USING btree (user_role_id);
COMMENT ON TABLE public.scraped_websites IS 'Scraped website content for knowledge base';

-- Permissions

ALTER TABLE public.scraped_websites OWNER TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO pg_database_owner;


-- public.session_assignments definition

-- Drop table

-- DROP TABLE public.session_assignments;

CREATE TABLE public.session_assignments ( id serial4 NOT NULL, session_id int4 NOT NULL, assignee_email varchar(255) NOT NULL, assignee_type varchar(20) NOT NULL, status varchar(50) DEFAULT 'active'::character varying NULL, assigned_at timestamp DEFAULT now() NULL, ended_at timestamp NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT session_assignments_pkey PRIMARY KEY (id), CONSTRAINT valid_assignee_type CHECK (((assignee_type)::text = ANY (ARRAY[('agent'::character varying)::text, ('admin'::character varying)::text]))), CONSTRAINT valid_assignment_status CHECK (((status)::text = ANY (ARRAY[('waiting'::character varying)::text, ('active'::character varying)::text, ('transferred'::character varying)::text, ('ended'::character varying)::text]))), CONSTRAINT session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX idx_session_assignments_assigned_at ON public.session_assignments USING btree (assigned_at DESC);
CREATE INDEX idx_session_assignments_assignee ON public.session_assignments USING btree (assignee_email);
CREATE INDEX idx_session_assignments_session ON public.session_assignments USING btree (session_id);
CREATE INDEX idx_session_assignments_status ON public.session_assignments USING btree (status);
CREATE INDEX idx_session_assignments_type ON public.session_assignments USING btree (assignee_type);
COMMENT ON TABLE public.session_assignments IS 'Tracks which agent/admin is assigned to each session';

-- Permissions

ALTER TABLE public.session_assignments OWNER TO postgres;
GRANT ALL ON TABLE public.session_assignments TO postgres;
GRANT ALL ON TABLE public.session_assignments TO pg_database_owner;


-- public.widget_suggested_messages definition

-- Drop table

-- DROP TABLE public.widget_suggested_messages;

CREATE TABLE public.widget_suggested_messages ( id serial4 NOT NULL, widget_config_id int4 NOT NULL, message_text text NOT NULL, display_order int4 DEFAULT 0 NULL, is_active bool DEFAULT true NULL, created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT widget_suggested_messages_pkey PRIMARY KEY (id), CONSTRAINT widget_suggested_messages_widget_config_id_fkey FOREIGN KEY (widget_config_id) REFERENCES public.widget_configuration(id) ON DELETE CASCADE);
CREATE INDEX idx_widget_suggested_messages_config_id ON public.widget_suggested_messages USING btree (widget_config_id);
CREATE INDEX idx_widget_suggested_messages_display_order ON public.widget_suggested_messages USING btree (display_order);
CREATE INDEX idx_widget_suggested_messages_is_active ON public.widget_suggested_messages USING btree (is_active);
COMMENT ON TABLE public.widget_suggested_messages IS 'Predefined messages that users can click to start conversations';

-- Permissions

ALTER TABLE public.widget_suggested_messages OWNER TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO pg_database_owner;


-- public.chat_messages definition

-- Drop table

-- DROP TABLE public.chat_messages;

CREATE TABLE public.chat_messages ( id serial4 NOT NULL, session_id int4 NOT NULL, "role" varchar(50) NOT NULL, "content" text NOT NULL, used_rag bool DEFAULT false NULL, used_postgres bool DEFAULT false NULL, used_neon_db bool DEFAULT false NULL, used_internet_search bool DEFAULT false NULL, confidence_score numeric(3, 2) NULL, sources jsonb DEFAULT '[]'::jsonb NULL, usage_info jsonb DEFAULT '{}'::jsonb NULL, rating int2 NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT chat_messages_pkey PRIMARY KEY (id), CONSTRAINT chat_messages_rating_check CHECK (((rating >= 1) AND (rating <= 5))), CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX idx_chat_messages_created_at ON public.chat_messages USING btree (created_at DESC);
CREATE INDEX idx_chat_messages_rating ON public.chat_messages USING btree (rating);
CREATE INDEX idx_chat_messages_role ON public.chat_messages USING btree (role);
CREATE INDEX idx_chat_messages_role_created_at ON public.chat_messages USING btree (role, created_at DESC);
CREATE INDEX idx_chat_messages_session_id ON public.chat_messages USING btree (session_id);
COMMENT ON TABLE public.chat_messages IS 'Individual chat messages within sessions';

-- Permissions

ALTER TABLE public.chat_messages OWNER TO postgres;
GRANT ALL ON TABLE public.chat_messages TO postgres;
GRANT ALL ON TABLE public.chat_messages TO pg_database_owner;


-- public.token_usage_log definition

-- Drop table

-- DROP TABLE public.token_usage_log;

CREATE TABLE public.token_usage_log ( id serial4 NOT NULL, session_id int4 NULL, message_id int4 NULL, provider varchar(50) NOT NULL, model varchar(100) NULL, prompt_tokens int4 DEFAULT 0 NULL, completion_tokens int4 DEFAULT 0 NULL, total_tokens int4 DEFAULT 0 NULL, cost_cents int4 DEFAULT 0 NULL, api_call_type varchar(50) NULL, request_metadata jsonb NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL, CONSTRAINT token_usage_log_pkey PRIMARY KEY (id), CONSTRAINT token_usage_log_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE, CONSTRAINT token_usage_log_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE);
CREATE INDEX idx_token_usage_log_created_at ON public.token_usage_log USING btree (created_at DESC);
CREATE INDEX idx_token_usage_log_message_id ON public.token_usage_log USING btree (message_id);
CREATE INDEX idx_token_usage_log_provider ON public.token_usage_log USING btree (provider);
CREATE INDEX idx_token_usage_log_session_id ON public.token_usage_log USING btree (session_id);
COMMENT ON TABLE public.token_usage_log IS 'Detailed token usage tracking for API calls';

-- Permissions

ALTER TABLE public.token_usage_log OWNER TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO pg_database_owner;


-- Missing tables referenced in DAOs

-- public.feedback definition (for feedback_dao.py)
-- Drop table

-- DROP TABLE public.feedback;

CREATE TABLE public.feedback ( id serial4 NOT NULL, message_id varchar(255) NOT NULL, session_id varchar(255) NOT NULL, feedback varchar(20) NOT NULL, user_email varchar(255) NULL, created_at timestamp DEFAULT now() NULL, CONSTRAINT feedback_pkey PRIMARY KEY (id));
CREATE INDEX idx_feedback_created_at ON public.feedback USING btree (created_at DESC);
CREATE INDEX idx_feedback_session ON public.feedback USING btree (session_id);
CREATE INDEX idx_feedback_message ON public.feedback USING btree (message_id);
COMMENT ON TABLE public.feedback IS 'User feedback on chat messages (legacy table)';

-- Permissions

ALTER TABLE public.feedback OWNER TO postgres;
GRANT ALL ON TABLE public.feedback TO postgres;
GRANT ALL ON TABLE public.feedback TO pg_database_owner;


-- Add persona_description column to persona_configurations if not present
ALTER TABLE public.persona_configurations ADD COLUMN IF NOT EXISTS persona_description text NULL;


-- DROP FUNCTION public.update_updated_at_column();

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$function$
;

-- Permissions

ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO postgres;


-- Permissions

GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;
GRANT USAGE ON SCHEMA public TO postgres;