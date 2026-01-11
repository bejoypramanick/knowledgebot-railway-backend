# Database 3NF Normalization - Complete Migration Plan

## Executive Summary

This document outlines the complete migration from the current database schema to a fully normalized 3NF (Third Normal Form) schema. The migration will preserve all existing functionality while improving data integrity, reducing redundancy, and enabling better scalability.

## Migration Overview

### Key Changes

1. **Removed Arrays** → Normalized into separate tables
   - `chatbot_configuration.admin_emails` → Already in `admins` table
   - `chatbot_configuration.human_agents` → Already in `human_agents` table
   - `widget_configuration.suggested_messages` → New `widget_suggested_messages` table

2. **Split Configuration Tables** → Separate tables by concern
   - `chatbot_configuration` → Split into:
     - `configuration_metadata` (global settings)
     - `notification_settings` (notification config)
     - `security_settings` (security config)
     - `llm_providers` (LLM token management)
     - `persona_configurations` (AI personas)

3. **Normalized Session Management**
   - `human_agent_sessions` → `session_assignments` (supports both agents and admins)
   - Added proper FK constraints to `chat_sessions`

4. **Removed Derived Data**
   - `chat_sessions.session_feedback` → Computed from `chat_feedback` table

## Schema Changes Summary

### New Tables Created
1. `configuration_metadata` - Global configuration (single row)
2. `notification_settings` - Notification settings (key-value)
3. `security_settings` - Security settings (key-value)
4. `llm_providers` - LLM provider configurations
5. `persona_configurations` - AI persona configurations
6. `widget_suggested_messages` - Widget suggested messages (normalized from array)
7. `session_assignments` - Session-to-agent/admin assignments (replaces `human_agent_sessions`)

### Tables Modified
1. `chatbot_configuration` - Removed (split into multiple tables)
2. `widget_configuration` - Removed `suggested_messages` array
3. `chat_sessions` - Removed `session_feedback` (derived field)
4. `human_agent_sessions` - Replaced by `session_assignments`

### Tables Unchanged
- `users`
- `admins`
- `human_agents`
- `user_unique_ids`
- `chat_messages`
- `chat_feedback`
- `file_uploads`
- `scraped_websites`
- `api_usage`
- `metrics`
- `notifications`
- `email_oauth_credentials`
- `token_usage_cache`
- `widget_scripts`

## Code Changes Required

### Backend Changes

#### 1. Configuration Service (`services/configuration_service/`)

**Files to Update:**

##### `main.py`
- [ ] Update `get_chatbot_config()` to read from new tables
- [ ] Update `save_chatbot_config()` to write to new tables
- [ ] Update `get_widget_config()` to join with `widget_suggested_messages`
- [ ] Update `save_widget_config()` to manage suggested messages table

**Changes:**
```python
# OLD: Read from single table
config = await conn.fetchrow("SELECT * FROM chatbot_configuration")

# NEW: Read from multiple tables
metadata = await conn.fetchrow("SELECT * FROM configuration_metadata WHERE id = 1")
notifications = await conn.fetch("SELECT * FROM notification_settings")
security = await conn.fetch("SELECT * FROM security_settings")
llm_providers = await conn.fetch("SELECT * FROM llm_providers")
personas = await conn.fetch("SELECT * FROM persona_configurations WHERE is_active = true")
```

##### `chat_log.py`
- [ ] Update `assign_chat_with_load_balancing()` to use `session_assignments`
- [ ] Update `get_agent_online_status()` to check `session_assignments`
- [ ] Update `get_agent_chat_count()` to count from `session_assignments`
- [ ] Update all session assignment logic to use new table
- [ ] Update `assign_chat_to_agent()` to insert into `session_assignments`
- [ ] Update `transfer_chat_session()` to update `session_assignments`
- [ ] Remove `session_feedback` references (use computed value)

