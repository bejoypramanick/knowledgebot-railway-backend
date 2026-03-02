# Debug Status - Knowledge Bot API Issues

## Summary
Currently debugging two main issues with the Knowledge Bot API:
1. **403 Forbidden** on mark-read endpoint
2. **500 Internal Server Error** on feedback/counts endpoint

---

## Issue 1: 403 Forbidden on Mark-Read Endpoint

### Problem
```
POST /api/v1/gateway/configuration/admin/chat-sessions/269/mark-read
Response: 403 Forbidden
Message: "Only human agents and admins can mark messages as read"
```

User is already an admin and human agent, but the endpoint returns 403.

### Root Cause Analysis
The `mark_session_messages_as_read()` method calls `check_user_role()` which queries:
```sql
SELECT EXISTS(...) as is_agent, EXISTS(...) as is_admin
```

For some reason, both `is_agent` and `is_admin` are returning `False` even for valid admins.

Possible causes:
1. User email format mismatch (case sensitivity, extra spaces)
2. User doesn't exist in the `users` table
3. User exists but doesn't have role mappings in `user_role_mapping`
4. Role names don't match ('admin' vs 'Admin', etc.)
5. Database connection/query issue

### Enhanced Debugging
**Added detailed logging** (commit c43849a):
- Logs the email being checked in `check_user_role()`
- Logs the raw database query result
- Logs the converted dictionary values
- Logs final is_agent and is_admin values
- Logs any exceptions that occur

**Location**: `configuration/dao/chat_log_dao.py`, line 59-86

### How to Debug
1. Deploy the backend with enhanced logging to production
2. Call the mark-read endpoint:
   ```bash
   curl -X POST "https://api-gateway-common.up.railway.app/api/v1/gateway/configuration/admin/chat-sessions/269/mark-read" \
     -H "X-User-Email: your@email.com" \
     -H "X-User-UID: your-uid" \
     -H "X-User-Name: Your Name"
   ```
3. Check the backend logs for lines starting with "🔍 DEBUG check_user_role"
4. Look for what email is being checked and what roles are returned

### Expected Logs
```
🔍 DEBUG check_user_role: Checking email: your@email.com
🔍 DEBUG check_user_role: Query result row: (True, True)
🔍 DEBUG check_user_role: Converted row_dict: {'is_agent': True, 'is_admin': True}
🔍 DEBUG check_user_role: Final result - is_agent=True, is_admin=True
```

### Verification Steps
1. Check if user exists:
   ```sql
   SELECT id, email FROM users WHERE email = 'your@email.com';
   ```

2. Check user roles:
   ```sql
   SELECT u.email, r.role_name
   FROM user_role_mapping urm
   JOIN users u ON urm.user_id = u.id
   JOIN roles r ON urm.role_id = r.id
   WHERE u.email = 'your@email.com';
   ```

3. Verify role names exist:
   ```sql
   SELECT DISTINCT role_name FROM roles;
   ```

---

## Issue 2: 500 Error on Feedback/Counts Endpoint

### Problem
```
POST /api/v1/gateway/configuration/feedback/counts
Request: { "session_ids": ["269", "268", "267"] }
Response: 500 Internal Server Error
Message: 'column "feedback_type" does not exist'
```

### Root Cause
The migration file `add_feedback_type_to_chat_sessions.sql` was created but **never applied to the Railway database**. When the API tries to query the `feedback_type` column, the database throws an error.

### Solution
**Created migration runner script** (commit f60ac37):
- File: `run_migration.py`
- Connects using existing SQLAlchemy database config
- Checks if column exists before and after
- Applies SQL migration files

### How to Apply Migration

1. **Option A: Run locally** (if you have access)
   ```bash
   python run_migration.py
   ```

2. **Option B: SSH into Railway and run**
   ```bash
   python /app/run_migration.py
   ```

3. **Option C: Manual SQL** (via Railway dashboard)
   ```sql
   -- Add feedback_type column if it doesn't exist
   ALTER TABLE chat_sessions
   ADD COLUMN IF NOT EXISTS feedback_type varchar(20);

   -- Add constraint
   ALTER TABLE chat_sessions
   ADD CONSTRAINT IF NOT EXISTS chat_sessions_feedback_type_check
   CHECK (feedback_type IS NULL OR feedback_type IN ('positive', 'negative'));

   -- Add feedback_provided_at column
   ALTER TABLE chat_sessions
   ADD COLUMN IF NOT EXISTS feedback_provided_at timestamp;

   -- Create indexes
   CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_type
   ON chat_sessions(feedback_type)
   WHERE feedback_type IS NOT NULL;

   CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_provided_at
   ON chat_sessions(feedback_provided_at)
   WHERE feedback_provided_at IS NOT NULL;
   ```

### Verify Migration
After applying the migration:
```bash
# Check column exists
SELECT feedback_type, feedback_provided_at FROM chat_sessions LIMIT 1;

# Test the endpoint
curl -X POST "https://api-gateway-common.up.railway.app/api/v1/gateway/configuration/feedback/counts" \
  -H "Content-Type: application/json" \
  -d '{"session_ids": ["269"]}'
```

### Exception Handling
The feedback_dao.py already has proper exception handling (lines 120-124):
```python
except Exception as e:
    logger.warning(f"Could not retrieve feedback counts (feedback_type column may not exist): {e}")
    return result_dict  # Return empty counts for all sessions
```

Once the migration is applied, this exception handling will silently return empty counts if the column still doesn't exist, providing graceful degradation.

---

## Deployment Status

### Frontend (knowledgebot)
✅ **Deployed**
- Latest commits pushed to main
- Auth headers are being sent in all API requests
- Cloudflare deployment is in progress
- Send button moved inside message input box

### Backend (knowledgebot-railway-backend)
✅ **Code pushed**
- Enhanced logging added (c43849a)
- Migration runner script added (f60ac37)
- **Needs**: Deploy to production to activate logging and test

---

## Next Steps (In Order)

1. **Deploy backend** with enhanced logging
2. **Call mark-read endpoint** and capture logs
3. **Analyze logs** to identify why roles are False
4. **Apply migration** to add feedback_type column
5. **Test feedback/counts endpoint** to verify it works
6. **Verify overall flow** with end-to-end testing

---

## Files Changed

### Backend
- `configuration/dao/chat_log_dao.py` - Enhanced logging in check_user_role()
- `configuration/service/chat_log_service.py` - Enhanced logging in mark_session_messages_as_read()
- `run_migration.py` - NEW - Migration runner script

### Commits
- c43849a - debug: add enhanced logging to check_user_role
- f60ac37 - feat: add migration runner script

---

## Contact Points
- Backend logs: Check Railway logs for "🔍 DEBUG" messages
- Database: Railway PostgreSQL dashboard
- Frontend: Check browser console for API requests
- API Gateway: Check logs for request/response details
