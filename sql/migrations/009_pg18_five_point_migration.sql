-- ============================================================================
-- PostgreSQL 18 Five-Point Migration
-- ============================================================================
-- Run during maintenance window (requires brief downtime for PK migration)
-- Estimated time: 2-5 minutes for typical dataset sizes
--
-- Pre-requisites:
--   1. PostgreSQL 18+ confirmed
--   2. Full database backup taken
--   3. Application services stopped
--
-- Phases:
--   1. UUID v7 Primary Key Evolution (serial → uuid with FK chain migration)
--   2. Atomic Change Tracking (RETURNING OLD/NEW - application-level, documented here)
--   3. Storage Optimization (Expression indexes instead of generated columns)
--   4. Index Consolidation (Skip scan-aware composite indexes)
--   5. I/O & Connection Tuning (Server configuration)
-- ============================================================================

SET statement_timeout = '300s';  -- 5 min for migration
SET lock_timeout = '60s';

-- ============================================================================
-- VERIFY POSTGRESQL 18+
-- ============================================================================
DO $$
BEGIN
    IF NOT (current_setting('server_version_num')::integer >= 180000) THEN
        RAISE EXCEPTION 'PostgreSQL 18+ required. Current: %', current_setting('server_version');
    END IF;
    RAISE NOTICE 'PostgreSQL % confirmed. Starting migration...', current_setting('server_version');
END $$;

BEGIN;

-- ============================================================================
-- PHASE 1: UUID v7 PRIMARY KEY EVOLUTION
-- ============================================================================
-- Strategy: Add UUID columns → Populate → Migrate FKs → Swap → Drop old
-- Dependency order: Level 0 → Level 1 → Level 2 → Level 3 → Level 4
-- ============================================================================

-- ──────────────────────────────────────────────────────────────────
-- LEVEL 0: Tables with no inbound FK dependencies on their PK
-- ──────────────────────────────────────────────────────────────────

-- users
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.users SET id_new = uuidv7() WHERE id_new IS NULL;

-- roles
ALTER TABLE public.roles ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.roles SET id_new = uuidv7() WHERE id_new IS NULL;

-- persona_configurations
ALTER TABLE public.persona_configurations ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.persona_configurations SET id_new = uuidv7() WHERE id_new IS NULL;

-- security_settings
ALTER TABLE public.security_settings ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.security_settings SET id_new = uuidv7() WHERE id_new IS NULL;

-- widget_configuration (singleton - replace CHECK(id=1) with boolean singleton)
ALTER TABLE public.widget_configuration ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.widget_configuration SET id_new = uuidv7() WHERE id_new IS NULL;

-- llm_providers
ALTER TABLE public.llm_providers ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.llm_providers SET id_new = uuidv7() WHERE id_new IS NULL;

-- metrics
ALTER TABLE public.metrics ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.metrics SET id_new = uuidv7() WHERE id_new IS NULL;

-- notifications
ALTER TABLE public.notifications ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.notifications SET id_new = uuidv7() WHERE id_new IS NULL;

-- api_usage
ALTER TABLE public.api_usage ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.api_usage SET id_new = uuidv7() WHERE id_new IS NULL;

-- service_health_checks
ALTER TABLE public.service_health_checks ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
UPDATE public.service_health_checks SET id_new = uuidv7() WHERE id_new IS NULL;

-- ──────────────────────────────────────────────────────────────────
-- LEVEL 1: user_role_mapping (FK → users.id, roles.id)
-- ──────────────────────────────────────────────────────────────────

ALTER TABLE public.user_role_mapping ADD COLUMN IF NOT EXISTS user_role_id_new uuid DEFAULT uuidv7();
ALTER TABLE public.user_role_mapping ADD COLUMN IF NOT EXISTS user_id_new uuid;
ALTER TABLE public.user_role_mapping ADD COLUMN IF NOT EXISTS role_id_new uuid;

UPDATE public.user_role_mapping SET user_role_id_new = uuidv7() WHERE user_role_id_new IS NULL;

-- Populate FK references via joins
UPDATE public.user_role_mapping urm
SET user_id_new = u.id_new
FROM public.users u
WHERE urm.user_id = u.id;

UPDATE public.user_role_mapping urm
SET role_id_new = r.id_new
FROM public.roles r
WHERE urm.role_id = r.id;

-- ──────────────────────────────────────────────────────────────────
-- LEVEL 2: Tables referencing user_role_mapping + widget_configuration
-- ──────────────────────────────────────────────────────────────────

-- chat_sessions
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS user_role_id_new uuid;

UPDATE public.chat_sessions SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.chat_sessions cs
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE cs.user_role_id = urm.user_role_id;

-- file_uploads
ALTER TABLE public.file_uploads ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.file_uploads ADD COLUMN IF NOT EXISTS user_role_id_new uuid;

UPDATE public.file_uploads SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.file_uploads fu
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE fu.user_role_id = urm.user_role_id;

-- scraped_websites (FK → user_role_mapping + self-referencing parent_id)
ALTER TABLE public.scraped_websites ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.scraped_websites ADD COLUMN IF NOT EXISTS user_role_id_new uuid;
ALTER TABLE public.scraped_websites ADD COLUMN IF NOT EXISTS parent_id_new uuid;

UPDATE public.scraped_websites SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.scraped_websites sw
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE sw.user_role_id = urm.user_role_id;

