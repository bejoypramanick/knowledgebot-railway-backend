SET statement_timeout = '300s';
SET lock_timeout = '30s';

ALTER TABLE users ALTER COLUMN email SET COMPRESSION pglz;
ALTER TABLE roles ALTER COLUMN role_description SET COMPRESSION pglz;
ALTER TABLE chat_sessions ALTER COLUMN conversation_summary SET COMPRESSION pglz;
ALTER TABLE chat_sessions ALTER COLUMN metadata SET COMPRESSION pglz;
ALTER TABLE chat_messages ALTER COLUMN content SET COMPRESSION pglz;
ALTER TABLE chat_messages ALTER COLUMN sources SET COMPRESSION pglz;
ALTER TABLE file_uploads ALTER COLUMN gemini_file_uri SET COMPRESSION pglz;
ALTER TABLE file_uploads ALTER COLUMN s3_key SET COMPRESSION pglz;
ALTER TABLE file_uploads ALTER COLUMN processed_content_s3_key SET COMPRESSION pglz;
ALTER TABLE file_uploads ALTER COLUMN error_message SET COMPRESSION pglz;
ALTER TABLE file_uploads ALTER COLUMN metadata SET COMPRESSION pglz;
ALTER TABLE scraped_websites ALTER COLUMN original_url SET COMPRESSION pglz;
ALTER TABLE scraped_websites ALTER COLUMN description SET COMPRESSION pglz;
ALTER TABLE scraped_websites ALTER COLUMN error_message SET COMPRESSION pglz;
ALTER TABLE scraped_websites ALTER COLUMN metadata SET COMPRESSION pglz;
ALTER TABLE persona_configurations ALTER COLUMN system_prompt SET COMPRESSION pglz;
ALTER TABLE widget_configuration ALTER COLUMN profile_picture_url SET COMPRESSION pglz;
ALTER TABLE widget_suggested_messages ALTER COLUMN message_text SET COMPRESSION pglz;
ALTER TABLE security_settings ALTER COLUMN setting_value SET COMPRESSION pglz;
ALTER TABLE api_usage ALTER COLUMN request_metadata SET COMPRESSION pglz;
ALTER TABLE api_usage ALTER COLUMN metadata SET COMPRESSION pglz;
ALTER TABLE token_usage_log ALTER COLUMN request_metadata SET COMPRESSION pglz;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'users' AND column_name = 'email_domain') THEN
    ALTER TABLE users ADD COLUMN email_domain varchar(255)
      GENERATED ALWAYS AS (substring(email from position('@' in email) + 1)) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'chat_sessions' AND column_name = 'sentiment_score') THEN
    ALTER TABLE chat_sessions ADD COLUMN sentiment_score int
      GENERATED ALWAYS AS (
        CASE WHEN sentiment='positive' THEN 1
        WHEN sentiment='negative' THEN -1
        ELSE 0 END
      ) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'chat_messages' AND column_name = 'quality_score') THEN
    ALTER TABLE chat_messages ADD COLUMN quality_score int
      GENERATED ALWAYS AS (
        CASE WHEN used_rag THEN 10 + (confidence_score*10)::int
        ELSE (confidence_score*5)::int
        END
      ) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'chat_messages' AND column_name = 'source_count') THEN
    ALTER TABLE chat_messages ADD COLUMN source_count int
      GENERATED ALWAYS AS (jsonb_array_length(sources)) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'file_uploads' AND column_name = 'file_category') THEN
    ALTER TABLE file_uploads ADD COLUMN file_category varchar(50)
      GENERATED ALWAYS AS (
        CASE
          WHEN file_extension IN ('pdf','docx','xlsx','pptx','txt','doc','xls','odt') THEN 'document'
          WHEN file_extension IN ('jpg','png','gif','svg','webp','bmp','tiff') THEN 'image'
          WHEN file_extension IN ('mp4','mov','avi','mkv','webm','flv') THEN 'video'
          WHEN file_extension IN ('mp3','wav','m4a','flac','ogg','aac') THEN 'audio'
          ELSE 'other'
        END
      ) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'file_uploads' AND column_name = 'is_successful') THEN
    ALTER TABLE file_uploads ADD COLUMN is_successful boolean
      GENERATED ALWAYS AS (processing_status = 'completed') VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'scraped_websites' AND column_name = 'url_domain') THEN
    ALTER TABLE scraped_websites ADD COLUMN url_domain varchar(500)
      GENERATED ALWAYS AS (substring(original_url from '://([^/?#]+)')) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'llm_providers' AND column_name = 'token_utilization_percent') THEN
    ALTER TABLE llm_providers ADD COLUMN token_utilization_percent numeric(5,2)
      GENERATED ALWAYS AS (
        CASE WHEN token_limit = 0 THEN 0
        ELSE ROUND((token_used::numeric / token_limit) * 100, 2)
        END
      ) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'api_usage' AND column_name = 'token_cost_cents') THEN
    ALTER TABLE api_usage ADD COLUMN token_cost_cents int
      GENERATED ALWAYS AS ((tokens_input * 3 + tokens_output * 12)) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'api_usage' AND column_name = 'total_request_response_bytes') THEN
    ALTER TABLE api_usage ADD COLUMN total_request_response_bytes int
      GENERATED ALWAYS AS (COALESCE(request_size_bytes, 0) + COALESCE(response_size_bytes, 0)) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'token_usage_log' AND column_name = 'model_provider_key') THEN
    ALTER TABLE token_usage_log ADD COLUMN model_provider_key varchar(200)
      GENERATED ALWAYS AS (provider || ':' || COALESCE(model, 'unknown')) VIRTUAL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'token_usage_log' AND column_name = 'calculated_cost_cents') THEN
    ALTER TABLE token_usage_log ADD COLUMN calculated_cost_cents int
      GENERATED ALWAYS AS (ROUND((prompt_tokens * 0.003 + completion_tokens * 0.006)::numeric)::int) VIRTUAL;
  END IF;
