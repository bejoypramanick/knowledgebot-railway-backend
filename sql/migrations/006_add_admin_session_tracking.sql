-- ============================================
-- Admin Session Tracking and Action Audit System
-- Comprehensive audit trail for admin/agent actions and sessions
--
-- Tables:
-- - admin_sessions: Track admin/agent login sessions with metadata
-- - admin_actions: Complete audit trail of every admin action
--
-- Compliance: Supports GDPR, HIPAA, SOC 2 audit requirements
-- ============================================

-- ============================================
-- TABLE 1: admin_sessions
-- ============================================
-- Tracks admin/agent login sessions with metadata
-- For audit trail and security monitoring
CREATE TABLE admin_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) UNIQUE NOT NULL,
    user_role_id INTEGER NOT NULL,
    email VARCHAR(255) NOT NULL,
    role_name VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    browser VARCHAR(100),
    os VARCHAR(100),
    device_type VARCHAR(50),
    login_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    logout_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    logout_reason VARCHAR(100),
    action_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for admin_sessions
CREATE INDEX idx_admin_sessions_session_id ON admin_sessions(session_id);
CREATE INDEX idx_admin_sessions_user_role_id ON admin_sessions(user_role_id);
CREATE INDEX idx_admin_sessions_email ON admin_sessions(email);
CREATE INDEX idx_admin_sessions_role_name ON admin_sessions(role_name);
CREATE INDEX idx_admin_sessions_login_at ON admin_sessions(login_at DESC);
CREATE INDEX idx_admin_sessions_last_activity_at ON admin_sessions(last_activity_at DESC);
CREATE INDEX idx_admin_sessions_is_active ON admin_sessions(is_active);
CREATE INDEX idx_admin_sessions_email_active ON admin_sessions(email, is_active) WHERE is_active = true;
CREATE INDEX idx_admin_sessions_expires_at ON admin_sessions(expires_at) WHERE is_active = true;

-- Composite indexes for common queries
CREATE INDEX idx_admin_sessions_email_login ON admin_sessions(email, login_at DESC);
CREATE INDEX idx_admin_sessions_active_user ON admin_sessions(user_role_id, is_active);

-- Trigger to auto-update updated_at
CREATE TRIGGER admin_sessions_updated_at
BEFORE UPDATE ON admin_sessions
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- TABLE 2: admin_actions
-- ============================================
-- Complete audit trail of every admin/agent action
CREATE TABLE admin_actions (
    id BIGSERIAL PRIMARY KEY,
    action_id VARCHAR(36) UNIQUE NOT NULL,
    session_id INTEGER NOT NULL,
    user_role_id INTEGER NOT NULL,
    email VARCHAR(255) NOT NULL,
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
    duration_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT true,
    error_message TEXT,
    error_code VARCHAR(50),
    ip_address VARCHAR(45),
    user_agent TEXT,
    correlation_id VARCHAR(36),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for admin_actions
CREATE INDEX idx_admin_actions_action_id ON admin_actions(action_id);
CREATE INDEX idx_admin_actions_session_id ON admin_actions(session_id);
CREATE INDEX idx_admin_actions_user_role_id ON admin_actions(user_role_id);
CREATE INDEX idx_admin_actions_email ON admin_actions(email);
CREATE INDEX idx_admin_actions_action_type ON admin_actions(action_type);
CREATE INDEX idx_admin_actions_action_category ON admin_actions(action_category);
CREATE INDEX idx_admin_actions_created_at ON admin_actions(created_at DESC);
CREATE INDEX idx_admin_actions_success ON admin_actions(success) WHERE success = false;  -- Partial index for errors

-- Composite indexes for common queries
CREATE INDEX idx_admin_actions_email_created ON admin_actions(email, created_at DESC);
CREATE INDEX idx_admin_actions_category_created ON admin_actions(action_category, created_at DESC);
CREATE INDEX idx_admin_actions_category_success ON admin_actions(action_category, success, created_at DESC);
CREATE INDEX idx_admin_actions_email_category ON admin_actions(email, action_category, created_at DESC);

-- Foreign key constraint (commented out - add after ensuring admin_sessions exists)
-- ALTER TABLE admin_actions
-- ADD CONSTRAINT fk_admin_actions_session_id
-- FOREIGN KEY (session_id) REFERENCES admin_sessions(id) ON DELETE CASCADE;

-- ============================================
-- VIEWS FOR ANALYTICS
-- ============================================
-- Session analytics view
CREATE VIEW admin_sessions_analytics AS
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

-- Action statistics view
CREATE VIEW admin_actions_analytics AS
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

-- ============================================
-- CONSTRAINTS
-- ============================================
-- Ensure email is not empty
ALTER TABLE admin_sessions ADD CONSTRAINT admin_sessions_email_not_empty CHECK (email != '');
ALTER TABLE admin_actions ADD CONSTRAINT admin_actions_email_not_empty CHECK (email != '');

-- Ensure session_id and action_id are valid UUIDs (simple format check)
ALTER TABLE admin_sessions ADD CONSTRAINT admin_sessions_session_id_format
  CHECK (session_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');

ALTER TABLE admin_actions ADD CONSTRAINT admin_actions_action_id_format
  CHECK (action_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$');

-- Ensure logout_at >= login_at if set
ALTER TABLE admin_sessions ADD CONSTRAINT admin_sessions_logout_after_login
  CHECK (logout_at IS NULL OR logout_at >= login_at);

-- Ensure expires_at is in future
ALTER TABLE admin_sessions ADD CONSTRAINT admin_sessions_expires_in_future
  CHECK (expires_at > login_at);

-- Ensure duration_ms is non-negative
ALTER TABLE admin_actions ADD CONSTRAINT admin_actions_duration_non_negative
  CHECK (duration_ms IS NULL OR duration_ms >= 0);

-- ============================================
-- TABLE AND COLUMN COMMENTS
-- ============================================
COMMENT ON TABLE admin_sessions IS
  'Tracks admin/agent login sessions with metadata for audit trail and security monitoring';

COMMENT ON TABLE admin_actions IS
  'Complete audit trail of every admin/agent action for compliance and security';

COMMENT ON COLUMN admin_sessions.session_id IS
  'UUID for OTEL logging context - unique identifier for this session';

COMMENT ON COLUMN admin_sessions.expires_at IS
  'When the session expires (from JWT exp claim)';

COMMENT ON COLUMN admin_sessions.action_count IS
  'Number of actions performed in this session - incremented asynchronously';

COMMENT ON COLUMN admin_actions.action_id IS
  'UUID for action correlation with OTEL traces';

COMMENT ON COLUMN admin_actions.action_type IS
  'Hierarchical action identifier: category.resource.operation (e.g., config.chatbot.update)';

COMMENT ON COLUMN admin_actions.correlation_id IS
  'OTEL trace ID for correlating with distributed tracing';

COMMENT ON COLUMN admin_actions.duration_ms IS
  'Execution time in milliseconds - used for performance monitoring';
