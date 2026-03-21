-- ============================================================================
-- PRODUCTION DATABASE SCHEMA - Knowledgebot Platform
-- ============================================================================
-- Complete consolidated database schema for production deployment
-- 3NF Normalized design with full audit capabilities
-- Generated: 2026-03-20
--
-- This file contains:
-- - Schema creation with authorization
-- - 13 sequences for auto-increment IDs
-- - 18 tables with constraints and relationships
-- - Comprehensive indexes for query optimization
-- - Automatic timestamp update triggers
-- - Helper functions for data integrity
-- - Default data initialization (roles, personas, admin user, widget config)
-- - Complete permission grants
--
-- USAGE: psql -U postgres -d knowledgebot -f database_schema_production.sql
-- ============================================================================

-- Set session parameters for consistent behavior
SET statement_timeout = '30s';
SET lock_timeout = '10s';

-- ============================================================================
-- SCHEMA SETUP
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS public AUTHORIZATION pg_database_owner;

COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form. Complete audit trail, role-based access control, and session management.';

-- ============================================================================
-- SEQUENCES (Auto-increment ID generators)
-- ============================================================================

-- API Usage tracking
CREATE SEQUENCE IF NOT EXISTS public.api_usage_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.api_usage_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO pg_database_owner;

-- Chat feedback/ratings
CREATE SEQUENCE IF NOT EXISTS public.chat_feedback_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.chat_feedback_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO pg_database_owner;

-- Individual chat messages
CREATE SEQUENCE IF NOT EXISTS public.chat_messages_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.chat_messages_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO pg_database_owner;

-- Chat sessions (conversations)
CREATE SEQUENCE IF NOT EXISTS public.chat_sessions_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.chat_sessions_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO pg_database_owner;

-- Uploaded files
CREATE SEQUENCE IF NOT EXISTS public.file_uploads_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.file_uploads_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO pg_database_owner;

-- LLM provider configurations
CREATE SEQUENCE IF NOT EXISTS public.llm_providers_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.llm_providers_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO pg_database_owner;

-- System metrics
CREATE SEQUENCE IF NOT EXISTS public.metrics_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.metrics_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.metrics_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.metrics_id_seq TO pg_database_owner;

-- Notification settings
CREATE SEQUENCE IF NOT EXISTS public.notification_settings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.notification_settings_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.notification_settings_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.notification_settings_id_seq TO pg_database_owner;

-- User notifications
CREATE SEQUENCE IF NOT EXISTS public.notifications_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.notifications_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.notifications_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.notifications_id_seq TO pg_database_owner;

-- Chatbot personas
CREATE SEQUENCE IF NOT EXISTS public.persona_configurations_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.persona_configurations_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.persona_configurations_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.persona_configurations_id_seq TO pg_database_owner;

-- Scraped websites
CREATE SEQUENCE IF NOT EXISTS public.scraped_websites_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.scraped_websites_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.scraped_websites_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.scraped_websites_id_seq TO pg_database_owner;

-- Security settings
CREATE SEQUENCE IF NOT EXISTS public.security_settings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.security_settings_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.security_settings_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.security_settings_id_seq TO pg_database_owner;

-- Session assignments to agents
CREATE SEQUENCE IF NOT EXISTS public.session_assignments_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.session_assignments_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.session_assignments_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.session_assignments_id_seq TO pg_database_owner;

-- Token usage tracking
CREATE SEQUENCE IF NOT EXISTS public.token_usage_log_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.token_usage_log_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.token_usage_log_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.token_usage_log_id_seq TO pg_database_owner;

-- User accounts
CREATE SEQUENCE IF NOT EXISTS public.users_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.users_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO pg_database_owner;

-- Widget configuration
CREATE SEQUENCE IF NOT EXISTS public.widget_configuration_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.widget_configuration_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO pg_database_owner;

-- Widget suggested messages
CREATE SEQUENCE IF NOT EXISTS public.widget_suggested_messages_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
ALTER SEQUENCE public.widget_suggested_messages_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_suggested_messages_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_suggested_messages_id_seq TO pg_database_owner;

-- ============================================================================
-- TABLES
-- ============================================================================

-- ============================================================================
-- Core User Management
-- ============================================================================

-- User accounts from Firebase Auth
CREATE TABLE IF NOT EXISTS public.users (
	id serial4 NOT NULL,
	email varchar(255) NOT NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	last_login_at timestamptz NULL,
	CONSTRAINT users_pkey PRIMARY KEY (id),
	CONSTRAINT users_email_key UNIQUE (email),
	CONSTRAINT valid_user_email CHECK (((email)::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text))
);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON public.users USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users USING btree (email);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON public.users USING btree (is_active);
COMMENT ON TABLE public.users IS 'User accounts from Firebase Auth';
ALTER TABLE public.users OWNER TO postgres;
GRANT ALL ON TABLE public.users TO postgres;
GRANT ALL ON TABLE public.users TO pg_database_owner;

