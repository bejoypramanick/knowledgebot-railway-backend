-- Migration: Set default monthly knowledge base quota to 20 MB.
-- Existing rows that still have the previous default of 100 MB are moved to
-- the new default. Tenant-specific custom values other than 100 MB are kept.

ALTER TABLE public.tenant_kb_quota_config
    ALTER COLUMN quota_limit_kb SET DEFAULT 20480;

UPDATE public.tenant_kb_quota_config
SET quota_limit_kb = 20480,
    updated_at = CURRENT_TIMESTAMP
WHERE quota_limit_kb = 102400;

UPDATE public.tenant_kb_quota_monthly_usage
SET quota_limit_kb = 20480,
    updated_at = CURRENT_TIMESTAMP
WHERE quota_limit_kb = 102400;
