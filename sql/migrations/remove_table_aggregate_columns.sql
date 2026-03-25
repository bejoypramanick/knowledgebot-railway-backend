ALTER TABLE file_uploads
    DROP COLUMN IF EXISTS total_tables_count,
    DROP COLUMN IF EXISTS total_table_rows_input,
    DROP COLUMN IF EXISTS total_table_chars_input,
    DROP COLUMN IF EXISTS total_table_chars_output,
    DROP COLUMN IF EXISTS total_table_input_tokens,
    DROP COLUMN IF EXISTS total_table_output_tokens;

ALTER TABLE scraped_websites
    DROP COLUMN IF EXISTS total_tables_count,
    DROP COLUMN IF EXISTS total_table_rows_input,
    DROP COLUMN IF EXISTS total_table_chars_input,
    DROP COLUMN IF EXISTS total_table_chars_output,
    DROP COLUMN IF EXISTS total_table_input_tokens,
    DROP COLUMN IF EXISTS total_table_output_tokens;