-- Role definitions (admin, human_agent, user)
CREATE TABLE IF NOT EXISTS public.roles (
	id serial4 NOT NULL,
	role_name varchar(50) NOT NULL,
	role_description text NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT roles_pkey PRIMARY KEY (id),
	CONSTRAINT roles_role_name_key UNIQUE (role_name)
);
CREATE INDEX IF NOT EXISTS idx_roles_role_name ON public.roles USING btree (role_name);
COMMENT ON TABLE public.roles IS 'User roles definition';
ALTER TABLE public.roles OWNER TO postgres;
GRANT ALL ON TABLE public.roles TO postgres;
GRANT ALL ON TABLE public.roles TO pg_database_owner;

-- User-to-role mapping (many-to-many)
CREATE TABLE IF NOT EXISTS public.user_role_mapping (
	user_role_id serial4 NOT NULL,
	user_id int4 NOT NULL,
	role_id int4 NOT NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT user_role_mapping_pkey PRIMARY KEY (user_role_id),
	CONSTRAINT user_role_mapping_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
	CONSTRAINT user_role_mapping_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE,
	CONSTRAINT user_role_mapping_user_role_key UNIQUE (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_user_id ON public.user_role_mapping USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_role_id ON public.user_role_mapping USING btree (role_id);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_is_active ON public.user_role_mapping USING btree (is_active);
COMMENT ON TABLE public.user_role_mapping IS 'Mapping between users and their roles';
ALTER TABLE public.user_role_mapping OWNER TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO pg_database_owner;

-- ============================================================================
-- Chat Session Management
-- ============================================================================

-- Chat sessions (conversations)
CREATE TABLE IF NOT EXISTS public.chat_sessions (
	id serial4 NOT NULL,
	session_id varchar(255) NOT NULL,
	user_role_id int4 NULL,
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
	CONSTRAINT chat_sessions_pkey PRIMARY KEY (id),
	CONSTRAINT chat_sessions_session_id_key UNIQUE (session_id),
	CONSTRAINT chat_sessions_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
	CONSTRAINT chat_sessions_archive_status_check CHECK (((archive_status)::text = ANY (ARRAY[('active'::character varying)::text, ('closed'::character varying)::text, ('archived'::character varying)::text, ('transferred'::character varying)::text]))),
	CONSTRAINT valid_sentiment CHECK (((sentiment)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text, ('neutral'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_session_id ON public.chat_sessions USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_role_id ON public.chat_sessions USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active ON public.chat_sessions USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_status ON public.chat_sessions USING btree (archive_status);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_status_updated ON public.chat_sessions USING btree (archive_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_activity ON public.chat_sessions USING btree (last_activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment ON public.chat_sessions USING btree (sentiment);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_file_search_store_id ON public.chat_sessions USING btree (file_search_store_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_cached_content_id ON public.chat_sessions USING btree (cached_content_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_conversation_summary ON public.chat_sessions USING gin (to_tsvector('english'::regconfig, conversation_summary));
COMMENT ON TABLE public.chat_sessions IS 'Chat session tracking';
COMMENT ON COLUMN public.chat_sessions.sentiment IS 'Overall sentiment analyzed by LLM';
COMMENT ON COLUMN public.chat_sessions.archive_status IS 'Session status: active (ongoing), closed (finished), archived (manually archived), transferred (moved to another agent)';
COMMENT ON COLUMN public.chat_sessions.conversation_summary IS 'AI-generated summary of the conversation, created when session ends';
COMMENT ON COLUMN public.chat_sessions.file_search_store_id IS 'Gemini FileSearchStore ID for RAG optimization';
COMMENT ON COLUMN public.chat_sessions.cached_content_id IS 'Gemini cached content ID for 90% cost discount';
ALTER TABLE public.chat_sessions OWNER TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO postgres;
GRANT ALL ON TABLE public.chat_sessions TO pg_database_owner;

-- Individual chat messages
CREATE TABLE IF NOT EXISTS public.chat_messages (
	id serial4 NOT NULL,
	session_id int4 NOT NULL,
	"role" varchar(50) NOT NULL,
	"content" text NOT NULL,
	used_rag bool DEFAULT false NULL,
	used_postgres bool DEFAULT false NULL,
	confidence_score numeric(3, 2) NULL,
	sources jsonb DEFAULT '[]'::jsonb NULL,
	is_message_read bool DEFAULT false NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT chat_messages_pkey PRIMARY KEY (id),
	CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON public.chat_messages USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role ON public.chat_messages USING btree (role);
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_message_read ON public.chat_messages USING btree (is_message_read);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON public.chat_messages USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_created_at ON public.chat_messages USING btree (role, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_unread ON public.chat_messages USING btree (session_id, is_message_read);
COMMENT ON TABLE public.chat_messages IS 'Individual chat messages within sessions';
ALTER TABLE public.chat_messages OWNER TO postgres;
GRANT ALL ON TABLE public.chat_messages TO postgres;
GRANT ALL ON TABLE public.chat_messages TO pg_database_owner;

-- Chat feedback/ratings
CREATE TABLE IF NOT EXISTS public.chat_feedback (
	id serial4 NOT NULL,
	message_id varchar(255) NOT NULL,
	session_id varchar(255) NOT NULL,
	feedback_type varchar(20) NOT NULL,
	user_role_id int4 NULL,
	created_at timestamp DEFAULT now() NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT chat_feedback_pkey PRIMARY KEY (id),
	CONSTRAINT chat_feedback_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
	CONSTRAINT valid_feedback_type CHECK (((feedback_type)::text = ANY (ARRAY[('positive'::character varying)::text, ('negative'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_session ON public.chat_feedback USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_type ON public.chat_feedback USING btree (feedback_type);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_user_role_id ON public.chat_feedback USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_created_at ON public.chat_feedback USING btree (created_at DESC);
COMMENT ON TABLE public.chat_feedback IS 'User feedback on chat messages with user role reference';
ALTER TABLE public.chat_feedback OWNER TO postgres;
GRANT ALL ON TABLE public.chat_feedback TO postgres;
GRANT ALL ON TABLE public.chat_feedback TO pg_database_owner;

-- Session assignments to human agents
CREATE TABLE IF NOT EXISTS public.session_assignments (
	id serial4 NOT NULL,
	session_id int4 NOT NULL,
	user_role_id int4 NOT NULL,
	status varchar(50) DEFAULT 'active'::character varying NULL,
	assigned_at timestamp DEFAULT now() NULL,
	ended_at timestamp NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT session_assignments_pkey PRIMARY KEY (id),
	CONSTRAINT session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
	CONSTRAINT session_assignments_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE CASCADE,
	CONSTRAINT valid_assignment_status CHECK (((status)::text = ANY (ARRAY[('waiting'::character varying)::text, ('active'::character varying)::text, ('transferred'::character varying)::text, ('ended'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_session_assignments_session ON public.session_assignments USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_role_id ON public.session_assignments USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status ON public.session_assignments USING btree (status);
CREATE INDEX IF NOT EXISTS idx_session_assignments_assigned_at ON public.session_assignments USING btree (assigned_at DESC);
COMMENT ON TABLE public.session_assignments IS 'Tracks which user role is assigned to each session';
ALTER TABLE public.session_assignments OWNER TO postgres;
GRANT ALL ON TABLE public.session_assignments TO postgres;
GRANT ALL ON TABLE public.session_assignments TO pg_database_owner;

-- ============================================================================
-- Knowledge Base Management
-- ============================================================================

-- Uploaded files
CREATE TABLE IF NOT EXISTS public.file_uploads (
	id serial4 NOT NULL,
	user_role_id int4 NULL,
	original_filename varchar(500) NOT NULL,
	display_name varchar(500) NULL,
	file_extension varchar(50) NULL,
	gemini_file_name varchar(500) NULL,
	gemini_file_uri text NULL,
	gemini_state varchar(50) DEFAULT 'pending'::character varying NULL,
	sha256_hash varchar(64) NULL,
	file_size int8 NULL,
	mime_type varchar(100) NULL,
	metadata jsonb DEFAULT '{}'::jsonb NULL,
	"version" int4 DEFAULT 1 NULL,
	processed_by_docling boolean DEFAULT false,
	docling_processing_time_ms int4,
	original_file_extension varchar(50),
	original_mime_type varchar(100),
	docling_images_extracted int4 DEFAULT 0,
	docling_images_with_ocr int4 DEFAULT 0,
	processing_status varchar(20) DEFAULT 'pending'::character varying NULL,
	error_message text NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT file_uploads_pkey PRIMARY KEY (id),
	CONSTRAINT file_uploads_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
	CONSTRAINT valid_processing_status CHECK ((processing_status::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_file_uploads_user_role_id ON public.file_uploads USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_file_uploads_gemini_state ON public.file_uploads USING btree (gemini_state);
CREATE INDEX IF NOT EXISTS idx_file_uploads_gemini_file_name ON public.file_uploads USING btree (gemini_file_name);
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_status ON public.file_uploads USING btree (processing_status);
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_pending ON public.file_uploads(processing_status) WHERE processing_status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_file_uploads_processed_by_docling ON public.file_uploads(processed_by_docling) WHERE processed_by_docling = true;
CREATE INDEX IF NOT EXISTS idx_file_uploads_docling_processing_time ON public.file_uploads(docling_processing_time_ms) WHERE processed_by_docling = true;
CREATE INDEX IF NOT EXISTS idx_file_uploads_created_at ON public.file_uploads USING btree (created_at DESC);
COMMENT ON TABLE public.file_uploads IS 'Uploaded files with Gemini FileSearch integration and Docling processing';
ALTER TABLE public.file_uploads OWNER TO postgres;
GRANT ALL ON TABLE public.file_uploads TO postgres;
GRANT ALL ON TABLE public.file_uploads TO pg_database_owner;

-- Scraped websites
CREATE TABLE IF NOT EXISTS public.scraped_websites (
	id serial4 NOT NULL,
	user_role_id int4 NULL,
	original_url text NOT NULL,
	"domain" varchar(500) NULL,
	title varchar(500) NULL,
	description text NULL,
	pages_scraped int4 DEFAULT 0 NULL,
	content_length int4 DEFAULT 0 NULL,
	gemini_state varchar(50) DEFAULT 'pending'::character varying NULL,
	gemini_file_name varchar(500) NULL,
	gemini_file_uri text NULL,
	metadata jsonb DEFAULT '{}'::jsonb NULL,
	"version" int4 DEFAULT 1 NULL,
	processing_status varchar(20) DEFAULT 'pending'::character varying NULL,
	error_message text NULL,
	celery_task_id varchar(255) NULL,
	depth int4 DEFAULT 0 NULL,
	parent_id int4 NULL,
	crawl_session_id int4 NULL,
	processed_content_s3_key text NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT scraped_websites_pkey PRIMARY KEY (id),
	CONSTRAINT scraped_websites_user_role_id_fkey FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL,
	CONSTRAINT scraped_websites_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.scraped_websites(id) ON DELETE CASCADE,
	CONSTRAINT valid_processing_status_websites CHECK ((processing_status::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text, ('deleted'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_user_role_id ON public.scraped_websites USING btree (user_role_id);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_original_url ON public.scraped_websites USING btree (original_url);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain ON public.scraped_websites USING btree (domain);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_gemini_state ON public.scraped_websites USING btree (gemini_state);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_status ON public.scraped_websites USING btree (processing_status);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_pending ON public.scraped_websites(processing_status) WHERE processing_status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_scraped_websites_celery_task_id ON public.scraped_websites USING btree (celery_task_id);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_parent_id ON public.scraped_websites USING btree (parent_id);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_depth ON public.scraped_websites USING btree (depth);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_crawl_session_id ON public.scraped_websites USING btree (crawl_session_id);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_session_parent ON public.scraped_websites(crawl_session_id, parent_id);
COMMENT ON TABLE public.scraped_websites IS 'Scraped website content for knowledge base';
ALTER TABLE public.scraped_websites OWNER TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO postgres;
GRANT ALL ON TABLE public.scraped_websites TO pg_database_owner;

-- ============================================================================
-- Configuration & Settings
-- ============================================================================

-- Chatbot personas
CREATE TABLE IF NOT EXISTS public.persona_configurations (
	id serial4 NOT NULL,
	persona_name varchar(100) NOT NULL,
	persona_description text NULL,
	system_prompt text NOT NULL,
	is_active bool DEFAULT false NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT persona_configurations_pkey PRIMARY KEY (id),
	CONSTRAINT persona_configurations_persona_name_key UNIQUE (persona_name)
);
CREATE INDEX IF NOT EXISTS idx_persona_configurations_persona_name ON public.persona_configurations USING btree (persona_name);
CREATE INDEX IF NOT EXISTS idx_persona_configurations_is_active ON public.persona_configurations USING btree (is_active);
COMMENT ON TABLE public.persona_configurations IS 'Chatbot persona configurations';
ALTER TABLE public.persona_configurations OWNER TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO postgres;
GRANT ALL ON TABLE public.persona_configurations TO pg_database_owner;

-- Widget configuration (single row - id=1)
CREATE TABLE IF NOT EXISTS public.widget_configuration (
	id serial4 NOT NULL,
	display_name varchar(255) DEFAULT 'GLOBISTAAN'::character varying NULL,
	initial_message text DEFAULT 'Hi! What can I help you with?'::text NULL,
	auto_show_duration int4 DEFAULT 30 NULL,
	keep_showing_suggested bool DEFAULT false NULL,
	theme varchar(50) DEFAULT 'light'::character varying NULL,
	primary_color varchar(7) DEFAULT '#007bff'::character varying NULL,
	use_primary_for_header bool DEFAULT true NULL,
	chat_bubble_color varchar(7) DEFAULT '#f8f9fa'::character varying NULL,
	align_bubble varchar(10) DEFAULT 'right'::character varying NULL,
	display_chatbot bool DEFAULT true NULL,
	profile_picture_url text NULL,
	chat_icon_url text NULL,
	profile_picture_filename varchar(255) NULL,
	chat_icon_filename varchar(255) NULL,
	profile_zoom numeric(3, 2) DEFAULT 1.00 NULL,
	chat_icon_zoom numeric(3, 2) DEFAULT 1.00 NULL,
	profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL,
	chat_icon_position jsonb DEFAULT '{"x": 20, "y": 20}'::jsonb NULL,
	hil_enabled bool DEFAULT true NULL,
	response_policy int4 DEFAULT 30 NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	hil_disabled_message text DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.'::text NULL,
	CONSTRAINT widget_configuration_pkey PRIMARY KEY (id),
	CONSTRAINT single_row CHECK ((id = 1))
);
CREATE INDEX IF NOT EXISTS idx_widget_configuration_display_chatbot ON public.widget_configuration USING btree (display_chatbot);
CREATE INDEX IF NOT EXISTS idx_widget_configuration_theme ON public.widget_configuration USING btree (theme);
COMMENT ON TABLE public.widget_configuration IS 'Widget appearance and behavior settings';
ALTER TABLE public.widget_configuration OWNER TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO postgres;
GRANT ALL ON TABLE public.widget_configuration TO pg_database_owner;

-- Widget suggested messages
CREATE TABLE IF NOT EXISTS public.widget_suggested_messages (
	id serial4 NOT NULL,
	widget_config_id int4 NOT NULL,
	message_text text NOT NULL,
	display_order int4 DEFAULT 0 NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT widget_suggested_messages_pkey PRIMARY KEY (id),
	CONSTRAINT widget_suggested_messages_widget_config_id_fkey FOREIGN KEY (widget_config_id) REFERENCES public.widget_configuration(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_widget_suggested_messages_config_id ON public.widget_suggested_messages USING btree (widget_config_id);
CREATE INDEX IF NOT EXISTS idx_widget_suggested_messages_display_order ON public.widget_suggested_messages USING btree (display_order);
CREATE INDEX IF NOT EXISTS idx_widget_suggested_messages_is_active ON public.widget_suggested_messages USING btree (is_active);
COMMENT ON TABLE public.widget_suggested_messages IS 'Predefined messages that users can click to start conversations';
ALTER TABLE public.widget_suggested_messages OWNER TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO postgres;
GRANT ALL ON TABLE public.widget_suggested_messages TO pg_database_owner;

-- Security settings
CREATE TABLE IF NOT EXISTS public.security_settings (
	id serial4 NOT NULL,
	setting_name varchar(100) NOT NULL,
	setting_value text NULL,
	setting_type varchar(50) DEFAULT 'string'::character varying NULL,
	description text NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT security_settings_pkey PRIMARY KEY (id),
	CONSTRAINT security_settings_setting_name_key UNIQUE (setting_name),
	CONSTRAINT valid_setting_type CHECK (((setting_type)::text = ANY (ARRAY[('string'::character varying)::text, ('integer'::character varying)::text, ('boolean'::character varying)::text, ('json'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_security_settings_setting_name ON public.security_settings USING btree (setting_name);
COMMENT ON TABLE public.security_settings IS 'Security and configuration settings';
ALTER TABLE public.security_settings OWNER TO postgres;
GRANT ALL ON TABLE public.security_settings TO postgres;
GRANT ALL ON TABLE public.security_settings TO pg_database_owner;

-- ============================================================================
-- LLM & API Management
-- ============================================================================

-- LLM provider configurations
CREATE TABLE IF NOT EXISTS public.llm_providers (
	id serial4 NOT NULL,
	provider_name varchar(100) NOT NULL,
	token_limit int8 DEFAULT 0 NULL,
	token_used int8 DEFAULT 0 NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT llm_providers_pkey PRIMARY KEY (id),
	CONSTRAINT llm_providers_provider_name_key UNIQUE (provider_name)
);
CREATE INDEX IF NOT EXISTS idx_llm_providers_provider_name ON public.llm_providers USING btree (provider_name);
CREATE INDEX IF NOT EXISTS idx_llm_providers_is_active ON public.llm_providers USING btree (is_active);
COMMENT ON TABLE public.llm_providers IS 'LLM provider token limits and usage tracking';
ALTER TABLE public.llm_providers OWNER TO postgres;
GRANT ALL ON TABLE public.llm_providers TO postgres;
GRANT ALL ON TABLE public.llm_providers TO pg_database_owner;

-- API usage tracking
CREATE TABLE IF NOT EXISTS public.api_usage (
	id serial4 NOT NULL,
	api_provider varchar(100) NOT NULL,
	api_endpoint varchar(255) NULL,
	http_method varchar(10) NULL,
	request_size_bytes int4 DEFAULT 0 NULL,
	response_size_bytes int4 DEFAULT 0 NULL,
	tokens_input int4 DEFAULT 0 NULL,
	tokens_output int4 DEFAULT 0 NULL,
	user_email varchar(255) NULL,
	request_metadata jsonb DEFAULT '{}'::jsonb NULL,
	last_used_at timestamptz NULL,
	metadata jsonb DEFAULT '{}'::jsonb NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT api_usage_pkey PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON public.api_usage USING btree (api_provider);
CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint ON public.api_usage USING btree (api_endpoint);
CREATE INDEX IF NOT EXISTS idx_api_usage_user_email ON public.api_usage USING btree (user_email);
CREATE INDEX IF NOT EXISTS idx_api_usage_created_at ON public.api_usage USING btree (created_at DESC);
COMMENT ON TABLE public.api_usage IS 'API usage tracking and metrics';
ALTER TABLE public.api_usage OWNER TO postgres;
GRANT ALL ON TABLE public.api_usage TO postgres;
GRANT ALL ON TABLE public.api_usage TO pg_database_owner;

-- Token usage tracking
CREATE TABLE IF NOT EXISTS public.token_usage_log (
	id serial4 NOT NULL,
	session_id int4 NULL,
	message_id int4 NULL,
	provider varchar(50) NOT NULL,
	model varchar(100) NULL,
	prompt_tokens int4 DEFAULT 0 NULL,
	completion_tokens int4 DEFAULT 0 NULL,
	total_tokens int4 DEFAULT 0 NULL,
	cost_cents int4 DEFAULT 0 NULL,
	api_call_type varchar(50) NULL,
	request_metadata jsonb NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT token_usage_log_pkey PRIMARY KEY (id),
	CONSTRAINT token_usage_log_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
	CONSTRAINT token_usage_log_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_session_id ON public.token_usage_log USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_message_id ON public.token_usage_log USING btree (message_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider ON public.token_usage_log USING btree (provider);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_created_at ON public.token_usage_log USING btree (created_at DESC);
COMMENT ON TABLE public.token_usage_log IS 'Detailed token usage tracking for API calls';
ALTER TABLE public.token_usage_log OWNER TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO postgres;
GRANT ALL ON TABLE public.token_usage_log TO pg_database_owner;

-- ============================================================================
-- Monitoring & Notifications
-- ============================================================================

-- System metrics
CREATE TABLE IF NOT EXISTS public.metrics (
	id serial4 NOT NULL,
	metric_type varchar(100) NOT NULL,
	metric_name varchar(255) NOT NULL,
	value numeric(20, 4) NULL,
	unit varchar(50) NULL,
	tags jsonb DEFAULT '{}'::jsonb NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT metrics_pkey PRIMARY KEY (id),
	CONSTRAINT metrics_type_name_unique UNIQUE (metric_type, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_metrics_type ON public.metrics USING btree (metric_type);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON public.metrics USING btree (metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_created_at ON public.metrics USING btree (created_at DESC);
COMMENT ON TABLE public.metrics IS 'System metrics and performance data';
ALTER TABLE public.metrics OWNER TO postgres;
GRANT ALL ON TABLE public.metrics TO postgres;
GRANT ALL ON TABLE public.metrics TO pg_database_owner;

-- User notifications
CREATE TABLE IF NOT EXISTS public.notifications (
	id serial4 NOT NULL,
	user_email varchar(255) NOT NULL,
	title varchar(500) NOT NULL,
	message text NOT NULL,
	"type" varchar(20) DEFAULT 'info'::character varying NULL,
	is_read bool DEFAULT false NULL,
	read_at timestamptz NULL,
	created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT notifications_pkey PRIMARY KEY (id),
	CONSTRAINT valid_notification_type CHECK (((type)::text = ANY (ARRAY[('info'::character varying)::text, ('success'::character varying)::text, ('warning'::character varying)::text, ('error'::character varying)::text])))
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_email ON public.notifications USING btree (user_email);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON public.notifications USING btree (is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON public.notifications USING btree (user_email, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON public.notifications USING btree (created_at DESC);
COMMENT ON TABLE public.notifications IS 'User notifications';
ALTER TABLE public.notifications OWNER TO postgres;
GRANT ALL ON TABLE public.notifications TO postgres;
GRANT ALL ON TABLE public.notifications TO pg_database_owner;

-- Notification settings
CREATE TABLE IF NOT EXISTS public.notification_settings (
	id serial4 NOT NULL,
	user_email varchar(255) NOT NULL,
	notification_type varchar(100) NOT NULL,
	is_enabled bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL
);
ALTER TABLE public.notification_settings OWNER TO postgres;
GRANT ALL ON TABLE public.notification_settings TO postgres;
GRANT ALL ON TABLE public.notification_settings TO pg_database_owner;

-- Service health checks
CREATE TABLE IF NOT EXISTS public.service_health_checks (
	id SERIAL PRIMARY KEY,
	service_name VARCHAR(100) NOT NULL,
	status VARCHAR(20) NOT NULL,
	response_time_ms INTEGER,
	checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	error_message TEXT,
	metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_service_checked
	ON public.service_health_checks(service_name, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_checked_at
	ON public.service_health_checks(checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_status
	ON public.service_health_checks(status);
CREATE INDEX IF NOT EXISTS idx_service_health_checks_status_checked
	ON public.service_health_checks(status, checked_at DESC)
	WHERE status != 'healthy';
COMMENT ON TABLE public.service_health_checks IS 'Tracks health check results for all microservices for monitoring and reporting';
COMMENT ON COLUMN public.service_health_checks.service_name IS 'Name of the service being monitored (e.g., api_gateway, website_crawling)';
COMMENT ON COLUMN public.service_health_checks.status IS 'Health status: healthy, degraded, or down';
COMMENT ON COLUMN public.service_health_checks.response_time_ms IS 'Response time in milliseconds';
COMMENT ON COLUMN public.service_health_checks.checked_at IS 'Timestamp when the check was performed';
COMMENT ON COLUMN public.service_health_checks.error_message IS 'Error message if status is not healthy';
COMMENT ON COLUMN public.service_health_checks.metadata IS 'Additional metadata about the health check (e.g., endpoint, version info)';
ALTER TABLE public.service_health_checks OWNER TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO postgres;
GRANT ALL ON TABLE public.service_health_checks TO pg_database_owner;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Automatic updated_at timestamp trigger function
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    -- Only update updated_at if the row is actually being modified
    -- This compares all columns except updated_at itself
    IF (NEW IS DISTINCT FROM OLD) THEN
        NEW.updated_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$function$;

ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO postgres;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO public;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Automatic updated_at timestamp triggers for all tables

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

DROP TRIGGER IF EXISTS chat_feedback_updated_at_trigger ON public.chat_feedback;
CREATE TRIGGER chat_feedback_updated_at_trigger BEFORE UPDATE ON public.chat_feedback FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

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

-- ============================================================================
-- PERMISSIONS
-- ============================================================================

GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;
GRANT USAGE ON SCHEMA public TO postgres;

-- ============================================================================
-- INITIAL DATA SETUP
-- ============================================================================

-- Insert default roles
INSERT INTO public.roles (role_name, role_description, created_at, updated_at)
VALUES
    ('admin', 'System administrator with full access to all features and settings', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('human_agent', 'Human agent who can handle chat sessions and provide customer support', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('user', 'Regular user with basic access to chat features', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_name) DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

-- Insert default personas
INSERT INTO persona_configurations (persona_name, persona_description, system_prompt, is_active, created_at, updated_at)
VALUES
    ('KnowledgeBot', 'A helpful AI assistant for knowledge management', 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.', true, NOW(), NOW()),
    ('Custom', 'User customizable persona', '', false, NOW(), NOW()),
    ('Friendly Receptionist', 'A warm and professional receptionist persona', 'You are a warm and professional Friendly Receptionist. Your goal is to make every user feel heard and valued. Use polite, welcoming language (e.g., "I''d be happy to help with that!"). Keep responses concise but hospitable. If you cannot solve a request, transition the user gently to the next step without losing your helpful tone.', false, NOW(), NOW()),
    ('Upselling Assistant', 'A strategic upselling assistant persona', 'You are a strategic Upselling Assistant. Your objective is to identify user needs and suggest premium features or add-ons that provide genuine value. Avoid being "pushy"; instead, use phrases like "To get the most out of this, you might consider..." or "Many users find [Feature] helpful for [Benefit]." Always frame suggestions as solutions to the user''s current goals.', false, NOW(), NOW()),
    ('Fast Paced Problem Solver', 'A quick and efficient problem solver persona', 'You are a Fast Paced Problem Solver. Time is of the essence. Omit pleasantries and fluff. Provide direct, actionable answers immediately. Use bullet points for steps and bold text for key terms. Your success is measured by how quickly the user can stop talking to you and start solving their issue. Do NOT add [Time-to-Solve] or any timing metadata to responses.', false, NOW(), NOW()),
    ('Knowledge Based Expert', 'A documentation-based expert persona', 'You are a Knowledge Based Expert. Your responses must be deeply rooted in provided documentation and technical facts. Use precise terminology and provide context for complex concepts. If data is missing, admit it rather than speculating. Maintain a formal, authoritative, yet accessible academic tone.', false, NOW(), NOW()),
    ('The Agile Troubleshooter', 'An agile diagnostic problem solver persona', 'You are The Agile Troubleshooter. Your approach is iterative and diagnostic. Instead of giving a final answer immediately, ask clarifying questions to narrow down the root cause. Use a "If this, then that" logic structure. Be adaptable; if one solution fails, pivot quickly to an alternative strategy.', false, NOW(), NOW()),
    ('The Welcoming Guide', 'A patient onboarding specialist persona', 'You are The Welcoming Guide. You specialize in onboarding new users who may feel overwhelmed. Your tone is patient and encouraging. Use clear, simple language and avoid jargon. Walk the user through processes step-by-step, ensuring they feel confident at each milestone. Think of yourself as a friendly mentor.', false, NOW(), NOW())
ON CONFLICT (persona_name) DO NOTHING;

-- Create admin user and assign roles
DO $$
DECLARE
    user_id_val INTEGER;
    admin_role_id INTEGER;
    human_agent_role_id INTEGER;
BEGIN
    -- Insert or update the user
    INSERT INTO public.users (email, is_active, created_at, updated_at)
    VALUES ('globistaan@gmail.com', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (email) DO UPDATE SET
        is_active = EXCLUDED.is_active,
        updated_at = CURRENT_TIMESTAMP;

    -- Get the user ID
    SELECT id INTO user_id_val FROM public.users WHERE email = 'globistaan@gmail.com';

    -- Get role IDs
    SELECT id INTO admin_role_id FROM public.roles WHERE role_name = 'admin';
    SELECT id INTO human_agent_role_id FROM public.roles WHERE role_name = 'human_agent';

    -- Assign admin role
    INSERT INTO public.user_role_mapping (user_id, role_id, is_active, created_at, updated_at)
    VALUES (user_id_val, admin_role_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id, role_id) DO UPDATE SET
        is_active = EXCLUDED.is_active,
        updated_at = CURRENT_TIMESTAMP;

    -- Assign human_agent role
    INSERT INTO public.user_role_mapping (user_id, role_id, is_active, created_at, updated_at)
    VALUES (user_id_val, human_agent_role_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id, role_id) DO UPDATE SET
        is_active = EXCLUDED.is_active,
        updated_at = CURRENT_TIMESTAMP;
END $$;

-- Initialize default widget configuration (id must be 1 due to single_row constraint)
INSERT INTO public.widget_configuration (
    id, display_name, initial_message, auto_show_duration, keep_showing_suggested,
    theme, primary_color, use_primary_for_header, chat_bubble_color, align_bubble,
    display_chatbot, profile_picture_url, chat_icon_url, profile_picture_filename,
    chat_icon_filename, profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
    hil_enabled, response_policy, hil_disabled_message, created_at, updated_at
) VALUES (
    1, 'GLOBISTAAN', 'Hi! What can I help you with?', 30, false,
    'light', '#007bff', true, '#f8f9fa', 'right',
    true, NULL, NULL, NULL,
    NULL, 1.00, 1.00, '{"x": 0, "y": 0}'::jsonb, '{"x": 20, "y": 20}'::jsonb,
    true, 30, 'Human assistance is currently offline. Please leave a message or try again later.',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SCHEMA FINALIZATION
-- ============================================================================

RESET statement_timeout;
RESET lock_timeout;

-- Verify schema setup
SELECT 'Schema setup complete' AS status,
       (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') AS table_count,
       (SELECT COUNT(*) FROM information_schema.sequences WHERE sequence_schema = 'public') AS sequence_count;

-- End of production database schema