-- Self-referencing FK (parent_id → scraped_websites.id)
UPDATE public.scraped_websites child
SET parent_id_new = parent.id_new
FROM public.scraped_websites parent
WHERE child.parent_id = parent.id;

-- widget_suggested_messages (FK → widget_configuration)
ALTER TABLE public.widget_suggested_messages ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.widget_suggested_messages ADD COLUMN IF NOT EXISTS widget_config_id_new uuid;

UPDATE public.widget_suggested_messages SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.widget_suggested_messages wsm
SET widget_config_id_new = wc.id_new
FROM public.widget_configuration wc
WHERE wsm.widget_config_id = wc.id;

-- admin_sessions (user_role_id INT, no FK constraint defined but referencing user_role_mapping)
ALTER TABLE public.admin_sessions ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.admin_sessions ADD COLUMN IF NOT EXISTS user_role_id_new uuid;

UPDATE public.admin_sessions SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.admin_sessions ases
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE ases.user_role_id = urm.user_role_id;

-- ──────────────────────────────────────────────────────────────────
-- LEVEL 3: Tables referencing chat_sessions
-- ──────────────────────────────────────────────────────────────────

-- chat_messages
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS session_id_new uuid;

UPDATE public.chat_messages SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.chat_messages cm
SET session_id_new = cs.id_new
FROM public.chat_sessions cs
WHERE cm.session_id = cs.id;

-- session_assignments (FK → chat_sessions.id + user_role_mapping.user_role_id)
ALTER TABLE public.session_assignments ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.session_assignments ADD COLUMN IF NOT EXISTS session_id_new uuid;
ALTER TABLE public.session_assignments ADD COLUMN IF NOT EXISTS user_role_id_new uuid;

UPDATE public.session_assignments SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.session_assignments sa
SET session_id_new = cs.id_new
FROM public.chat_sessions cs
WHERE sa.session_id = cs.id;

UPDATE public.session_assignments sa
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE sa.user_role_id = urm.user_role_id;

-- admin_actions (session_id INT referencing admin_sessions.id)
ALTER TABLE public.admin_actions ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.admin_actions ADD COLUMN IF NOT EXISTS session_id_new uuid;
ALTER TABLE public.admin_actions ADD COLUMN IF NOT EXISTS user_role_id_new uuid;

UPDATE public.admin_actions SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.admin_actions aa
SET session_id_new = ases.id_new
FROM public.admin_sessions ases
WHERE aa.session_id = ases.id;

UPDATE public.admin_actions aa
SET user_role_id_new = urm.user_role_id_new
FROM public.user_role_mapping urm
WHERE aa.user_role_id = urm.user_role_id;

-- ──────────────────────────────────────────────────────────────────
-- LEVEL 4: Tables referencing chat_sessions + chat_messages
-- ──────────────────────────────────────────────────────────────────

-- token_usage_log
ALTER TABLE public.token_usage_log ADD COLUMN IF NOT EXISTS id_new uuid DEFAULT uuidv7();
ALTER TABLE public.token_usage_log ADD COLUMN IF NOT EXISTS session_id_new uuid;
ALTER TABLE public.token_usage_log ADD COLUMN IF NOT EXISTS message_id_new uuid;

UPDATE public.token_usage_log SET id_new = uuidv7() WHERE id_new IS NULL;

UPDATE public.token_usage_log tul
SET session_id_new = cs.id_new
FROM public.chat_sessions cs
WHERE tul.session_id = cs.id;

UPDATE public.token_usage_log tul
SET message_id_new = cm.id_new
FROM public.chat_messages cm
WHERE tul.message_id = cm.id;

-- ──────────────────────────────────────────────────────────────────
-- DROP ALL FOREIGN KEY CONSTRAINTS (bottom-up)
-- ──────────────────────────────────────────────────────────────────

-- Level 4
ALTER TABLE public.token_usage_log DROP CONSTRAINT IF EXISTS token_usage_log_session_id_fkey;
ALTER TABLE public.token_usage_log DROP CONSTRAINT IF EXISTS token_usage_log_message_id_fkey;

-- Level 3
ALTER TABLE public.chat_messages DROP CONSTRAINT IF EXISTS chat_messages_session_id_fkey;
ALTER TABLE public.session_assignments DROP CONSTRAINT IF EXISTS session_assignments_session_id_fkey;
ALTER TABLE public.session_assignments DROP CONSTRAINT IF EXISTS session_assignments_user_role_id_fkey;

-- Level 2
ALTER TABLE public.chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_user_role_id_fkey;
ALTER TABLE public.file_uploads DROP CONSTRAINT IF EXISTS file_uploads_user_role_id_fkey;
ALTER TABLE public.scraped_websites DROP CONSTRAINT IF EXISTS scraped_websites_user_role_id_fkey;
ALTER TABLE public.scraped_websites DROP CONSTRAINT IF EXISTS scraped_websites_parent_id_fkey;
ALTER TABLE public.widget_suggested_messages DROP CONSTRAINT IF EXISTS widget_suggested_messages_widget_config_id_fkey;

-- Level 1
ALTER TABLE public.user_role_mapping DROP CONSTRAINT IF EXISTS user_role_mapping_user_id_fkey;
ALTER TABLE public.user_role_mapping DROP CONSTRAINT IF EXISTS user_role_mapping_role_id_fkey;

-- Also drop chat_feedback FK if table still exists
ALTER TABLE IF EXISTS public.chat_feedback DROP CONSTRAINT IF EXISTS chat_feedback_user_role_id_fkey;

