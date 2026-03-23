-- Migration 015: Add tables_metadata table and aggregate columns
-- Run manually on Railway Postgres BEFORE deploying code

-- Per-table metadata captured during Gemini table formatting
CREATE TABLE IF NOT EXISTS public.tables_metadata (
    id uuid DEFAULT uuidv7() NOT NULL,
    file_upload_id uuid NULL,
    scraped_website_id uuid NULL,
    table_index int4 DEFAULT 0,
    table_column_count_input int4 DEFAULT 0,
    table_row_count_input int4 DEFAULT 0,
    table_character_count_input int4 DEFAULT 0,
    table_word_count_input int4 DEFAULT 0,
    table_word_count_output int4 DEFAULT 0,
    table_character_count_output int4 DEFAULT 0,
    table_input_token_count int4 DEFAULT 0,
    table_output_token_count int4 DEFAULT 0,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT tables_metadata_pkey PRIMARY KEY (id),
    CONSTRAINT tables_metadata_file_upload_id_fkey FOREIGN KEY (file_upload_id) REFERENCES public.file_uploads(id) ON DELETE CASCADE,
    CONSTRAINT tables_metadata_scraped_website_id_fkey FOREIGN KEY (scraped_website_id) REFERENCES public.scraped_websites(id) ON DELETE CASCADE,
    CONSTRAINT tables_metadata_has_parent CHECK (file_upload_id IS NOT NULL OR scraped_website_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_tables_metadata_file_upload_id ON public.tables_metadata USING btree (file_upload_id);
CREATE INDEX IF NOT EXISTS idx_tables_metadata_scraped_website_id ON public.tables_metadata USING btree (scraped_website_id);

-- Aggregate table metrics on file_uploads
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_tables_count int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_table_rows_input int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_table_chars_input int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_table_chars_output int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_table_input_tokens int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_table_output_tokens int4 DEFAULT 0;

-- Aggregate table metrics on scraped_websites
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_tables_count int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_table_rows_input int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_table_chars_input int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_table_chars_output int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_table_input_tokens int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS total_table_output_tokens int4 DEFAULT 0;
