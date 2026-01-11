# Database Schema Normalization Analysis

## Current Schema Issues (Violations of 3NF)

### 1. **chatbot_configuration table**
**Issues:**
- `admin_emails` array - should be in separate table (already have `admins` table)
- `human_agents` array - should be in separate table (already have `human_agents` table)
- Mixed configuration types (notifications, security, LLM tokens) - should be separate tables
- `llm_token_limit_gemini`, `llm_token_used_gemini`, etc. - should be in `token_usage_cache` or separate table

**Violations:**
- 1NF: Arrays violate atomicity
- 2NF: Partial dependencies (LLM tokens depend on provider, not config)
- 3NF: Transitive dependencies (notification settings are independent)

### 2. **widget_configuration table**
**Issues:**
- `suggested_messages` array - violates 1NF
- All settings in one table - could be normalized by category

**Violations:**
- 1NF: Array violates atomicity

### 3. **chat_sessions table**
**Issues:**
- `metadata` JSONB - unstructured data, but acceptable for flexibility
- `session_feedback` - derived from `chat_feedback` table (should be computed)

**Violations:**
- 3NF: `session_feedback` is derivable from `chat_feedback`

### 4. **human_agent_sessions table**
**Issues:**
- Missing proper relationship to `chat_sessions`
- `customer_session_id` should be FK to `chat_sessions.session_id`

**Violations:**
- Referential integrity not enforced

### 5. **Redundant/Missing Tables**
**Issues:**
- No separate table for notification settings
- No separate table for security settings
- No separate table for LLM provider configurations
- No separate table for widget suggested messages
- No separate table for session assignments (agent/admin to session)

## Proposed 3NF Schema

### New Tables Needed:

1. **notification_settings** - Extract from chatbot_configuration
2. **security_settings** - Extract from chatbot_configuration
3. **llm_providers** - Extract LLM token info
4. **widget_suggested_messages** - Extract from widget_configuration
5. **session_assignments** - Properly link sessions to agents/admins
6. **configuration_metadata** - Single row config table

### Tables to Modify:

1. **chatbot_configuration** - Remove arrays and extracted fields
2. **widget_configuration** - Remove arrays
3. **chat_sessions** - Remove derived fields
4. **human_agent_sessions** - Add proper FK constraints

### Tables to Keep As-Is:

1. **users** - Already normalized
2. **admins** - Already normalized
3. **human_agents** - Already normalized
4. **chat_messages** - Acceptable (JSONB for sources is flexible)
5. **file_uploads** - Acceptable
6. **scraped_websites** - Acceptable
7. **api_usage** - Acceptable
8. **metrics** - Acceptable

## Migration Strategy

1. Create new normalized tables
2. Migrate data from old structure to new
3. Update application code to use new schema
4. Test thoroughly
5. Drop old columns/constraints
6. Add new constraints

## Backward Compatibility

To maintain zero downtime:
1. Add new tables alongside old structure
2. Dual-write to both old and new structures
3. Migrate existing data
4. Switch reads to new structure
5. Remove old structure