-- ──────────────────────────────────────────────────────────────────
-- DROP OLD PRIMARY KEYS AND UNIQUE CONSTRAINTS
-- ──────────────────────────────────────────────────────────────────

ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE public.roles DROP CONSTRAINT IF EXISTS roles_pkey;
ALTER TABLE public.user_role_mapping DROP CONSTRAINT IF EXISTS user_role_mapping_pkey;
ALTER TABLE public.user_role_mapping DROP CONSTRAINT IF EXISTS user_role_mapping_user_role_key;
ALTER TABLE public.chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_pkey;
ALTER TABLE public.chat_messages DROP CONSTRAINT IF EXISTS chat_messages_pkey;
ALTER TABLE public.file_uploads DROP CONSTRAINT IF EXISTS file_uploads_pkey;
ALTER TABLE public.scraped_websites DROP CONSTRAINT IF EXISTS scraped_websites_pkey;
ALTER TABLE public.session_assignments DROP CONSTRAINT IF EXISTS session_assignments_pkey;
ALTER TABLE public.widget_configuration DROP CONSTRAINT IF EXISTS widget_configuration_pkey;
ALTER TABLE public.widget_configuration DROP CONSTRAINT IF EXISTS single_row;
ALTER TABLE public.widget_suggested_messages DROP CONSTRAINT IF EXISTS widget_suggested_messages_pkey;
ALTER TABLE public.token_usage_log DROP CONSTRAINT IF EXISTS token_usage_log_pkey;
ALTER TABLE public.persona_configurations DROP CONSTRAINT IF EXISTS persona_configurations_pkey;
ALTER TABLE public.security_settings DROP CONSTRAINT IF EXISTS security_settings_pkey;
ALTER TABLE public.llm_providers DROP CONSTRAINT IF EXISTS llm_providers_pkey;
ALTER TABLE public.metrics DROP CONSTRAINT IF EXISTS metrics_pkey;
ALTER TABLE public.notifications DROP CONSTRAINT IF EXISTS notifications_pkey;
ALTER TABLE public.api_usage DROP CONSTRAINT IF EXISTS api_usage_pkey;
ALTER TABLE public.service_health_checks DROP CONSTRAINT IF EXISTS service_health_checks_pkey;
ALTER TABLE public.admin_sessions DROP CONSTRAINT IF EXISTS admin_sessions_pkey;
ALTER TABLE public.admin_actions DROP CONSTRAINT IF EXISTS admin_actions_pkey;

-- ──────────────────────────────────────────────────────────────────
-- DROP OLD COLUMNS, RENAME NEW → FINAL NAMES
-- ──────────────────────────────────────────────────────────────────

-- === LEVEL 0 TABLES ===

-- users
ALTER TABLE public.users DROP COLUMN id;
ALTER TABLE public.users RENAME COLUMN id_new TO id;
ALTER TABLE public.users ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.users ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.users ADD PRIMARY KEY (id);

-- roles
ALTER TABLE public.roles DROP COLUMN id;
ALTER TABLE public.roles RENAME COLUMN id_new TO id;
ALTER TABLE public.roles ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.roles ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.roles ADD PRIMARY KEY (id);

-- persona_configurations
ALTER TABLE public.persona_configurations DROP COLUMN id;
ALTER TABLE public.persona_configurations RENAME COLUMN id_new TO id;
ALTER TABLE public.persona_configurations ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.persona_configurations ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.persona_configurations ADD PRIMARY KEY (id);

-- security_settings
ALTER TABLE public.security_settings DROP COLUMN id;
ALTER TABLE public.security_settings RENAME COLUMN id_new TO id;
ALTER TABLE public.security_settings ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.security_settings ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.security_settings ADD PRIMARY KEY (id);

-- widget_configuration (singleton pattern: boolean UNIQUE constraint)
ALTER TABLE public.widget_configuration DROP COLUMN id;
ALTER TABLE public.widget_configuration RENAME COLUMN id_new TO id;
ALTER TABLE public.widget_configuration ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.widget_configuration ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.widget_configuration ADD PRIMARY KEY (id);
-- Replace CHECK(id=1) with boolean singleton pattern
ALTER TABLE public.widget_configuration ADD COLUMN IF NOT EXISTS is_singleton bool DEFAULT true NOT NULL;
ALTER TABLE public.widget_configuration ADD CONSTRAINT widget_config_singleton UNIQUE (is_singleton);
ALTER TABLE public.widget_configuration ADD CONSTRAINT widget_config_singleton_check CHECK (is_singleton = true);

-- llm_providers
ALTER TABLE public.llm_providers DROP COLUMN id;
ALTER TABLE public.llm_providers RENAME COLUMN id_new TO id;
ALTER TABLE public.llm_providers ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.llm_providers ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.llm_providers ADD PRIMARY KEY (id);

-- metrics
ALTER TABLE public.metrics DROP COLUMN id;
ALTER TABLE public.metrics RENAME COLUMN id_new TO id;
ALTER TABLE public.metrics ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.metrics ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.metrics ADD PRIMARY KEY (id);

-- notifications
ALTER TABLE public.notifications DROP COLUMN id;
ALTER TABLE public.notifications RENAME COLUMN id_new TO id;
ALTER TABLE public.notifications ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.notifications ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.notifications ADD PRIMARY KEY (id);

