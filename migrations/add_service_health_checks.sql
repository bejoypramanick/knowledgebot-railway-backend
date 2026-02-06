-- Migration: Add service_health_checks table for health monitoring
-- Created for Phase 1: Health Monitoring Service

CREATE TABLE IF NOT EXISTS service_health_checks (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,  -- 'healthy', 'degraded', 'down'
    response_time_ms INTEGER,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    metadata JSONB
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_service_health_checks_service_checked
    ON service_health_checks(service_name, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_service_health_checks_checked_at
    ON service_health_checks(checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_service_health_checks_status
    ON service_health_checks(status);

-- Create index for recent failures query
CREATE INDEX IF NOT EXISTS idx_service_health_checks_status_checked
    ON service_health_checks(status, checked_at DESC)
    WHERE status != 'healthy';

COMMENT ON TABLE service_health_checks IS 'Tracks health check results for all microservices for monitoring and reporting';
COMMENT ON COLUMN service_health_checks.service_name IS 'Name of the service being monitored (e.g., api_gateway, website_crawling)';
COMMENT ON COLUMN service_health_checks.status IS 'Health status: healthy, degraded, or down';
COMMENT ON COLUMN service_health_checks.response_time_ms IS 'Response time in milliseconds';
COMMENT ON COLUMN service_health_checks.checked_at IS 'Timestamp when the check was performed';
COMMENT ON COLUMN service_health_checks.error_message IS 'Error message if status is not healthy';
COMMENT ON COLUMN service_health_checks.metadata IS 'Additional metadata about the health check (e.g., endpoint, version info)';
