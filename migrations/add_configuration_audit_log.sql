-- Create configuration audit log table for tracking configuration changes
CREATE TABLE IF NOT EXISTS configuration_audit_log (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB,
    ip_address INET,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_configuration_audit_log_user_email
ON configuration_audit_log (user_email);

CREATE INDEX IF NOT EXISTS idx_configuration_audit_log_action
ON configuration_audit_log (action);

CREATE INDEX IF NOT EXISTS idx_configuration_audit_log_timestamp
ON configuration_audit_log (timestamp DESC);

-- Add a comment to the table
COMMENT ON TABLE configuration_audit_log IS 'Audit log for tracking all configuration changes made by users';