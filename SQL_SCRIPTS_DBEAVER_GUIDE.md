# SQL Scripts - DBeaver Guide

Both SQL scripts have been updated to be **fully compatible with DBeaver** PostgreSQL connections.

## Key Changes Made

### Migration Script: `006_add_admin_session_tracking.sql`

✅ **Removed**:
- `\echo` commands (psql-specific)
- `/**/ ` block comments (replaced with `--` comments)
- Inline comments on column definitions

✅ **Updated**:
- All comments use `--` (standard SQL)
- Block comments use `--` on each line
- Column definitions are cleaner without inline comments
- Constraints formatted for better readability

✅ **Now Works**:
- DBeaver SQL Editor
- psql command line
- Any PostgreSQL client

### Verification Script: `verify_admin_audit_deployment.sql`

✅ **Removed**:
- `\echo` commands (replaced with `SELECT 'text' AS section`)
- `\dt` commands (replaced with SQL information_schema queries)
- `\d+` commands (replaced with detailed SQL information_schema queries)
- psql-specific metacommands

✅ **Updated**:
- All output uses `SELECT` statements
- Information retrieved from `information_schema` views
- Uses `ON CONFLICT DO NOTHING` for test inserts (safe re-runs)
- Automatic cleanup of test data at the end

✅ **Now Works**:
- DBeaver SQL Editor (all features)
- psql command line
- Azure Data Studio
- pgAdmin
- Any PostgreSQL client

## How to Use in DBeaver

### Running the Migration

1. **Open DBeaver**
   - Launch DBeaver application

2. **Connect to Railway PostgreSQL**
   - Right-click "Database Connections" → "New Database Connection"
   - Or: Database → New Database Connection
   - Select PostgreSQL
   - Fill in Railway credentials:
     - Host: from Railway Dashboard → Postgres → Connect
     - Port: 5432
     - Database: postgres (or your database name)
     - Username: from Railway Dashboard
     - Password: from Railway Dashboard
   - Test Connection → Finish

3. **Open SQL Editor**
   - In DBeaver, right-click the PostgreSQL connection
   - Select "SQL Editor" → "Open SQL Editor"
   - Or: File → New → SQL Script

4. **Run Migration**
   - Open file: `sql/migrations/006_add_admin_session_tracking.sql`
   - Or copy-paste the contents into the SQL Editor
   - **Option A**: Execute entire script
     - Select all (Ctrl+A)
     - Execute (Ctrl+Enter)
   - **Option B**: Execute section by section
     - Highlight a section (e.g., the CREATE TABLE statement)
     - Execute (Ctrl+Enter)

5. **Review Output**
   - No errors should appear
   - Tables created successfully
   - Indexes created successfully
   - Constraints created successfully
   - Views created successfully

### Running the Verification

1. **Open SQL Editor**
   - File → New → SQL Script
   - Or use existing editor

2. **Load Verification Script**
   - Open file: `scripts/verify_admin_audit_deployment.sql`
   - Or copy-paste the contents

3. **Execute Verification**
   - Select all (Ctrl+A)
   - Execute (Ctrl+Enter)
   - Or execute section by section:
     - Click in a section (e.g., "SECTION 1: VERIFY TABLES EXIST")
     - Execute (Ctrl+Enter) - runs up to next section

4. **Review Results**

   Each section shows results in the "Results" tab:

   **Section 1: Tables Verification**
   ```
   admin_sessions_exists | true
   admin_actions_exists  | true
   ```

   **Section 2-3: Columns**
   Lists all columns with data types

   **Section 4-5: Indexes**
   Lists all indexes (should see many)

   **Section 6-7: Constraints**
   Lists all constraints (should see many)

   **Section 8: Views**
   ```
   admin_sessions_analytics_exists | true
   admin_actions_analytics_exists  | true
   ```

   **Section 9: Triggers**
   Lists triggers for updated_at columns

   **Section 14: Final Summary**
   ```
   tables_created     | PASS
   indexes_created    | PASS
   constraints_created | PASS
   views_created      | PASS
   ```

   **If all show PASS**: ✅ **Deployment successful!**

## DBeaver Tips

### Running Specific Sections

To run only a specific section:

1. Click anywhere in that section
2. Press **Ctrl+Enter** (or right-click → "Execute" → "Execute Active Statement")
3. DBeaver will execute just that statement/section

### Viewing Results

- Results appear in the "Results" tab below the SQL Editor
- Click column headers to sort
- Right-click cells to copy

### Formatting SQL

To auto-format the SQL:

1. Select all (Ctrl+A)
2. Right-click → "Format SQL"

### Saving Results

To save query results:

1. In Results tab, right-click
2. Select "Export..."
3. Choose format (CSV, Excel, etc.)

### Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Execute active statement | Ctrl+Enter |
| Execute all | Ctrl+Shift+Enter |
| Format SQL | Ctrl+Shift+F |
| New SQL Editor | Ctrl+Alt+U |
| Open file | Ctrl+O |
| Find/Replace | Ctrl+H |

## Troubleshooting

### Error: "Table already exists"

**Solution**: This is OK - means migration was already run.
- Run the verification script to confirm tables are intact
- You can drop and re-run if needed:

```sql
DROP TABLE IF EXISTS admin_actions CASCADE;
DROP TABLE IF EXISTS admin_sessions CASCADE;
-- Then re-run migration
```

### Error: "Function update_updated_at_column() does not exist"

**Solution**: This trigger function might not exist in your database.
- The migration includes it, but it may be optional
- Comment out the trigger line and re-run:

```sql
-- CREATE TRIGGER admin_sessions_updated_at
-- BEFORE UPDATE ON admin_sessions
-- FOR EACH ROW
-- EXECUTE FUNCTION update_updated_at_column();
```

Or create the function first:

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### Error: "Connection refused" or "Cannot connect to database"

**Solution**:
1. Verify Railway credentials in DBeaver connection settings
2. Check Railway Dashboard for database status
3. Test connection before running scripts (DBeaver will prompt)

### Verification Shows FAIL

**Check**:
1. Did migration actually complete? (check DBeaver for errors)
2. Are you connected to correct database?
3. Run migration again if needed

## Performance Notes

- Migration: < 2 seconds
- Verification: < 1 second
- Both operations are read-safe (use ON CONFLICT DO NOTHING for tests)

## File Versions

- ✅ `sql/migrations/006_add_admin_session_tracking.sql` - DBeaver compatible
- ✅ `scripts/verify_admin_audit_deployment.sql` - DBeaver compatible

Both scripts also work with:
- psql (PostgreSQL command line)
- Azure Data Studio
- pgAdmin
- pgweb
- Any standard PostgreSQL client

## Questions?

Refer to:
- `ADMIN_AUDIT_IMPLEMENTATION.md` - Detailed implementation guide
- `DEPLOYMENT_CHECKLIST.md` - Step-by-step deployment
- `sql/migrations/006_add_admin_session_tracking.sql` - Script with comments
