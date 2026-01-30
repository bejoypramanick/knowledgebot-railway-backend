-- Migration: Fix missing columns and tables
-- Fixes issues found in production logs

-- Add missing status column to human_agents table
ALTER TABLE public.human_agents 
ADD COLUMN IF NOT EXISTS status varchar(20) DEFAULT 'active' NULL;

-- Add missing user_id column to token_usage_log table  
ALTER TABLE public.token_usage_log 
ADD COLUMN IF NOT EXISTS user_id uuid NULL;

-- Add missing agent_email column to agent_session_assignments table
ALTER TABLE public.agent_session_assignments 
ADD COLUMN IF NOT EXISTS agent_email varchar(255) NULL;

-- Create suggested_messages table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.suggested_messages (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    message_text text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT suggested_messages_pkey PRIMARY KEY (id)
);

-- Add missing columns to widget_configuration table if they don't exist
ALTER TABLE public.widget_configuration 
ADD COLUMN IF NOT EXISTS auto_show_duration integer DEFAULT 30 NULL,
ADD COLUMN IF NOT EXISTS keep_showing_suggested boolean DEFAULT true NULL,
ADD COLUMN IF NOT EXISTS theme varchar(50) DEFAULT 'light' NULL,
ADD COLUMN IF NOT EXISTS primary_color varchar(7) DEFAULT '#007bff' NULL,
ADD COLUMN IF NOT EXISTS use_primary_for_header boolean DEFAULT true NULL,
ADD COLUMN IF NOT EXISTS chat_bubble_color varchar(7) DEFAULT '#007bff' NULL,
ADD COLUMN IF NOT EXISTS align_bubble varchar(10) DEFAULT 'right' NULL,
ADD COLUMN IF NOT EXISTS display_chatbot boolean DEFAULT true NULL,
ADD COLUMN IF NOT EXISTS profile_picture_url text NULL,
ADD COLUMN IF NOT EXISTS chat_icon_url text NULL,
ADD COLUMN IF NOT EXISTS profile_picture_filename varchar(255) NULL,
ADD COLUMN IF NOT EXISTS chat_icon_filename varchar(255) NULL,
ADD COLUMN IF NOT EXISTS profile_zoom numeric(3,2) DEFAULT 1.0 NULL,
ADD COLUMN IF NOT EXISTS chat_icon_zoom numeric(3,2) DEFAULT 1.0 NULL,
ADD COLUMN IF NOT EXISTS profile_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL,
ADD COLUMN IF NOT EXISTS chat_icon_position jsonb DEFAULT '{"x": 0, "y": 0}'::jsonb NULL;

-- Insert default suggested messages if table is empty
INSERT INTO public.suggested_messages (message_text, sort_order)
VALUES 
    ('How can I help you today?', 1),
    ('What would you like to know?', 2),
    ('Tell me more about your needs.', 3)
ON CONFLICT DO NOTHING;

-- Add index for performance
CREATE INDEX IF NOT EXISTS idx_human_agents_status ON public.human_agents USING btree (status);
CREATE INDEX IF NOT EXISTS idx_token_usage_log_user_id ON public.token_usage_log USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_agent_session_assignments_agent_email ON public.agent_session_assignments USING btree (agent_email);

-- Add constraints for human_agents status
ALTER TABLE public.human_agents 
ADD CONSTRAINT IF NOT EXISTS human_agents_status_check 
CHECK (status IN ('active', 'inactive', 'removed'));

COMMIT;
