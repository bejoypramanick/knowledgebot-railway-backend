# Database Migrations

This directory contains SQL migration files for the KnowledgeBot Railway Backend database.

## Migration Naming Convention

Migrations are named with the format: `YYYYMMDD_description.sql`

- `YYYYMMDD`: Date in YYYYMMDD format (e.g., 20250119)
- `description`: Brief description of what the migration does, using underscores instead of spaces

## How to Run Migrations

### Manual Execution (Recommended)

Run migrations manually using your preferred PostgreSQL client:

#### Option 1: Railway CLI
```bash
# Connect to your Railway database
railway connect postgres

# Then run each migration file manually:
psql -f migrations/20250119_add_detailed_token_fields.sql
psql -f migrations/20250122_remove_unused_columns.sql
psql -f migrations/fix_chat_sessions_archive_status.sql
# ... etc
```

#### Option 2: Direct psql connection
```bash
psql -h your-db-host -U your-username -d your-database -f migrations/filename.sql
```

#### Option 3: Any PostgreSQL client
1. Connect to your Railway PostgreSQL database
2. Execute the contents of each migration file manually
3. Run migrations in chronological order (by filename date)

### Important: Run Order
Always run migrations in chronological order by their date prefix:
1. `20250119_add_detailed_token_fields.sql`
2. `20250122_remove_unused_columns.sql`
3. `20250122_update_pending_to_confirmed.sql`
4. `add_configuration_audit_log.sql`
5. `add_display_chatbot_toggle.sql`
6. `add_hil_disabled_message_column.sql`
7. `add_token_usage_log_migration.sql`
8. `migrate_assistant_to_bot_role.sql`
9. `fix_chat_sessions_archive_status.sql` (run this last)

## Migration Files

### 20250119_add_detailed_token_fields.sql
- **Purpose**: Adds detailed token usage fields to support OpenAI cache tokens and audio tokens
- **Columns Added**:
  - `cache_read_tokens`: Tokens read from cache (OpenAI prompt caching)
  - `cache_write_tokens`: Tokens written to cache (OpenAI prompt caching)
  - `input_audio_tokens`: Audio input tokens (multimodal models)
  - `cache_audio_read_tokens`: Audio tokens read from cache
- **Safe to Run**: Yes, uses `IF NOT EXISTS` so can be run multiple times safely

## Verification

After running the migration, verify it worked:

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'token_usage_log'
AND column_name IN ('cache_read_tokens', 'cache_write_tokens', 'input_audio_tokens', 'cache_audio_read_tokens')
ORDER BY column_name;
```

Expected output:
```
      column_name      | data_type | is_nullable | column_default
----------------------|-----------|-------------|---------------
 cache_audio_read_tokens | integer   | YES         | 0
 cache_read_tokens      | integer   | YES         | 0
 cache_write_tokens     | integer   | YES         | 0
 input_audio_tokens     | integer   | YES         | 0
```

## Rollback

If you need to rollback this migration:

```sql
ALTER TABLE token_usage_log
DROP COLUMN IF EXISTS cache_read_tokens,
DROP COLUMN IF EXISTS cache_write_tokens,
DROP COLUMN IF EXISTS input_audio_tokens,
DROP COLUMN IF EXISTS cache_audio_read_tokens;
```

## Important Notes

- Always backup your database before running migrations
- Test migrations on a development/staging environment first
- Never run migrations directly in application code
- Keep migration files version controlled
- Run migrations in order (by date)