-- Updated Master migration script to run only missing migrations
-- Execute this script to apply only the tables that don't exist in the main schema

-- Note: This script should be run with psql using the -f flag
-- The \i commands below are psql meta-commands

-- Migration 001: Add missing columns to existing tables
-- Run this first: psql $DATABASE_URL -f sql/migrations/001_add_admins_status_column.sql

-- Migration 002: Create chatbot_personas table (missing from main schema)  
-- Run this second: psql $DATABASE_URL -f sql/migrations/002_create_chatbot_personas_table.sql

-- Migration 003: Create agent_session_assignments table (missing from main schema)
-- Run this third: psql $DATABASE_URL -f sql/migrations/003_create_agent_session_assignments_table.sql

-- For convenience, here are the individual migration commands:
/*
-- Migration 001: Add missing status column to admins table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='admins' AND column_name='status' AND table_schema='public'
    ) THEN
        ALTER TABLE public.admins ADD COLUMN status varchar(50) DEFAULT 'active' NOT NULL;
    END IF;
END $$;

-- Add constraint for status column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'admins_status_check'
    ) THEN
        ALTER TABLE public.admins 
        ADD CONSTRAINT admins_status_check 
        CHECK (status IN ('active', 'inactive', 'removed'));
    END IF;
END $$;

-- Create index for status column
CREATE INDEX IF NOT EXISTS idx_admins_status ON public.admins USING btree (status);

-- Update existing records to have active status
UPDATE public.admins SET status = 'active' WHERE status IS NULL;

-- Add comments
COMMENT ON COLUMN public.admins.status IS 'Admin status: active (can access), inactive (suspended), removed (deleted)';

-- Migration 002: Create chatbot_personas table
CREATE TABLE IF NOT EXISTS public.chatbot_personas (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    persona_name varchar(100) NOT NULL,
    persona_description text NULL,
    system_prompt text NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    updated_at timestamp DEFAULT now() NULL,
    created_by_email varchar(255) NULL,
    CONSTRAINT chatbot_personas_pkey PRIMARY KEY (id),
    CONSTRAINT chatbot_personas_persona_name_unique UNIQUE (persona_name),
    CONSTRAINT valid_persona_name CHECK ((persona_name)::text ~* '^[A-Za-z0-9._%+-]+$'::text)
);

-- Create indexes for chatbot_personas
CREATE INDEX IF NOT EXISTS idx_chatbot_personas_active ON public.chatbot_personas USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_chatbot_personas_name ON public.chatbot_personas USING btree (persona_name);

-- Insert default persona
INSERT INTO public.chatbot_personas (persona_name, persona_description, system_prompt, is_active, created_by_email)
VALUES (
    'KnowledgeBot',
    'A helpful AI assistant specialized in knowledge management and answering questions based on available documents and conversations.',
    'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.',
    true,
    'system@knowledgebot.com'
) ON CONFLICT (persona_name) DO NOTHING;

-- Migration 003: Create agent_session_assignments table
CREATE TABLE IF NOT EXISTS public.agent_session_assignments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    assigned_at timestamp DEFAULT now() NULL,
    status varchar(50) DEFAULT 'active' NOT NULL,
    assigned_by_email varchar(255) NULL,
    ended_at timestamp NULL,
    CONSTRAINT agent_session_assignments_pkey PRIMARY KEY (id),
    CONSTRAINT valid_assignment_status CHECK (status IN ('waiting', 'active', 'transferred', 'ended')),
    CONSTRAINT agent_session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    CONSTRAINT agent_session_assignments_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.human_agents(id) ON DELETE CASCADE
);

-- Create indexes for agent_session_assignments
CREATE INDEX IF NOT EXISTS idx_session_assignments_session_id ON public.agent_session_assignments USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_agent_id ON public.agent_session_assignments USING btree (agent_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status ON public.agent_session_assignments USING btree (status);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_updated ON public.agent_session_assignments USING btree (status, assigned_at DESC);
*/

-- Verify all tables were created successfully
SELECT 
    table_name,
    table_type
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'chatbot_personas',
        'agent_session_assignments'
    )
ORDER BY table_name;