-- api_usage
ALTER TABLE public.api_usage DROP COLUMN id;
ALTER TABLE public.api_usage RENAME COLUMN id_new TO id;
ALTER TABLE public.api_usage ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.api_usage ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.api_usage ADD PRIMARY KEY (id);

-- service_health_checks
ALTER TABLE public.service_health_checks DROP COLUMN id;
ALTER TABLE public.service_health_checks RENAME COLUMN id_new TO id;
ALTER TABLE public.service_health_checks ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.service_health_checks ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.service_health_checks ADD PRIMARY KEY (id);

-- === LEVEL 1: user_role_mapping ===

ALTER TABLE public.user_role_mapping DROP COLUMN user_role_id;
ALTER TABLE public.user_role_mapping DROP COLUMN user_id;
ALTER TABLE public.user_role_mapping DROP COLUMN role_id;
ALTER TABLE public.user_role_mapping RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.user_role_mapping RENAME COLUMN user_id_new TO user_id;
ALTER TABLE public.user_role_mapping RENAME COLUMN role_id_new TO role_id;
ALTER TABLE public.user_role_mapping ALTER COLUMN user_role_id SET NOT NULL;
ALTER TABLE public.user_role_mapping ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE public.user_role_mapping ALTER COLUMN role_id SET NOT NULL;
ALTER TABLE public.user_role_mapping ALTER COLUMN user_role_id SET DEFAULT uuidv7();
ALTER TABLE public.user_role_mapping ADD PRIMARY KEY (user_role_id);
ALTER TABLE public.user_role_mapping ADD CONSTRAINT user_role_mapping_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE public.user_role_mapping ADD CONSTRAINT user_role_mapping_role_id_fkey
    FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
ALTER TABLE public.user_role_mapping ADD CONSTRAINT user_role_mapping_user_role_key UNIQUE (user_id, role_id);

-- === LEVEL 2 ===

-- chat_sessions
ALTER TABLE public.chat_sessions DROP COLUMN id;
ALTER TABLE public.chat_sessions DROP COLUMN user_role_id;
ALTER TABLE public.chat_sessions RENAME COLUMN id_new TO id;
ALTER TABLE public.chat_sessions RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.chat_sessions ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.chat_sessions ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.chat_sessions ADD PRIMARY KEY (id);
ALTER TABLE public.chat_sessions ADD CONSTRAINT chat_sessions_user_role_id_fkey
    FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL;

-- file_uploads
ALTER TABLE public.file_uploads DROP COLUMN id;
ALTER TABLE public.file_uploads DROP COLUMN user_role_id;
ALTER TABLE public.file_uploads RENAME COLUMN id_new TO id;
ALTER TABLE public.file_uploads RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.file_uploads ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.file_uploads ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.file_uploads ADD PRIMARY KEY (id);
ALTER TABLE public.file_uploads ADD CONSTRAINT file_uploads_user_role_id_fkey
    FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL;

-- scraped_websites
ALTER TABLE public.scraped_websites DROP COLUMN id;
ALTER TABLE public.scraped_websites DROP COLUMN user_role_id;
ALTER TABLE public.scraped_websites DROP COLUMN parent_id;
ALTER TABLE public.scraped_websites RENAME COLUMN id_new TO id;
ALTER TABLE public.scraped_websites RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.scraped_websites RENAME COLUMN parent_id_new TO parent_id;
ALTER TABLE public.scraped_websites ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.scraped_websites ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.scraped_websites ADD PRIMARY KEY (id);
ALTER TABLE public.scraped_websites ADD CONSTRAINT scraped_websites_user_role_id_fkey
    FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL;
ALTER TABLE public.scraped_websites ADD CONSTRAINT scraped_websites_parent_id_fkey
    FOREIGN KEY (parent_id) REFERENCES public.scraped_websites(id) ON DELETE CASCADE;

-- widget_suggested_messages
ALTER TABLE public.widget_suggested_messages DROP COLUMN id;
ALTER TABLE public.widget_suggested_messages DROP COLUMN widget_config_id;
ALTER TABLE public.widget_suggested_messages RENAME COLUMN id_new TO id;
ALTER TABLE public.widget_suggested_messages RENAME COLUMN widget_config_id_new TO widget_config_id;
ALTER TABLE public.widget_suggested_messages ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.widget_suggested_messages ALTER COLUMN widget_config_id SET NOT NULL;
ALTER TABLE public.widget_suggested_messages ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.widget_suggested_messages ADD PRIMARY KEY (id);
ALTER TABLE public.widget_suggested_messages ADD CONSTRAINT widget_suggested_messages_widget_config_id_fkey
    FOREIGN KEY (widget_config_id) REFERENCES public.widget_configuration(id) ON DELETE CASCADE;

-- admin_sessions
ALTER TABLE public.admin_sessions DROP COLUMN id;
ALTER TABLE public.admin_sessions DROP COLUMN user_role_id;
ALTER TABLE public.admin_sessions RENAME COLUMN id_new TO id;
ALTER TABLE public.admin_sessions RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.admin_sessions ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.admin_sessions ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.admin_sessions ADD PRIMARY KEY (id);

-- === LEVEL 3 ===

