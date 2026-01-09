-- User Unique IDs and Notifications Schema
-- Run this SQL file to add tables for unique ID generation and notification history

-- User Unique IDs table
CREATE TABLE IF NOT EXISTS user_unique_ids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    unique_id VARCHAR(100) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('customer', 'agent', 'admin')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email, role)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_user_unique_ids_email ON user_unique_ids(email);
CREATE INDEX IF NOT EXISTS idx_user_unique_ids_unique_id ON user_unique_ids(unique_id);
CREATE INDEX IF NOT EXISTS idx_user_unique_ids_role ON user_unique_ids(role);

-- Notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'info' CHECK (type IN ('info', 'success', 'warning', 'error')),
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_notifications_user_email ON notifications(user_email);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_email, is_read);

-- Widget Scripts table (for version control and analytics)
CREATE TABLE IF NOT EXISTS widget_scripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_id VARCHAR(255), -- Reference to widget config
    script_content TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    install_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for widget scripts
CREATE INDEX IF NOT EXISTS idx_widget_scripts_config_id ON widget_scripts(config_id);
CREATE INDEX IF NOT EXISTS idx_widget_scripts_is_active ON widget_scripts(is_active);