-- Insert default personas into chatbot_personas table
INSERT INTO chatbot_personas (persona_name, persona_description, system_prompt, is_active, created_at, updated_at) VALUES
(
    'KnowledgeBot',
    'A helpful AI assistant for knowledge management',
    'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.',
    true,
    NOW(),
    NOW()
),
(
    'Friendly-Receptionist',
    'A warm and welcoming receptionist persona',
    'You are a friendly receptionist who welcomes visitors and helps them navigate. Your tone should be warm, welcoming, and professional. Always greet users with a smile in your voice and be ready to assist with any questions or direct them to the right resources.',
    false,
    NOW(),
    NOW()
),
(
    'Technical-Support',
    'A technical support specialist for IT and development issues',
    'You are a technical support specialist with deep knowledge of IT systems, programming, and development. Provide detailed, accurate technical solutions. Be thorough in your explanations and always consider best practices and security implications.',
    false,
    NOW(),
    NOW()
),
(
    'Customer-Service',
    'A customer service representative focused on customer satisfaction',
    'You are a customer service representative dedicated to ensuring customer satisfaction. Be empathetic, patient, and solution-oriented. Always listen carefully to customer concerns and provide clear, helpful responses that address their needs.',
    false,
    NOW(),
    NOW()
),
(
    'Research-Assistant',
    'A research assistant for academic and professional research',
    'You are a research assistant skilled in finding and synthesizing information from various sources. Be methodical, thorough, and analytical. Always cite sources when possible and present information in a structured, academic manner.',
    false,
    NOW(),
    NOW()
),
(
    'Business-Analyst',
    'A business analyst for strategic insights and analysis',
    'You are a business analyst who provides strategic insights and data-driven analysis. Be analytical, detail-oriented, and focused on business outcomes. Always consider the broader business context and provide actionable recommendations.',
    false,
    NOW(),
    NOW()
),
(
    'Creative-Writing-Assistant',
    'A creative writing assistant for storytelling and content creation',
    'You are a creative writing assistant who helps with storytelling, content creation, and creative projects. Be imaginative, inspiring, and supportive of creative expression. Always encourage creativity while providing constructive feedback.',
    false,
    NOW(),
    NOW()
),
(
    'Language-Tutor',
    'A language tutor for learning and practicing different languages',
    'You are a language tutor who helps users learn and practice different languages. Be patient, encouraging, and educational. Always provide clear explanations, correct mistakes gently, and adapt to the user''s learning pace.',
    false,
    NOW(),
    NOW()
),
(
    'Health-Advisor',
    'A health and wellness advisor for general health guidance',
    'You are a health and wellness advisor who provides general health guidance and wellness tips. Always emphasize that you are not a medical professional and encourage users to consult healthcare providers for specific medical concerns. Be supportive, informative, and focused on preventive health.',
    false,
    NOW(),
    NOW()
),
(
    'Finance-Assistant',
    'A financial assistant for general financial guidance and education',
    'You are a financial assistant who provides general financial guidance and education. Always clarify that you are not a financial advisor and recommend consulting qualified professionals for specific financial advice. Be educational, objective, and focused on financial literacy.',
    false,
    NOW(),
    NOW()
)
ON CONFLICT (persona_name) DO NOTHING;

-- Verify personas were inserted
SELECT 
    persona_name,
    persona_description,
    is_active,
    created_at
FROM chatbot_personas 
ORDER BY persona_name;

-- Verify columns were added to existing tables
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_schema = 'public' 
    AND table_name = 'admins' 
    AND column_name = 'status';

-- Check what tables already exist in the main schema
SELECT 
    table_name,
    'EXISTS' as status
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'admins', 'human_agents', 'users', 'chat_sessions', 'chat_messages',
        'session_assignments', 'file_uploads', 'configuration_metadata',
        'widget_configuration', 'widget_suggested_messages', 'notification_settings',
        'security_settings', 'llm_providers', 'persona_configurations',
        'notifications', 'chat_feedback', 'token_usage_log', 'metrics',
        'email_oauth_credentials', 'user_unique_ids', 'scraped_websites',
        'api_usage', 'widget_scripts'
    )
ORDER BY table_name;

-- Success message
SELECT 'Missing migrations completed successfully!' as migration_status;
