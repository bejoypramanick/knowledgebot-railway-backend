# Delete All Chats SQL Script

## ⚠️ WARNING
This SQL script will **permanently delete ALL chat data** from your database. This includes:
- All chat sessions (including sentiment and session_feedback columns)
- All chat messages  
- All human agent session assignments
- All chat feedback

**This action CANNOT be undone!**

**Note:** The `chat_sessions` table includes:
- `sentiment` (VARCHAR) - LLM-analyzed sentiment (positive/negative/neutral)
- `session_feedback` (VARCHAR) - Aggregated feedback from chat_feedback table
These columns will be deleted along with the chat_sessions records.

## File Location
`sql/delete_all_chats.sql`

## Usage

### Step 1: Review What Will Be Deleted
First, run the SELECT statements at the top of the file to see how many records will be deleted:

```sql
SELECT 'chat_sessions' as table_name, COUNT(*) as record_count FROM chat_sessions
UNION ALL
SELECT 'chat_messages' as table_name, COUNT(*) as record_count FROM chat_messages
-- ... etc
```

### Step 2: Uncomment DELETE Statements
Open `sql/delete_all_chats.sql` and uncomment the DELETE statements at the bottom:

```sql
-- Change from:
-- DELETE FROM chat_feedback;

-- To:
DELETE FROM chat_feedback;
```

### Step 3: Run the Script
Execute the SQL file using one of these methods:

**Option 1: Using psql command line**
```bash
psql $DATABASE_URL -f sql/delete_all_chats.sql
```

**Option 2: Using Railway CLI**
```bash
railway connect
# Then copy and paste the SQL commands
```

**Option 3: Using a database GUI tool**
- Open your database in pgAdmin, DBeaver, or similar
- Open the SQL file
- Execute the uncommented DELETE statements

**Option 4: Direct SQL execution**
```bash
# If you have DATABASE_URL set:
psql "$DATABASE_URL" << EOF
DELETE FROM chat_feedback;
DELETE FROM human_agent_sessions;
DELETE FROM chat_messages;
DELETE FROM chat_sessions;
EOF
```

### Step 4: Verify Deletion
Run the verification queries at the bottom of the file to confirm all data was deleted.

## Deletion Order

The DELETE statements are ordered to respect foreign key constraints:
1. `chat_feedback` (if exists)
2. `human_agent_sessions` (if exists)  
3. `chat_messages`
4. `chat_sessions` (this may cascade delete messages if CASCADE is set)

## After Running

Once you've deleted all chats and verified everything is working:
- **Delete this SQL file** to prevent accidental use
- Or rename it to `delete_all_chats.sql.disabled` if you want to keep it for reference