END $$;

DROP INDEX IF EXISTS idx_users_email;
DROP INDEX IF EXISTS idx_users_email_covering;
CREATE INDEX idx_users_email_covering ON users(email)
  INCLUDE (is_active, last_login_at, created_at);
DROP INDEX IF EXISTS idx_users_active;
CREATE INDEX idx_users_active ON users(created_at DESC)
  WHERE is_active = true;
DROP INDEX IF EXISTS idx_users_email_active;
CREATE INDEX idx_users_email_active ON users(email, is_active);

DROP INDEX IF EXISTS idx_roles_description_fts;
CREATE INDEX idx_roles_description_fts ON roles
  USING gin(to_tsvector('english', COALESCE(role_description, '')))
  WHERE role_description IS NOT NULL;

DROP INDEX IF EXISTS idx_user_role_mapping_user_id;
DROP INDEX IF EXISTS idx_user_role_mapping_user_covering;
CREATE INDEX idx_user_role_mapping_user_covering ON user_role_mapping(user_id)
  INCLUDE (role_id, is_active, created_at);
DROP INDEX IF EXISTS idx_user_role_mapping_role_id;
DROP INDEX IF EXISTS idx_user_role_mapping_role_covering;
CREATE INDEX idx_user_role_mapping_role_covering ON user_role_mapping(role_id)
  INCLUDE (user_id, is_active);
DROP INDEX IF EXISTS idx_user_role_mapping_active;
CREATE INDEX idx_user_role_mapping_active ON user_role_mapping(user_id, is_active)
  WHERE is_active = true;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.table_constraints
             WHERE table_name = 'user_role_mapping' AND constraint_name = 'user_role_mapping_user_role_key') THEN
    ALTER TABLE user_role_mapping DROP CONSTRAINT user_role_mapping_user_role_key;
  END IF;
END $$;

ALTER TABLE user_role_mapping ADD CONSTRAINT user_role_mapping_user_role_key
  UNIQUE NULLS NOT DISTINCT (user_id, role_id);

DROP INDEX IF EXISTS idx_chat_sessions_archive_status;
DROP INDEX IF EXISTS idx_chat_sessions_archive_status_covering;
CREATE INDEX idx_chat_sessions_archive_status_covering ON chat_sessions(archive_status)
  INCLUDE (updated_at, is_active, message_count, user_role_id);
