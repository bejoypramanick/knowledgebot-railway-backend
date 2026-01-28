-- Migration 004: Create llm_providers table
-- This table tracks LLM provider usage and token limits

CREATE TABLE IF NOT EXISTS public.llm_providers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider_name varchar(100) NOT NULL,
    token_used integer DEFAULT 0 NOT NULL,
    token_limit integer DEFAULT 20000 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    updated_at timestamp DEFAULT now() NULL,
    last_reset_at timestamp DEFAULT now() NULL,
    CONSTRAINT llm_providers_pkey PRIMARY KEY (id),
    CONSTRAINT llm_providers_name_unique UNIQUE (provider_name),
    CONSTRAINT valid_token_usage CHECK (token_used >= 0),
    CONSTRAINT valid_token_limit CHECK (token_limit > 0),
    CONSTRAINT valid_token_usage_not_exceed_limit CHECK (token_used <= token_limit)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_llm_providers_active ON public.llm_providers USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_llm_providers_name ON public.llm_providers USING btree (provider_name);
CREATE INDEX IF NOT EXISTS idx_llm_providers_usage ON public.llm_providers USING btree (token_used);

-- Add comments
COMMENT ON TABLE public.llm_providers IS 'LLM provider configuration and token usage tracking';
COMMENT ON COLUMN public.llm_providers.provider_name IS 'Name of the LLM provider (e.g., gemini, openai, anthropic)';
COMMENT ON COLUMN public.llm_providers.token_used IS 'Number of tokens used by this provider';
COMMENT ON COLUMN public.llm_providers.token_limit IS 'Maximum tokens allowed for this provider';
COMMENT ON COLUMN public.llm_providers.is_active IS 'Whether this provider is currently active';
COMMENT ON COLUMN public.llm_providers.last_reset_at IS 'Last time token usage was reset';

-- Insert default LLM providers
INSERT INTO public.llm_providers (provider_name, token_used, token_limit, is_active)
VALUES 
    ('gemini', 0, 20000, true),
    ('openai', 0, 20000, true),
    ('anthropic', 0, 20000, true),
    ('local', 0, 50000, true)
ON CONFLICT (provider_name) DO NOTHING;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION public.update_llm_providers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER llm_providers_updated_at
    BEFORE UPDATE ON public.llm_providers
    FOR EACH ROW
    EXECUTE FUNCTION public.update_llm_providers_updated_at();
