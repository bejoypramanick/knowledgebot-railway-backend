-- Migration 006: Create suggested_messages table
-- This table stores suggested messages for the chat widget

CREATE TABLE IF NOT EXISTS public.suggested_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    message_text text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    updated_at timestamp DEFAULT now() NULL,
    created_by_email varchar(255) NULL,
    CONSTRAINT suggested_messages_pkey PRIMARY KEY (id),
    CONSTRAINT valid_sort_order CHECK (sort_order >= 0)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_suggested_messages_active ON public.suggested_messages USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_suggested_messages_sort_order ON public.suggested_messages USING btree (sort_order);

-- Add comments
COMMENT ON TABLE public.suggested_messages IS 'Suggested messages that appear in the chat widget';
COMMENT ON COLUMN public.suggested_messages.message_text IS 'The suggested message text';
COMMENT ON COLUMN public.suggested_messages.sort_order IS 'Order in which messages should be displayed';
COMMENT ON COLUMN public.suggested_messages.is_active IS 'Whether this message is currently active';
COMMENT ON COLUMN public.suggested_messages.created_by_email IS 'Email of the admin who created this message';

-- Insert default suggested messages
INSERT INTO public.suggested_messages (message_text, sort_order, is_active, created_by_email)
VALUES 
    ('What can you help me with?', 1, true, 'system@knowledgebot.com'),
    ('How do I upload documents?', 2, true, 'system@knowledgebot.com'),
    ('Show me my chat history', 3, true, 'system@knowledgebot.com'),
    ('What are my account settings?', 4, true, 'system@knowledgebot.com'),
    ('Help me find information', 5, true, 'system@knowledgebot.com')
ON CONFLICT DO NOTHING;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION public.update_suggested_messages_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER suggested_messages_updated_at
    BEFORE UPDATE ON public.suggested_messages
    FOR EACH ROW
    EXECUTE FUNCTION public.update_suggested_messages_updated_at();