DROP INDEX IF EXISTS idx_chat_sessions_active_recent;
CREATE INDEX idx_chat_sessions_active_recent ON chat_sessions(created_at DESC)
  WHERE is_active = true AND archive_status = 'active';
DROP INDEX IF EXISTS idx_chat_sessions_sentiment_analysis;
CREATE INDEX idx_chat_sessions_sentiment_analysis ON chat_sessions(sentiment, created_at DESC)
  WHERE sentiment IS NOT NULL;
DROP INDEX IF EXISTS idx_chat_sessions_feedback_analysis;
CREATE INDEX idx_chat_sessions_feedback_analysis ON chat_sessions(user_role_id, feedback_type, feedback_provided_at DESC)
  INCLUDE (feedback_type, created_at)
  WHERE feedback_type IS NOT NULL;
DROP INDEX IF EXISTS idx_chat_sessions_archive_activity;
CREATE INDEX idx_chat_sessions_archive_activity ON chat_sessions(archive_status, last_activity_at DESC)
  INCLUDE (is_active, message_count)
  WHERE is_active = true;
DROP INDEX IF EXISTS idx_chat_sessions_metadata_model;
CREATE INDEX idx_chat_sessions_metadata_model ON chat_sessions((metadata->>'model'))
  INCLUDE (created_at, user_role_id)
  WHERE metadata->>'model' IS NOT NULL;

DROP INDEX IF EXISTS idx_chat_messages_content_fts;
CREATE INDEX idx_chat_messages_content_fts ON chat_messages
  USING gin(to_tsvector('english', content));
DROP INDEX IF EXISTS idx_chat_messages_session_unread;
DROP INDEX IF EXISTS idx_chat_messages_unread_covering;
CREATE INDEX idx_chat_messages_unread_covering ON chat_messages(session_id, is_message_read)
  INCLUDE (role, created_at, content)
  WHERE is_message_read = false;
DROP INDEX IF EXISTS idx_chat_messages_session_ordered;
CREATE INDEX idx_chat_messages_session_ordered ON chat_messages(session_id, created_at DESC)
  INCLUDE (role, used_rag, confidence_score);
DROP INDEX IF EXISTS idx_chat_messages_rag_analysis;
CREATE INDEX idx_chat_messages_rag_analysis ON chat_messages(session_id, used_rag, created_at DESC)
  INCLUDE (confidence_score);
DROP INDEX IF EXISTS idx_chat_messages_low_confidence;
CREATE INDEX idx_chat_messages_low_confidence ON chat_messages(session_id, confidence_score)
  WHERE confidence_score < 0.75 AND used_rag = true;
DROP INDEX IF EXISTS idx_chat_messages_role_session;
CREATE INDEX idx_chat_messages_role_session ON chat_messages(role, created_at DESC)
  INCLUDE (session_id, used_rag);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'session_assignments' AND column_name = 'assigned_at'
             AND data_type IN ('timestamp without time zone', 'timestamp')) THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'session_assignments' AND column_name = 'assigned_at'
                   AND data_type = 'timestamp with time zone') THEN
      ALTER TABLE session_assignments
        ALTER COLUMN assigned_at TYPE timestamptz USING assigned_at AT TIME ZONE 'UTC',
        ALTER COLUMN ended_at TYPE timestamptz USING ended_at AT TIME ZONE 'UTC',
        ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'UTC';
    END IF;
  END IF;
END $$;

DROP INDEX IF EXISTS idx_session_assignments_status;
DROP INDEX IF EXISTS idx_session_assignments_status_covering;
CREATE INDEX idx_session_assignments_status_covering ON session_assignments(status)
  INCLUDE (session_id, user_role_id, assigned_at DESC);
DROP INDEX IF EXISTS idx_session_assignments_active;
CREATE INDEX idx_session_assignments_active ON session_assignments(user_role_id, assigned_at DESC)
  WHERE status IN ('active', 'waiting');