**Changes:**
```python
# OLD: Insert into human_agent_sessions
await conn.execute("""
    INSERT INTO human_agent_sessions (customer_session_id, agent_email, status)
    VALUES ($1, $2, 'connected')
""", session_id, agent_email)

# NEW: Insert into session_assignments
await conn.execute("""
    INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status)
    VALUES (
        (SELECT id FROM chat_sessions WHERE session_id = $1),
        $2,
        $3,
        'active'
    )
""", session_id, assignee_email, assignee_type)
```

##### `human_agents.py`
- [ ] No changes needed (table structure unchanged)

##### `admin_management.py`
- [ ] No changes needed (table structure unchanged)

##### `feedback.py`
- [ ] Remove `update_session_feedback()` calls
- [ ] Update feedback queries to compute session feedback on-the-fly

##### `token_usage.py`
- [ ] Update to read from `llm_providers` table instead of `chatbot_configuration`
- [ ] Update token increment logic

**Changes:**
```python
# OLD: Update chatbot_configuration
await conn.execute("""
    UPDATE chatbot_configuration 
    SET llm_token_used_gemini = llm_token_used_gemini + $1
""", tokens_used)

# NEW: Update llm_providers
await conn.execute("""
    UPDATE llm_providers 
    SET token_used = token_used + $1
    WHERE provider_name = $2
""", tokens_used, 'gemini')
```

#### 2. Chatbot Orchestration Service (`services/chatbot_orchestration/`)

##### `main.py`
- [ ] Update configuration loading to read from new tables
- [ ] Update persona loading from `persona_configurations`
- [ ] Update HIL check to read from `configuration_metadata`

**Changes:**
```python
# OLD: Read HIL setting
hil_enabled = config.get('hil_enabled', True)

# NEW: Read from configuration_metadata
metadata = await conn.fetchrow("SELECT hil_enabled FROM configuration_metadata WHERE id = 1")
hil_enabled = metadata['hil_enabled'] if metadata else True
```

#### 3. Shared Database Module (`shared/db.py`)

- [ ] No changes needed (connection logic unchanged)

### Frontend Changes

#### 1. Configuration API (`src/lib/configuration-api.ts`)

**Files to Update:**

##### `configuration-api.ts`
- [ ] Update `ChatbotConfiguration` interface
- [ ] Update `WidgetConfiguration` interface
- [ ] Update `getChatbotConfig()` response parsing
- [ ] Update `saveChatbotConfig()` request formatting
- [ ] Update `getWidgetConfig()` response parsing
- [ ] Update `saveWidgetConfig()` request formatting

**Changes:**
```typescript
// OLD Interface
interface ChatbotConfiguration {
  admin_emails?: string[];
  human_agents?: string[];
  llm_token_limit_gemini?: number;
  // ...
}

// NEW Interface
interface ChatbotConfiguration {
  // Arrays removed - managed server-side
  hil_enabled?: boolean;
  response_policy?: number;
  notifications?: {
    user_interactions_enabled: boolean;
    error_alerts_enabled: boolean;
    feedback_requests_enabled: boolean;
  };
  security?: {
    response_timeout: number;
    remove_pii: boolean;
    restrict_config: boolean;
  };
  llm_providers?: Array<{
    provider_name: string;
    token_limit: number;
    token_used: number;
  }>;
  persona?: {
    persona_name: string;
    system_prompt: string;
  };
}

interface WidgetConfiguration {
  // suggested_messages removed from here
  display_name: string;
  initial_message: string;
  // ... other fields
  suggested_messages?: string[]; // Still in interface for backward compat, but managed separately
}
```

#### 2. Chat Log Component (`src/pages/ChatLog.tsx`)

- [ ] Update session assignment display logic
- [ ] Update agent status checks
- [ ] Remove session_feedback references (compute from messages)

#### 3. Configuration Pages

##### `src/pages/Configuration.tsx`
- [ ] Update to handle new configuration structure
- [ ] Update form handling for split configuration

##### `src/pages/WidgetConfiguration.tsx`
- [ ] Update suggested messages handling (CRUD operations)

## Data Migration Script

### Migration Steps

