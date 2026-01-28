-- Migration 002: Create chatbot_personas table
-- This table is missing from the database schema and is needed for persona switching

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

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_chatbot_personas_active ON public.chatbot_personas USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_chatbot_personas_name ON public.chatbot_personas USING btree (persona_name);

-- Add comments
COMMENT ON TABLE public.chatbot_personas IS 'Chatbot personas for different AI personalities and behaviors';
COMMENT ON COLUMN public.chatbot_personas.persona_name IS 'Display name of the persona';
COMMENT ON COLUMN public.chatbot_personas.persona_description IS 'Detailed description of the persona behavior and characteristics';
COMMENT ON COLUMN public.chatbot_personas.system_prompt IS 'System prompt used for the AI persona';
COMMENT ON COLUMN public.chatbot_personas.is_active IS 'Whether this persona is currently active for use';
COMMENT ON COLUMN public.chatbot_personas.created_by_email IS 'Email of the admin who created this persona';

-- Insert default persona
INSERT INTO public.chatbot_personas (persona_name, persona_description, system_prompt, is_active, created_by_email)
VALUES (
    'KnowledgeBot',
    'A helpful AI assistant specialized in knowledge management and answering questions based on available documents and conversations.',
    'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.',
    true,
    'system@knowledgebot.com'
) ON CONFLICT (persona_name) DO NOTHING;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION public.update_chatbot_personas_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER chatbot_personas_updated_at
    BEFORE UPDATE ON public.chatbot_personas
    FOR EACH ROW
    EXECUTE FUNCTION public.update_chatbot_personas_updated_at();

-- Verify table was created
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' AND table_name = 'chatbot_personas';
