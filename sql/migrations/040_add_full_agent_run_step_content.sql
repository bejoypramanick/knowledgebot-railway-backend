-- Store the full captured agent step payload separately from the short UI preview.
-- Token counts in this table are diagnostics from Gemini count_tokens over this
-- captured content; provider-billed totals remain in token_usage_log.

ALTER TABLE public.agent_run_steps
    ADD COLUMN IF NOT EXISTS content_full text DEFAULT ''::text,
    ADD COLUMN IF NOT EXISTS token_source varchar(80) DEFAULT 'gemini_count_tokens_captured_content';

ALTER TABLE public.agent_run_steps
    ALTER COLUMN content_full SET COMPRESSION pglz;

COMMENT ON COLUMN public.agent_run_steps.content_full IS
    'Full captured agent step content, including tool call arguments and tool return payloads when exposed by the run object.';

COMMENT ON COLUMN public.agent_run_steps.token_source IS
    'Where token_count came from. For agent_run_steps this is a diagnostic count over captured content, not provider billing.';
