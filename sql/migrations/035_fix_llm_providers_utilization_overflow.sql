-- Migration: 035_fix_llm_providers_utilization_overflow
-- Description: Increases precision of token_utilization_percent to handle usage > 999.99%

ALTER TABLE public.llm_providers DROP COLUMN IF EXISTS token_utilization_percent;

ALTER TABLE public.llm_providers ADD COLUMN token_utilization_percent numeric(10, 2)
GENERATED ALWAYS AS (
    CASE
        WHEN token_limit = 0 THEN 0::numeric
        ELSE round(token_used::numeric / token_limit::numeric * 100::numeric, 2)
    END
) STORED NULL;

COMMENT ON COLUMN public.llm_providers.token_utilization_percent IS 'Token utilization as a percentage, supports values up to 99,999,999.99%';