-- chat_messages
ALTER TABLE public.chat_messages DROP COLUMN id;
ALTER TABLE public.chat_messages DROP COLUMN session_id;
ALTER TABLE public.chat_messages RENAME COLUMN id_new TO id;
ALTER TABLE public.chat_messages RENAME COLUMN session_id_new TO session_id;
ALTER TABLE public.chat_messages ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.chat_messages ALTER COLUMN session_id SET NOT NULL;
ALTER TABLE public.chat_messages ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.chat_messages ADD PRIMARY KEY (id);
ALTER TABLE public.chat_messages ADD CONSTRAINT chat_messages_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;

-- session_assignments
ALTER TABLE public.session_assignments DROP COLUMN id;
ALTER TABLE public.session_assignments DROP COLUMN session_id;
ALTER TABLE public.session_assignments DROP COLUMN user_role_id;
ALTER TABLE public.session_assignments RENAME COLUMN id_new TO id;
ALTER TABLE public.session_assignments RENAME COLUMN session_id_new TO session_id;
ALTER TABLE public.session_assignments RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.session_assignments ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.session_assignments ALTER COLUMN session_id SET NOT NULL;
ALTER TABLE public.session_assignments ALTER COLUMN user_role_id SET NOT NULL;
ALTER TABLE public.session_assignments ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.session_assignments ADD PRIMARY KEY (id);
ALTER TABLE public.session_assignments ADD CONSTRAINT session_assignments_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;
ALTER TABLE public.session_assignments ADD CONSTRAINT session_assignments_user_role_id_fkey
    FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE CASCADE;

-- admin_actions
ALTER TABLE public.admin_actions DROP COLUMN id;
ALTER TABLE public.admin_actions DROP COLUMN session_id;
ALTER TABLE public.admin_actions DROP COLUMN user_role_id;
ALTER TABLE public.admin_actions RENAME COLUMN id_new TO id;
ALTER TABLE public.admin_actions RENAME COLUMN session_id_new TO session_id;
ALTER TABLE public.admin_actions RENAME COLUMN user_role_id_new TO user_role_id;
ALTER TABLE public.admin_actions ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.admin_actions ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.admin_actions ADD PRIMARY KEY (id);
-- Enable the FK that was previously commented out
ALTER TABLE public.admin_actions ADD CONSTRAINT fk_admin_actions_session_id
    FOREIGN KEY (session_id) REFERENCES public.admin_sessions(id) ON DELETE CASCADE;

-- === LEVEL 4 ===

-- token_usage_log
ALTER TABLE public.token_usage_log DROP COLUMN id;
ALTER TABLE public.token_usage_log DROP COLUMN session_id;
ALTER TABLE public.token_usage_log DROP COLUMN message_id;
ALTER TABLE public.token_usage_log RENAME COLUMN id_new TO id;
ALTER TABLE public.token_usage_log RENAME COLUMN session_id_new TO session_id;
ALTER TABLE public.token_usage_log RENAME COLUMN message_id_new TO message_id;
ALTER TABLE public.token_usage_log ALTER COLUMN id SET NOT NULL;
ALTER TABLE public.token_usage_log ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE public.token_usage_log ADD PRIMARY KEY (id);
ALTER TABLE public.token_usage_log ADD CONSTRAINT token_usage_log_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;
ALTER TABLE public.token_usage_log ADD CONSTRAINT token_usage_log_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE;

-- ──────────────────────────────────────────────────────────────────
-- DROP ORPHANED SEQUENCES (no longer needed with UUID v7)
-- ──────────────────────────────────────────────────────────────────

DROP SEQUENCE IF EXISTS public.users_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.chat_sessions_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.chat_messages_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.file_uploads_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.scraped_websites_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.session_assignments_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.widget_configuration_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.widget_suggested_messages_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.token_usage_log_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.persona_configurations_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.security_settings_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.llm_providers_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.metrics_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.notifications_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.notification_settings_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.api_usage_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.chat_feedback_id_seq CASCADE;

-- ============================================================================
-- PHASE 1b: DROP REDUNDANT created_at INDEXES
-- ============================================================================
-- UUID v7 PKs provide chronological ordering via ORDER BY id DESC
-- These created_at indexes are now redundant for sorting
-- ============================================================================

DROP INDEX IF EXISTS idx_users_created_at;
DROP INDEX IF EXISTS idx_api_usage_created_at;
DROP INDEX IF EXISTS idx_chat_feedback_created_at;
DROP INDEX IF EXISTS idx_metrics_created_at;
DROP INDEX IF EXISTS idx_notifications_created_at;
DROP INDEX IF EXISTS idx_chat_messages_created_at;
DROP INDEX IF EXISTS idx_token_usage_log_created_at;
DROP INDEX IF EXISTS idx_file_uploads_created_at;
DROP INDEX IF EXISTS idx_service_health_checks_checked_at;
DROP INDEX IF EXISTS idx_admin_sessions_login_at;
DROP INDEX IF EXISTS idx_admin_sessions_last_activity_at;
DROP INDEX IF EXISTS idx_admin_actions_created_at;
DROP INDEX IF EXISTS idx_session_assignments_assigned_at;

-- ============================================================================
-- PHASE 3: STORAGE OPTIMIZATION - Expression Indexes
-- ============================================================================
-- IMPORTANT: PG18 virtual generated columns CANNOT have GIN indexes.
-- Instead, use expression indexes which store the computed value in the
-- index only (not in the heap), achieving the same disk savings.
-- ============================================================================

-- Full-text search on chat messages (expression index, no generated column needed)
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_fts
    ON public.chat_messages USING gin(to_tsvector('english'::regconfig, "content"));

