-- Add provider_type to llm_providers
ALTER TABLE public.llm_providers 
ADD COLUMN IF NOT EXISTS provider_type varchar(50) DEFAULT 'llm' NULL;