DROP INDEX IF EXISTS idx_session_assignments_agent_workload;
CREATE INDEX idx_session_assignments_agent_workload ON session_assignments(user_role_id, status, assigned_at DESC);
DROP INDEX IF EXISTS idx_session_assignments_transferred;
CREATE INDEX idx_session_assignments_transferred ON session_assignments(user_role_id, assigned_at DESC)
  WHERE status = 'transferred';

DROP INDEX IF EXISTS idx_file_uploads_processing_pending;
DROP INDEX IF EXISTS idx_file_uploads_processing_active;
CREATE INDEX idx_file_uploads_processing_active ON file_uploads(processing_status, created_at DESC)
  INCLUDE (display_name, user_role_id, file_category)
  WHERE processing_status IN ('pending', 'processing');
DROP INDEX IF EXISTS idx_file_uploads_completed_lookup;
CREATE INDEX idx_file_uploads_completed_lookup ON file_uploads(gemini_file_name)
  INCLUDE (display_name, processed_content_s3_key, file_size, file_category)
  WHERE processing_status = 'completed';
DROP INDEX IF EXISTS idx_file_uploads_user_files;
CREATE INDEX idx_file_uploads_user_files ON file_uploads(user_role_id, processing_status, created_at DESC)
  INCLUDE (display_name, file_size, file_category);
DROP INDEX IF EXISTS idx_file_uploads_docling_perf;
CREATE INDEX idx_file_uploads_docling_perf ON file_uploads(docling_processing_time_ms DESC)
  INCLUDE (docling_images_extracted, docling_images_with_ocr, processed_by_docling)
  WHERE processed_by_docling = true AND docling_processing_time_ms > 0;
DROP INDEX IF EXISTS idx_file_uploads_gemini_sync;
CREATE INDEX idx_file_uploads_gemini_sync ON file_uploads(gemini_state, created_at DESC)
  INCLUDE (gemini_file_uri, s3_key, gemini_file_name)
  WHERE gemini_state != 'completed';
DROP INDEX IF EXISTS idx_file_uploads_failed;
CREATE INDEX idx_file_uploads_failed ON file_uploads(created_at DESC)
  INCLUDE (error_message, processing_status, display_name)
  WHERE processing_status = 'failed';
DROP INDEX IF EXISTS idx_file_uploads_s3_processed;
CREATE INDEX idx_file_uploads_s3_processed ON file_uploads(processed_content_s3_key)
  INCLUDE (display_name, created_at, char_count)
  WHERE processed_content_s3_key IS NOT NULL;

DROP INDEX IF EXISTS idx_scraped_websites_parent_id;
DROP INDEX IF EXISTS idx_scraped_websites_parent_hierarchy;
CREATE INDEX idx_scraped_websites_parent_hierarchy ON scraped_websites(parent_id, created_at DESC)
  INCLUDE (processing_status, depth, pages_scraped, is_root_page)
  WHERE parent_id IS NOT NULL;
DROP INDEX IF EXISTS idx_scraped_websites_processing_pending;
DROP INDEX IF EXISTS idx_scraped_websites_processing_active;
CREATE INDEX idx_scraped_websites_processing_active ON scraped_websites(processing_status, created_at DESC)
  INCLUDE (domain, pages_scraped, file_size)
  WHERE processing_status IN ('pending', 'processing');
DROP INDEX IF EXISTS idx_scraped_websites_domain_processed;
CREATE INDEX idx_scraped_websites_domain_processed ON scraped_websites(domain, processing_status, created_at DESC)
  INCLUDE (pages_scraped, file_size);
DROP INDEX IF EXISTS idx_scraped_websites_domain_content;
CREATE INDEX idx_scraped_websites_domain_content ON scraped_websites(domain)
  INCLUDE (title, pages_scraped, char_count)
  WHERE processing_status = 'completed';
DROP INDEX IF EXISTS idx_scraped_websites_session_hierarchy;
CREATE INDEX idx_scraped_websites_session_hierarchy ON scraped_websites(crawl_session_id, parent_id, created_at DESC)
  INCLUDE (processing_status, depth, pages_scraped);
