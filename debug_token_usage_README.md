# Token Usage Debugging Guide

This guide provides SQL queries to debug token usage tracking issues in the KnowledgeBot system.

## How to Run These Queries

### Option 1: Railway CLI (Recommended)
```bash
# Connect to Railway database
railway connect postgres

# Run the queries
psql -f debug_token_usage_queries.sql
```

### Option 2: Direct PostgreSQL Connection
```bash
psql -h your-db-host -U postgres -d railway -f debug_token_usage_queries.sql
```

### Option 3: Run Individual Queries
Copy and paste individual queries into your PostgreSQL client or Railway database console.

## What Each Query Diagnoses

### Basic Structure Checks (Queries 1-3)
- **Query 1**: Verifies `token_usage_log` table exists
- **Query 2**: Shows all columns in the table
- **Query 3**: Specifically checks for the detailed token fields that were added

### Data Overview (Queries 4-6)
- **Query 4**: Shows cached token usage summary
- **Query 5**: Total count of token usage log entries
- **Query 6**: Most recent 10 token usage entries

### Usage Analysis (Queries 7-9)
- **Query 7**: Token usage grouped by provider (OpenAI vs Gemini)
- **Query 8**: Token usage grouped by API call type (chat, rag, etc.)
- **Query 9**: Token usage grouped by model

### Data Integrity (Queries 10-13)
- **Query 10**: Sessions with token usage and their activity
- **Query 11**: Checks for NULL values in critical fields
- **Query 12**: Hourly token usage summary (last 24 hours)
- **Query 13**: Identifies duplicate entries

### Advanced Token Types (Queries 14-15)
- **Query 14**: Entries with OpenAI cache tokens (should be > 0)
- **Query 15**: Entries with audio tokens

### Foreign Key Validation (Queries 16-19)
- **Query 16**: Validates session_id foreign keys
- **Query 17**: Validates message_id foreign keys
- **Query 18**: Full details with joins to related tables
- **Query 19**: Counts orphaned records (no corresponding session/message)

### Database Structure (Query 20)
- **Query 20**: Shows constraints and indexes on the table

## Quick Diagnostic Queries

### Check if token tracking is working at all
```sql
SELECT COUNT(*) as total_records FROM token_usage_log;
```
- **Expected**: Some number > 0 if token tracking has occurred
- **Problem**: 0 records means no token usage is being logged

### Check if detailed fields are being used
```sql
SELECT
    COUNT(CASE WHEN cache_read_tokens > 0 THEN 1 END) as cache_reads,
    COUNT(CASE WHEN cache_write_tokens > 0 THEN 1 END) as cache_writes,
    COUNT(CASE WHEN input_audio_tokens > 0 THEN 1 END) as audio_tokens
FROM token_usage_log;
```
- **Expected**: Non-zero values for OpenAI entries (cache tokens) and audio models
- **Problem**: All zeros means detailed fields aren't being populated

### Check recent activity
```sql
SELECT COUNT(*) as entries_last_hour FROM token_usage_log
WHERE created_at >= NOW() - INTERVAL '1 hour';
```
- **Expected**: Some activity if the system is being used
- **Problem**: 0 entries means recent token usage isn't being logged

## Common Issues and Solutions

### Issue: "column 'cache_read_tokens' of relation 'token_usage_log' does not exist"
**Symptoms**: Database errors when trying to insert token usage
**Solution**: Run the migration `migrations/20250119_add_detailed_token_fields.sql`

### Issue: No token usage records appearing
**Symptoms**: Queries return 0 records, UI shows "No token usage data available"
**Possible Causes**:
1. Migration not applied (check Query 3)
2. Token tracking code not being executed
3. Database connection issues in token tracker
4. Exceptions being caught and logged but not re-raised

### Issue: Token usage appears but detailed fields are all 0
**Symptoms**: Records exist but cache_read_tokens, cache_write_tokens = 0
**Possible Causes**:
1. OpenAI responses don't include cache token information
2. Token extraction logic not parsing cache tokens correctly
3. pydantic-ai RunUsage object doesn't include cache tokens

### Issue: Orphaned records (no corresponding session/message)
**Symptoms**: Query 19 shows orphaned_sessions > 0 or orphaned_messages > 0
**Possible Causes**:
1. Sessions/messages deleted but token logs remain
2. Token logging happening before database commit
3. ID format mismatch (UUID vs string)

## Debugging Steps

1. **Start with basics**: Run queries 1-6 to verify table structure and data
2. **Check recent activity**: Run the "Quick check: Recent activity" query
3. **Verify data integrity**: Run queries 10-13 to check for issues
4. **Check foreign keys**: Run queries 16-19 to validate relationships
5. **Examine detailed fields**: Run queries 14-15 to see if advanced token types are working

## Logs to Check

If queries show no data, check these logs:
- Configuration service logs for "✅ Detailed token fields already exist"
- Chatbot orchestration logs for "✅ Token usage tracked in database"
- Database logs for any constraint violations or errors

## Getting Help

If you're still having issues:
1. Run all queries and share the results
2. Include relevant log excerpts
3. Note when the issue started occurring
4. Mention any recent deployments or code changes