-- Full-text search on conversation summaries
DROP INDEX IF EXISTS idx_chat_sessions_conversation_summary;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_summary_fts
    ON public.chat_sessions USING gin(to_tsvector('english'::regconfig, coalesce(conversation_summary, '')));

-- ============================================================================
-- PHASE 4: INDEX CONSOLIDATION (Skip Scan Optimization)
-- ============================================================================
-- PG18 Skip Scans allow composite indexes with low-cardinality leading
-- columns to serve queries on any suffix column efficiently.
-- Strategy: Merge narrow single-column indexes into broad composite ones.
-- ============================================================================

-- ── users ──
DROP INDEX IF EXISTS idx_users_is_active;
DROP INDEX IF EXISTS idx_users_email;  -- Already covered by UNIQUE constraint
CREATE INDEX IF NOT EXISTS idx_users_is_active_id
    ON public.users(is_active, id DESC);  -- Skip scan: jump past is_active=false

-- ── user_role_mapping ──
DROP INDEX IF EXISTS idx_user_role_mapping_is_active;
DROP INDEX IF EXISTS idx_user_role_mapping_user_id;
DROP INDEX IF EXISTS idx_user_role_mapping_role_id;
CREATE INDEX IF NOT EXISTS idx_urm_user_active
    ON public.user_role_mapping(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_urm_role_active
    ON public.user_role_mapping(role_id, is_active);

-- ── chat_sessions ──
DROP INDEX IF EXISTS idx_chat_sessions_is_active;
DROP INDEX IF EXISTS idx_chat_sessions_archive_status;
DROP INDEX IF EXISTS idx_chat_sessions_sentiment;
DROP INDEX IF EXISTS idx_chat_sessions_session_id;  -- Covered by UNIQUE
DROP INDEX IF EXISTS idx_chat_sessions_user_role_id;
DROP INDEX IF EXISTS idx_chat_sessions_archive_status_updated;
DROP INDEX IF EXISTS idx_chat_sessions_cached_content_id;
DROP INDEX IF EXISTS idx_chat_sessions_last_activity;

-- Consolidated composite indexes
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_user_id
    ON public.chat_sessions(archive_status, user_role_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_active_id
    ON public.chat_sessions(is_active, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment_id
    ON public.chat_sessions(sentiment, id DESC);
-- Partial index for Gemini file search
CREATE INDEX IF NOT EXISTS idx_chat_sessions_file_search
    ON public.chat_sessions(file_search_store_id) WHERE file_search_store_id IS NOT NULL;

-- ── chat_messages ──
DROP INDEX IF EXISTS idx_chat_messages_role;
DROP INDEX IF EXISTS idx_chat_messages_session_id;
DROP INDEX IF EXISTS idx_chat_messages_is_message_read;
DROP INDEX IF EXISTS idx_chat_messages_role_created_at;

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
    ON public.chat_messages(session_id, id ASC);  -- Messages in session order
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_id
    ON public.chat_messages(role, id DESC);  -- Skip scan by role
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_unread
    ON public.chat_messages(session_id, is_message_read) WHERE is_message_read = false;  -- Partial

-- ── file_uploads ──
DROP INDEX IF EXISTS idx_file_uploads_processing_status;
DROP INDEX IF EXISTS idx_file_uploads_gemini_state;
DROP INDEX IF EXISTS idx_file_uploads_user_role_id;
DROP INDEX IF EXISTS idx_file_uploads_gemini_file_name;
DROP INDEX IF EXISTS idx_file_uploads_processed_by_docling;
DROP INDEX IF EXISTS idx_file_uploads_docling_processing_time;
DROP INDEX IF EXISTS idx_file_uploads_processing_pending;

CREATE INDEX IF NOT EXISTS idx_file_uploads_status_id
    ON public.file_uploads(processing_status, id DESC);  -- Skip scan
CREATE INDEX IF NOT EXISTS idx_file_uploads_user_status
    ON public.file_uploads(user_role_id, processing_status);
-- Partial for active processing only
CREATE INDEX IF NOT EXISTS idx_file_uploads_pending
    ON public.file_uploads(id DESC) WHERE processing_status IN ('pending', 'processing');

-- ── scraped_websites ──
DROP INDEX IF EXISTS idx_scraped_websites_processing_status;
DROP INDEX IF EXISTS idx_scraped_websites_gemini_state;
DROP INDEX IF EXISTS idx_scraped_websites_user_role_id;
DROP INDEX IF EXISTS idx_scraped_websites_original_url;
DROP INDEX IF EXISTS idx_scraped_websites_celery_task_id;
DROP INDEX IF EXISTS idx_scraped_websites_parent_id;
DROP INDEX IF EXISTS idx_scraped_websites_depth;
DROP INDEX IF EXISTS idx_scraped_websites_crawl_session_id;
DROP INDEX IF EXISTS idx_scraped_websites_session_parent;
DROP INDEX IF EXISTS idx_scraped_websites_processing_pending;

CREATE INDEX IF NOT EXISTS idx_scraped_websites_status_id
    ON public.scraped_websites(processing_status, id DESC);  -- Skip scan
CREATE INDEX IF NOT EXISTS idx_scraped_websites_hierarchy
    ON public.scraped_websites(crawl_session_id, parent_id, depth);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_domain
    ON public.scraped_websites(domain);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_pending
    ON public.scraped_websites(id DESC) WHERE processing_status IN ('pending', 'processing');

-- ── notifications ──
DROP INDEX IF EXISTS idx_notifications_is_read;
DROP INDEX IF EXISTS idx_notifications_user_email;
DROP INDEX IF EXISTS idx_notifications_user_read;

CREATE INDEX IF NOT EXISTS idx_notifications_user_read_id
    ON public.notifications(user_email, is_read, id DESC);  -- Skip scan on is_read

-- ── token_usage_log ──
DROP INDEX IF EXISTS idx_token_usage_log_provider;
DROP INDEX IF EXISTS idx_token_usage_log_session_id;
DROP INDEX IF EXISTS idx_token_usage_log_message_id;

CREATE INDEX IF NOT EXISTS idx_token_usage_log_session_id
    ON public.token_usage_log(session_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider_id
    ON public.token_usage_log(provider, id DESC);  -- Skip scan

-- ── admin_sessions ──
DROP INDEX IF EXISTS idx_admin_sessions_session_id;  -- Covered by UNIQUE
DROP INDEX IF EXISTS idx_admin_sessions_user_role_id;
DROP INDEX IF EXISTS idx_admin_sessions_email;
DROP INDEX IF EXISTS idx_admin_sessions_role_name;
DROP INDEX IF EXISTS idx_admin_sessions_is_active;
DROP INDEX IF EXISTS idx_admin_sessions_email_active;
DROP INDEX IF EXISTS idx_admin_sessions_expires_at;
DROP INDEX IF EXISTS idx_admin_sessions_email_login;
DROP INDEX IF EXISTS idx_admin_sessions_active_user;

CREATE INDEX IF NOT EXISTS idx_admin_sessions_email_active_id
    ON public.admin_sessions(email, is_active, id DESC);  -- Covers email + active + chronological
CREATE INDEX IF NOT EXISTS idx_admin_sessions_active_expires
    ON public.admin_sessions(is_active, expires_at) WHERE is_active = true;  -- Partial for expiry checks

-- ── admin_actions ──
DROP INDEX IF EXISTS idx_admin_actions_action_id;  -- Covered by UNIQUE
DROP INDEX IF EXISTS idx_admin_actions_session_id;
DROP INDEX IF EXISTS idx_admin_actions_user_role_id;
DROP INDEX IF EXISTS idx_admin_actions_email;
DROP INDEX IF EXISTS idx_admin_actions_action_type;
DROP INDEX IF EXISTS idx_admin_actions_action_category;
DROP INDEX IF EXISTS idx_admin_actions_success;
DROP INDEX IF EXISTS idx_admin_actions_email_created;
DROP INDEX IF EXISTS idx_admin_actions_category_created;
DROP INDEX IF EXISTS idx_admin_actions_category_success;
DROP INDEX IF EXISTS idx_admin_actions_email_category;

CREATE INDEX IF NOT EXISTS idx_admin_actions_category_id
    ON public.admin_actions(action_category, id DESC);  -- Skip scan: category is low-cardinality
CREATE INDEX IF NOT EXISTS idx_admin_actions_email_id
    ON public.admin_actions(email, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_actions_session_id
    ON public.admin_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_admin_actions_failed
    ON public.admin_actions(id DESC) WHERE success = false;  -- Partial for error monitoring

-- ── metrics ──
DROP INDEX IF EXISTS idx_metrics_type;
DROP INDEX IF EXISTS idx_metrics_name;
DROP INDEX IF EXISTS idx_metrics_created_at;

CREATE INDEX IF NOT EXISTS idx_metrics_type_id
    ON public.metrics(metric_type, id DESC);  -- Skip scan

-- ── llm_providers ──
DROP INDEX IF EXISTS idx_llm_providers_is_active;
DROP INDEX IF EXISTS idx_llm_providers_provider_name;  -- Covered by UNIQUE

CREATE INDEX IF NOT EXISTS idx_llm_providers_active_id
    ON public.llm_providers(is_active DESC, id DESC);  -- Skip scan

-- ── service_health_checks ──
DROP INDEX IF EXISTS idx_service_health_checks_status;
DROP INDEX IF EXISTS idx_service_health_checks_service_checked;
DROP INDEX IF EXISTS idx_service_health_checks_status_checked;

CREATE INDEX IF NOT EXISTS idx_health_checks_service_id
    ON public.service_health_checks(service_name, id DESC);
CREATE INDEX IF NOT EXISTS idx_health_checks_unhealthy
    ON public.service_health_checks(status, id DESC) WHERE status != 'healthy';  -- Partial

-- ── widget_suggested_messages ──
DROP INDEX IF EXISTS idx_widget_suggested_messages_config_id;
DROP INDEX IF EXISTS idx_widget_suggested_messages_display_order;
DROP INDEX IF EXISTS idx_widget_suggested_messages_is_active;

CREATE INDEX IF NOT EXISTS idx_wsm_config_order
    ON public.widget_suggested_messages(widget_config_id, display_order);

-- ── persona_configurations ──
DROP INDEX IF EXISTS idx_persona_configurations_is_active;
DROP INDEX IF EXISTS idx_persona_configurations_persona_name;  -- Covered by UNIQUE

CREATE INDEX IF NOT EXISTS idx_persona_active_id
    ON public.persona_configurations(is_active DESC, id DESC);  -- Skip scan

-- ── widget_configuration ──
DROP INDEX IF EXISTS idx_widget_configuration_display_chatbot;
DROP INDEX IF EXISTS idx_widget_configuration_theme;
-- Singleton table - no indexes needed beyond PK

-- ── session_assignments ──
DROP INDEX IF EXISTS idx_session_assignments_session;
DROP INDEX IF EXISTS idx_session_assignments_user_role_id;
DROP INDEX IF EXISTS idx_session_assignments_status;
DROP INDEX IF EXISTS idx_session_assignments_user_role_id_status;

CREATE INDEX IF NOT EXISTS idx_session_assignments_session
    ON public.session_assignments(session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_status
    ON public.session_assignments(user_role_id, status);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_id
    ON public.session_assignments(status, id DESC);  -- Skip scan

-- ============================================================================
-- PHASE 2: ATOMIC CHANGE TRACKING (RETURNING OLD/NEW)
-- ============================================================================
-- PG18 supports: UPDATE ... RETURNING OLD.col, NEW.col
-- This eliminates read-before-write anti-patterns in application code.
--
-- No schema changes needed - this is application-level.
-- See refactored DAO code for implementation.
--
-- Example pattern (for reference):
--
--   -- BEFORE (2 round-trips):
--   SELECT metadata FROM scraped_websites WHERE id = :id;
--   UPDATE scraped_websites SET metadata = :merged WHERE id = :id;
--
--   -- AFTER (1 atomic trip):
--   UPDATE scraped_websites
--   SET metadata = jsonb_concat(metadata, :new_metadata)
--   WHERE id = :id
--   RETURNING OLD.metadata AS previous_metadata, NEW.metadata AS current_metadata;
--
-- ============================================================================

-- ============================================================================
-- PHASE 5: I/O & CONNECTION TUNING
-- ============================================================================
-- These are postgresql.conf settings. Apply via:
--   ALTER SYSTEM SET <param> = <value>;
--   SELECT pg_reload_conf();
-- ============================================================================

-- PG18 Async I/O - critical for Railway SSD storage
-- io_method = 'worker' enables kernel-level async I/O
DO $$
BEGIN
    -- SSD-optimized cost model
    EXECUTE 'ALTER SYSTEM SET random_page_cost = 1.1';
    -- Async I/O concurrency (200 is good for SSD, adjust for Railway plan)
    EXECUTE 'ALTER SYSTEM SET effective_io_concurrency = 200';
    -- Parallel workers for sequential scans
    EXECUTE 'ALTER SYSTEM SET max_parallel_workers_per_gather = 2';
    -- JIT compilation for complex analytics queries
    EXECUTE 'ALTER SYSTEM SET jit = on';
    -- Memory tuning (adjust for Railway plan - these are conservative defaults)
    EXECUTE 'ALTER SYSTEM SET work_mem = ''16MB''';
    EXECUTE 'ALTER SYSTEM SET maintenance_work_mem = ''128MB''';
    -- Connection tuning for asyncpg
    EXECUTE 'ALTER SYSTEM SET idle_in_transaction_session_timeout = ''60s''';
    -- PG18: Enable streaming read prefetch
    EXECUTE 'ALTER SYSTEM SET effective_cache_size = ''2GB''';

    RAISE NOTICE 'I/O tuning applied. Run: SELECT pg_reload_conf(); to activate.';
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Could not apply ALTER SYSTEM settings (may need superuser): %', SQLERRM;
END $$;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Analyze all tables for fresh statistics after index changes
ANALYZE public.users;
ANALYZE public.roles;
ANALYZE public.user_role_mapping;
ANALYZE public.chat_sessions;
ANALYZE public.chat_messages;
ANALYZE public.file_uploads;
ANALYZE public.scraped_websites;
ANALYZE public.session_assignments;
ANALYZE public.widget_configuration;
ANALYZE public.widget_suggested_messages;
ANALYZE public.token_usage_log;
ANALYZE public.admin_sessions;
ANALYZE public.admin_actions;
ANALYZE public.persona_configurations;
ANALYZE public.security_settings;
ANALYZE public.llm_providers;
ANALYZE public.metrics;
ANALYZE public.notifications;
ANALYZE public.api_usage;
ANALYZE public.service_health_checks;

COMMIT;

-- Reload config for Phase 5 changes
SELECT pg_reload_conf();

RESET statement_timeout;
RESET lock_timeout;

-- ============================================================================
-- POST-MIGRATION VERIFICATION QUERIES
-- ============================================================================
-- Run these after migration to verify everything is working:

-- 1. Verify all PKs are UUID type
SELECT
    c.relname AS table_name,
    a.attname AS pk_column,
    t.typname AS column_type,
    CASE WHEN t.typname = 'uuid' THEN 'OK' ELSE 'NEEDS MIGRATION' END AS status
FROM pg_class c
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_index i ON c.oid = i.indrelid AND i.indisprimary
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
JOIN pg_type t ON a.atttypid = t.oid
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;

-- 2. Verify no orphaned created_at indexes remain
SELECT indexname, tablename
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname LIKE '%created_at%'
ORDER BY tablename;

-- 3. Count indexes per table (should be fewer post-consolidation)
SELECT
    tablename,
    COUNT(*) AS index_count
FROM pg_indexes
WHERE schemaname = 'public'
GROUP BY tablename
ORDER BY index_count DESC;

-- 4. Test UUID v7 ordering
SELECT
    'UUID v7 ordering test' AS test,
    uuidv7() < uuidv7() AS chronological_order_works;
