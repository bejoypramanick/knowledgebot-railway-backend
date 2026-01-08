# Database Migration Scripts

This directory contains SQL migration scripts that must be run **manually** on your PostgreSQL database.

## Important Notes

- **All DDL operations must be run manually** - the application code does NOT execute any DDL statements
- Run these scripts in order if dependencies exist
- Always backup your database before running migrations
- Test migrations on a staging environment first

## Required Migrations

### 1. Add `hil_enabled` Column to `chatbot_configuration` Table

**File:** `add_hil_enabled_to_chatbot_configuration.sql`

**Purpose:** Adds the `hil_enabled` column to control Human-in-the-Loop (human agent support) functionality.

**When to run:** If you're getting errors about missing `hil_enabled` column.

**Command:**
```bash
psql -h <host> -U <user> -d <database> -f sql/add_hil_enabled_to_chatbot_configuration.sql
```

Or via Railway CLI:
```bash
railway connect postgres
\i sql/add_hil_enabled_to_chatbot_configuration.sql
```

### 2. Add `auto_generated_password` Column to `admins` Table

**File:** `add_auto_generated_password_to_admins.sql`

**Purpose:** Adds the `auto_generated_password` column to store auto-generated passwords for admin accounts.

**When to run:** If you're getting errors about missing `auto_generated_password` column when creating admin accounts.

**Command:**
```bash
psql -h <host> -U <user> -d <database> -f sql/add_auto_generated_password_to_admins.sql
```

Or via Railway CLI:
```bash
railway connect postgres
\i sql/add_auto_generated_password_to_admins.sql
```

## Verification

After running migrations, verify the columns exist:

```sql
-- Check hil_enabled column
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'chatbot_configuration' 
AND column_name = 'hil_enabled';

-- Check auto_generated_password column
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'admins' 
AND column_name = 'auto_generated_password';
```

## Running Migrations on Railway

1. Connect to your Railway PostgreSQL database:
   ```bash
   railway connect postgres
   ```

2. Run the migration script:
   ```sql
   \i sql/add_hil_enabled_to_chatbot_configuration.sql
   ```

3. Or copy-paste the SQL directly into the Railway SQL console.

## Troubleshooting

- If you get "column already exists" errors, the migration has already been run
- If you get permission errors, ensure your database user has ALTER TABLE permissions
- Always check the application logs after running migrations to ensure everything works