1. **Backup existing data**
2. **Create new tables** (run `schema_3nf.sql`)
3. **Migrate data** from old tables to new tables
4. **Verify data integrity**
5. **Update application code**
6. **Deploy backend**
7. **Deploy frontend**
8. **Drop old columns/tables**

### Migration SQL (See `data_migration.sql`)

## Testing Plan

### Unit Tests
- [ ] Test configuration CRUD operations
- [ ] Test session assignment logic
- [ ] Test agent/admin routing
- [ ] Test chat transfer functionality
- [ ] Test feedback aggregation

### Integration Tests
- [ ] Test full chat flow (customer → agent)
- [ ] Test admin fallback routing
- [ ] Test chat transfers
- [ ] Test configuration updates
- [ ] Test widget configuration

### Manual Testing
- [ ] Create new chat session
- [ ] Assign to agent
- [ ] Transfer to admin
- [ ] Submit feedback
- [ ] Update configuration
- [ ] Verify all UI displays correctly

## Rollback Plan

If issues occur:

1. **Stop deployments**
2. **Restore database from backup**
3. **Revert code changes** (git revert)
4. **Redeploy previous version**
5. **Investigate issues**
6. **Fix and retry**

## Deployment Checklist

### Pre-Deployment
- [ ] Backup production database
- [ ] Test migration on staging environment
- [ ] Verify all tests pass
- [ ] Review code changes
- [ ] Prepare rollback plan

### Deployment
- [ ] Put application in maintenance mode
- [ ] Run `drop_all_schema.sql` (if fresh start)
- [ ] Run `schema_3nf.sql`
- [ ] Run `data_migration.sql` (if migrating data)
- [ ] Deploy backend services
- [ ] Deploy frontend
- [ ] Verify health checks
- [ ] Run smoke tests
- [ ] Exit maintenance mode

### Post-Deployment
- [ ] Monitor error logs
- [ ] Monitor performance metrics
- [ ] Verify all features working
- [ ] Check user reports
- [ ] Document any issues

## File Change Summary

### Backend Files (8 files)
1. `services/configuration_service/main.py` - Major changes
2. `services/configuration_service/chat_log.py` - Major changes
3. `services/configuration_service/feedback.py` - Minor changes
4. `services/configuration_service/token_usage.py` - Minor changes
5. `services/chatbot_orchestration/main.py` - Minor changes
6. `sql/drop_all_schema.sql` - New file ✓
7. `sql/schema_3nf.sql` - New file ✓
8. `sql/data_migration.sql` - New file (to create)

### Frontend Files (4 files)
1. `src/lib/configuration-api.ts` - Major changes
2. `src/pages/Configuration.tsx` - Minor changes
3. `src/pages/WidgetConfiguration.tsx` - Minor changes
4. `src/pages/ChatLog.tsx` - Minor changes

## Estimated Timeline

- **Schema Creation**: ✓ Complete
- **Data Migration Script**: 30 minutes
- **Backend Code Updates**: 3-4 hours
- **Frontend Code Updates**: 2-3 hours
- **Testing**: 2-3 hours
- **Deployment**: 1 hour
- **Total**: 8-12 hours

## Risk Assessment

### High Risk Areas
1. Session assignment migration (affects active chats)
2. Configuration migration (affects all features)
3. Data loss during migration

### Mitigation
1. Comprehensive testing on staging
2. Database backups before migration
3. Rollback plan ready
4. Gradual deployment (backend first, then frontend)

## Success Criteria

- [ ] All existing functionality works
- [ ] No data loss
- [ ] Performance maintained or improved
- [ ] All tests pass
- [ ] No critical bugs in production
- [ ] Database follows 3NF principles

## Next Steps

1. Create data migration script
2. Update backend code files
3. Update frontend code files
4. Test on local environment
5. Test on staging environment
6. Deploy to production

---

**Document Version**: 1.0  
**Last Updated**: 2026-01-11  
**Author**: Database Migration Team  
**Status**: Ready for Execution
