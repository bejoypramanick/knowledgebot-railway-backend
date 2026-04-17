CREATE TABLE IF NOT EXISTS public.tenant_kb_quota_config (
    tenant_id uuid PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    quota_limit_kb bigint NOT NULL DEFAULT 102400,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.tenant_kb_quota_monthly_usage (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    cycle_start_at timestamptz NOT NULL,
    cycle_end_at timestamptz NOT NULL,
    quota_limit_kb bigint NOT NULL,
    reset_usage_at timestamptz NOT NULL,
    manual_reset_count integer NOT NULL DEFAULT 0,
    last_manual_reset_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tenant_kb_quota_monthly_usage_unique UNIQUE (tenant_id, cycle_start_at)
);

CREATE INDEX IF NOT EXISTS idx_tenant_kb_quota_monthly_usage_tenant_cycle
ON public.tenant_kb_quota_monthly_usage (tenant_id, cycle_start_at DESC);