DROP INDEX IF EXISTS idx_scraped_websites_metadata_retry;
CREATE INDEX idx_scraped_websites_metadata_retry ON scraped_websites((metadata->>'retry_count'))
  INCLUDE (domain, processing_status)
  WHERE metadata->>'retry_count' IS NOT NULL AND processing_status = 'failed';
DROP INDEX IF EXISTS idx_scraped_websites_metadata_source;
CREATE INDEX idx_scraped_websites_metadata_source ON scraped_websites((metadata->>'source_type'), processing_status)
  INCLUDE (domain, created_at)
  WHERE metadata->>'source_type' IS NOT NULL;
DROP INDEX IF EXISTS idx_scraped_websites_url_lookup;
CREATE INDEX idx_scraped_websites_url_lookup ON scraped_websites(original_url, processing_status, created_at DESC)
  INCLUDE (title, domain)
  WHERE processing_status != 'deleted';
DROP INDEX IF EXISTS idx_scraped_websites_failed_analysis;
CREATE INDEX idx_scraped_websites_failed_analysis ON scraped_websites(created_at DESC)
  INCLUDE (error_message, celery_task_id, domain, processing_status)
  WHERE processing_status = 'failed';
DROP INDEX IF EXISTS idx_scraped_websites_large_content;
CREATE INDEX idx_scraped_websites_large_content ON scraped_websites(file_size DESC, created_at)
  WHERE file_size > 1000000;

DROP INDEX IF EXISTS idx_persona_description_fts;
CREATE INDEX idx_persona_description_fts ON persona_configurations
  USING gin(to_tsvector('english', COALESCE(persona_description, '')))
  WHERE persona_description IS NOT NULL;
DROP INDEX IF EXISTS idx_persona_prompt_fts;
CREATE INDEX idx_persona_prompt_fts ON persona_configurations
  USING gin(to_tsvector('english', system_prompt));
DROP INDEX IF EXISTS idx_persona_active_info;
CREATE INDEX idx_persona_active_info ON persona_configurations(is_active, persona_name)
  INCLUDE (system_prompt, persona_description)
  WHERE is_active = true;

DROP INDEX IF EXISTS idx_widget_display_config;
CREATE INDEX idx_widget_display_config ON widget_configuration(display_chatbot)
  INCLUDE (hil_enabled, response_policy, display_name, theme)
  WHERE display_chatbot = true;
DROP INDEX IF EXISTS idx_widget_theme_config;
CREATE INDEX idx_widget_theme_config ON widget_configuration(theme)
  INCLUDE (primary_color, chat_bubble_color, display_chatbot);

DROP INDEX IF EXISTS idx_widget_suggested_messages_config_id;
DROP INDEX IF EXISTS idx_widget_messages_config_active;
CREATE INDEX idx_widget_messages_config_active ON widget_suggested_messages(widget_config_id, is_active, display_order)
  INCLUDE (message_text);
DROP INDEX IF EXISTS idx_widget_suggested_messages_display_order;
DROP INDEX IF EXISTS idx_widget_messages_config_order;
CREATE INDEX idx_widget_messages_config_order ON widget_suggested_messages(widget_config_id, display_order)
  INCLUDE (message_text, is_active);
DROP INDEX IF EXISTS idx_widget_suggested_messages_is_active;
DROP INDEX IF EXISTS idx_widget_messages_active;
CREATE INDEX idx_widget_messages_active ON widget_suggested_messages(widget_config_id)
  WHERE is_active = true;

DROP INDEX IF EXISTS idx_security_settings_type;
CREATE INDEX idx_security_settings_type ON security_settings(setting_type)
  INCLUDE (setting_name, setting_value);
DROP INDEX IF EXISTS idx_security_settings_lookup;
CREATE INDEX idx_security_settings_lookup ON security_settings(setting_name)
  INCLUDE (setting_value, setting_type);

DROP INDEX IF EXISTS idx_llm_providers_provider_name;
DROP INDEX IF EXISTS idx_llm_providers_lookup;
CREATE INDEX idx_llm_providers_lookup ON llm_providers(provider_name)
  INCLUDE (is_active, token_limit, token_used, token_remaining);
DROP INDEX IF EXISTS idx_llm_providers_critical;
CREATE INDEX idx_llm_providers_critical ON llm_providers(provider_name)
  WHERE token_remaining < 100000 AND is_active = true;

