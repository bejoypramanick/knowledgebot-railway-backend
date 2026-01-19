# Database Migrations

This directory contains SQL migration files for the KnowledgeBot Railway Backend database.

## Migration Naming Convention

Migrations are named with the format: `YYYYMMDD_description.sql`

- `YYYYMMDD`: Date in YYYYMMDD format (e.g., 20250119)
- `description`: Brief description of what the migration does, using underscores instead of spaces

## How to Run Migrations

### Option 1: Using Railway CLI (Recommended for Production)

1. Install Railway CLI if not already installed:
   ```bash
   npm install -g @railway/cli
   ```

2. Link to your Railway project:
   ```bash
   railway link
   ```

3. Connect to your database:
   ```bash
   railway connect postgres
   ```

4. Run the migration file:
   ```bash
   psql -f migrations/20250119_add_detailed_token_fields.sql
   ```

### Option 2: Using psql directly

If you have direct database access:

```bash
psql -h your-db-host -U your-username -d your-database -f migrations/20250119_add_detailed_token_fields.sql
```

### Option 3: Using any PostgreSQL client

1. Connect to your Railway PostgreSQL database
2. Execute the contents of the migration file

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