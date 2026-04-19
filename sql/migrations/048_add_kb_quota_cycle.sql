ALTER TABLE public.tenant_kb_quota_config
    ADD COLUMN IF NOT EXISTS quota_cycle text NOT NULL DEFAULT 'monthly';

ALTER TABLE public.tenant_kb_quota_config
    ADD COLUMN IF NOT EXISTS storage_quota_limit_kb bigint NOT NULL DEFAULT 20480;

ALTER TABLE public.tenant_kb_quota_config
    DROP CONSTRAINT IF EXISTS tenant_kb_quota_config_cycle_check;

ALTER TABLE public.tenant_kb_quota_config
    ADD CONSTRAINT tenant_kb_quota_config_cycle_check
    CHECK (quota_cycle IN ('daily', 'monthly'));