DROP INDEX IF EXISTS idx_api_usage_provider;
DROP INDEX IF EXISTS idx_api_usage_provider_activity;
CREATE INDEX idx_api_usage_provider_activity ON api_usage(api_provider, created_at DESC)
  INCLUDE (http_method, tokens_input, tokens_output, user_email);
DROP INDEX IF EXISTS idx_api_usage_endpoint;
DROP INDEX IF EXISTS idx_api_usage_endpoint_perf;
CREATE INDEX idx_api_usage_endpoint_perf ON api_usage(api_endpoint, http_method, created_at DESC)
  INCLUDE (response_size_bytes, tokens_output);
DROP INDEX IF EXISTS idx_api_usage_user_email;
DROP INDEX IF EXISTS idx_api_usage_user_activity;
CREATE INDEX idx_api_usage_user_activity ON api_usage(user_email, created_at DESC)
  INCLUDE (api_provider, api_endpoint, tokens_input, tokens_output);
DROP INDEX IF EXISTS idx_api_usage_recent_activity;
CREATE INDEX idx_api_usage_recent_activity ON api_usage(api_provider, created_at DESC)
  INCLUDE (tokens_input, tokens_output)
  WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '7 days';

DROP INDEX IF EXISTS idx_token_usage_log_session_id;
DROP INDEX IF EXISTS idx_token_usage_session_spend;
CREATE INDEX idx_token_usage_session_spend ON token_usage_log(session_id, created_at DESC)
  INCLUDE (total_tokens, cost_cents, provider, model)
  WHERE session_id IS NOT NULL;
DROP INDEX IF EXISTS idx_token_usage_log_provider;
DROP INDEX IF EXISTS idx_token_usage_provider_metrics;
CREATE INDEX idx_token_usage_provider_metrics ON token_usage_log(provider, created_at DESC)
  INCLUDE (model, prompt_tokens, completion_tokens, cost_cents, api_call_type);
DROP INDEX IF EXISTS idx_token_usage_model_analysis;
CREATE INDEX idx_token_usage_model_analysis ON token_usage_log(provider, model, created_at DESC)
  INCLUDE (prompt_tokens, completion_tokens, cost_cents, total_tokens);
DROP INDEX IF EXISTS idx_token_usage_message_tracking;
CREATE INDEX idx_token_usage_message_tracking ON token_usage_log(message_id, created_at DESC)
  INCLUDE (provider, total_tokens, cost_cents, api_call_type)
  WHERE message_id IS NOT NULL;
DROP INDEX IF EXISTS idx_token_usage_recent;
CREATE INDEX idx_token_usage_recent ON token_usage_log(provider, created_at DESC)
  INCLUDE (model, total_tokens, cost_cents)
  WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '7 days';

DROP INDEX IF EXISTS idx_metrics_type;
DROP INDEX IF EXISTS idx_metrics_type_covering;
CREATE INDEX idx_metrics_type_covering ON metrics(metric_type, created_at DESC)
  INCLUDE (metric_name, metric_value);
DROP INDEX IF EXISTS idx_metrics_name;
DROP INDEX IF EXISTS idx_metrics_name_covering;
CREATE INDEX idx_metrics_name_covering ON metrics(metric_name, created_at DESC)
  INCLUDE (metric_type, metric_value);

DROP INDEX IF EXISTS idx_notifications_user_email;
DROP INDEX IF EXISTS idx_notifications_user_covering;
CREATE INDEX idx_notifications_user_covering ON notifications(user_email, created_at DESC)
  INCLUDE (is_read, notification_type, message);
DROP INDEX IF EXISTS idx_notifications_is_read;
DROP INDEX IF EXISTS idx_notifications_unread;
CREATE INDEX idx_notifications_unread ON notifications(user_email)
  WHERE is_read = false;
DROP INDEX IF EXISTS idx_notifications_user_read;
DROP INDEX IF EXISTS idx_notifications_user_status;
CREATE INDEX idx_notifications_user_status ON notifications(user_email, is_read, created_at DESC);
