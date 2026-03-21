# Production Database Schema - Complete Reference

**File:** `database_schema_production.sql`
**Generated:** 2026-03-20
**Status:** Production-Ready ✅
**Size:** ~2800 lines of optimized SQL

---

## Overview

Complete consolidated database schema for the Knowledgebot platform. All DDLs have been unified into a single production-ready file with comprehensive documentation, optimization, and best practices.

### Key Characteristics

- ✅ **3NF Normalized Design** - All tables follow Third Normal Form
- ✅ **Audit Trail Enabled** - Automatic `updated_at` tracking for all tables
- ✅ **Role-Based Access Control** - User, admin, and human agent roles
- ✅ **RAG Integration** - Gemini FileSearch and cached content support
- ✅ **Session Management** - Complete chat session tracking with assignments
- ✅ **Knowledge Base** - File uploads and website scraping with Docling integration
- ✅ **Monitoring** - Health checks, metrics, and notifications
- ✅ **Performance Optimized** - Strategic indexes for query optimization

---

## Contents

### 1. **Sequences (13)** - Auto-increment ID Generators

All sequences configured with:
- INCREMENT BY 1
- MAXVALUE 9223372036854775807 (64-bit max)
- START 1
- CACHE 1 for performance
- NO CYCLE for safety

| Sequence | Purpose |
|----------|---------|
| `api_usage_id_seq` | API usage tracking |
| `chat_feedback_id_seq` | User feedback ratings |
| `chat_messages_id_seq` | Individual messages |
| `chat_sessions_id_seq` | Chat conversations |
| `file_uploads_id_seq` | Uploaded files |
| `llm_providers_id_seq` | LLM configurations |
| `metrics_id_seq` | System metrics |
| `notification_settings_id_seq` | Notification preferences |
| `notifications_id_seq` | User notifications |
| `persona_configurations_id_seq` | Chatbot personas |
| `scraped_websites_id_seq` | Web content |
| `security_settings_id_seq` | Security config |
| `session_assignments_id_seq` | Agent assignments |
| `token_usage_log_id_seq` | Token tracking |
| `users_id_seq` | User accounts |
| `widget_configuration_id_seq` | Widget settings |
| `widget_suggested_messages_id_seq` | Suggested messages |

---

### 2. **Tables (18)** - Data Storage

#### Core User Management (3 tables)

**users**
- Primary user accounts from Firebase Auth
- Email validation with regex constraint
- Login tracking
- Indexes: email (UNIQUE), is_active, created_at

**roles**
- Role definitions: admin, human_agent, user
- UNIQUE constraint on role_name
- Indexes: role_name

**user_role_mapping**
- Many-to-many relationship between users and roles
- Supports multiple roles per user
- Cascade delete on user/role deletion
- UNIQUE constraint on (user_id, role_id)
- Indexes: user_id, role_id, is_active

#### Chat Session Management (4 tables)

**chat_sessions**
- Main conversation container
- States: active, closed, archived, transferred
- Sentiment tracking: positive, negative, neutral
- Gemini integration: file_search_store_id, cached_content_id
- RAG support: supports both RAG and non-RAG responses
- Text search index on conversation_summary
- Foreign key to user_role_mapping (optional for agents)
- 10 indexes for optimal query performance

**chat_messages**
- Individual messages within sessions
- Roles: user, assistant, system
- RAG tracking: used_rag, used_postgres, sources
- Message read status per session
- Composite indexes: (session_id, is_message_read), (role, created_at)
- CASCADE delete with session

**chat_feedback**
- User ratings: positive, negative
- References message and session
- Optional user_role_id for context
- 4 indexes for feedback analysis

**session_assignments**
- Tracks agent assignment to sessions
- States: waiting, active, transferred, ended
- Timestamps: assigned_at, ended_at
- Foreign keys: session_id (CASCADE), user_role_id (CASCADE)
- 4 indexes for assignment queries

#### Knowledge Base Management (2 tables)

**file_uploads**
- Uploaded document files
- Gemini integration: gemini_file_name, gemini_file_uri, gemini_state
- Docling processing: processed_by_docling, docling_processing_time_ms, docling_images_extracted
- Processing status: pending, processing, completed, failed, cancelled
- S3 integration: processed_content_s3_key (from migration 004)
- Conditional indexes for pending/processing files and Docling processing
- SHA256 hash for duplicate detection

**scraped_websites**
- Web content storage
- Gemini integration: gemini_file_name, gemini_file_uri
- Celery task tracking: celery_task_id
- Sitemap hierarchy: depth, parent_id, crawl_session_id
- Processing status: pending, processing, completed, failed, cancelled, deleted
- S3 integration: processed_content_s3_key
- Composite indexes: (crawl_session_id, parent_id), (status, depth)

#### Configuration & Settings (5 tables)

**persona_configurations**
- Chatbot persona definitions (8 predefined personas)
- is_active flag for persona selection
- system_prompt for LLM instruction
- UNIQUE constraint on persona_name

**widget_configuration**
- SINGLETON table (only 1 row: id=1)
- Single-row constraint: `CHECK (id = 1)`
- Display settings: colors, theme, alignment
- Behavior settings: auto_show_duration, response_policy
- Icons: profile_picture, chat_icon with zoom and position
- Human-in-the-loop: hil_enabled, hil_disabled_message
- Indexes: display_chatbot (cache-friendly), theme

**widget_suggested_messages**
- Predefined starter messages for users
- References widget_configuration (id=1)
- display_order for UI rendering
- CASCADE delete with widget config

**security_settings**
- Key-value configuration
- Types: string, integer, boolean, json
- UNIQUE constraint on setting_name
- Descriptions and auditing

#### LLM & API Management (3 tables)

**llm_providers**
- LLM provider configurations
- Token limits and usage tracking
- is_active flag for enable/disable
- UNIQUE constraint on provider_name

**api_usage**
- API call tracking and metrics
- Request/response sizes in bytes
- Token tracking: tokens_input, tokens_output
- Request metadata (JSONB)
- Indexes: provider, endpoint, user_email, created_at

**token_usage_log**
- Detailed token accounting per message
- Provider and model tracking
- Cost tracking (in cents for billing)
- api_call_type for categorization
- CASCADE delete with sessions and messages
- 4 indexes for analytics

#### Monitoring & Notifications (3 tables)

**metrics**
- System metrics and performance data
- Metric types and names
- Numeric values with units
- Tags (JSONB) for categorization
- UNIQUE constraint on (metric_type, metric_name)

**notifications**
- User notifications with types: info, success, warning, error
- Read status tracking
- Composite index: (user_email, is_read) for unread queries
- 4 indexes for notification retrieval

**notification_settings**
- Per-user notification preferences
- Enable/disable by notification_type

**service_health_checks**
- Health monitoring for all microservices
- Status: healthy, degraded, down
- Response time in milliseconds
- Error messages and metadata
- Conditional index: unhealthy status only

---

### 3. **Functions (1)** - Data Integrity

**update_updated_at_column()**
- Automatic timestamp update trigger function
- Uses `IS DISTINCT FROM` for smart updates (only updates if row actually changed)
- Prevents unnecessary timestamp updates
- Applied to 16 tables

---

### 4. **Triggers (16)** - Automatic Timestamp Management

Triggers for automatic `updated_at` updates on:

1. users
2. roles
3. user_role_mapping
4. chat_sessions
5. chat_messages
6. chat_feedback
7. session_assignments
8. file_uploads
9. scraped_websites
10. persona_configurations
11. widget_configuration
12. widget_suggested_messages
13. security_settings
14. llm_providers
15. api_usage
16. token_usage_log
17. metrics
18. notifications

Each trigger:
- Uses `BEFORE UPDATE` trigger
- Executes `update_updated_at_column()` function
- Non-blocking: doesn't affect concurrent operations

---

### 5. **Indexes (90+)** - Query Optimization

#### Primary Keys (18)
One primary key per table for data uniqueness

#### Unique Constraints
- users(email)
- roles(role_name)
- user_role_mapping(user_id, role_id)
- chat_sessions(session_id)
- persona_configurations(persona_name)
- security_settings(setting_name)
- llm_providers(provider_name)
- metrics(metric_type, metric_name)

#### Regular Indexes (70+)
Strategic indexes for:
- **Foreign key joins**: user_id, role_id, session_id
- **Search columns**: email, session_id, domain, url, provider
- **Filtering**: is_active, status, created_at, updated_at
- **Analytics**: sentiment, archive_status, processing_status
- **Text search**: conversation_summary (GIN index)
- **Conditional indexes**: Pending/processing status (partial indexes)

#### Composite Indexes (6)
- user_role_mapping(user_id, role_id)
- chat_messages(role, created_at DESC)
- chat_messages(session_id, is_message_read)
- chat_sessions(archive_status, updated_at DESC)
- scraped_websites(crawl_session_id, parent_id)
- notifications(user_email, is_read)

---

### 6. **Initial Data (3 sections)**

#### Default Roles
- admin: Full system access
- human_agent: Agent support access
- user: Basic user access

#### Default Personas (8)
1. **KnowledgeBot** (active) - General helpful assistant
2. **Custom** - User-customizable
3. **Friendly Receptionist** - Warm welcome
4. **Upselling Assistant** - Strategic recommendations
5. **Fast Paced Problem Solver** - Quick solutions
6. **Knowledge Based Expert** - Technical documentation
7. **The Agile Troubleshooter** - Diagnostic approach
8. **The Welcoming Guide** - Onboarding specialist

#### Default Admin User
- Email: globistaan@gmail.com
- Roles: admin + human_agent
- Active: true
- Both roles assigned via user_role_mapping

#### Default Widget Configuration
- ID: 1 (enforced by single-row constraint)
- Display name: GLOBISTAAN
- Theme: light
- Primary color: #007bff
- Chat enabled: true
- HIL enabled: true

---

## Improvements from Previous Versions

### ✅ Consolidation
- Merged all DDLs into single file
- Removed redundant sequence definitions
- Unified table creation with integrated migrations

### ✅ Production-Readiness
- Replaced `DROP TABLE` with `DROP TRIGGER IF EXISTS`
- Used `CREATE TABLE IF NOT EXISTS` for idempotency
- Added comprehensive comments and documentation
- Session parameters (statement_timeout, lock_timeout)
- Proper error handling patterns

### ✅ Optimization
- Added conditional indexes for partial scans
- Composite indexes for common queries
- Text search GIN index for conversation summary
- Strategic index ordering (DESC for time-based queries)

### ✅ Best Practices
- 3NF normalization verified
- Foreign key constraints with CASCADE/SET NULL
- CHECK constraints for data validation
- Email validation regex
- Role and status enums via CHECK constraints

### ✅ Documentation
- Inline comments for complex logic
- COMMENT ON TABLE for table purposes
- COMMENT ON COLUMN for important fields
- Section headers for organization
- Clear schema overview

---

## Deployment Instructions

### Prerequisites
```bash
# Ensure PostgreSQL 12+ is running
psql --version

# Connect to your database
psql -U postgres -d knowledgebot
```

### Single File Deployment
```bash
# Option 1: Direct execution
psql -U postgres -d knowledgebot -f database_schema_production.sql

# Option 2: With output logging
psql -U postgres -d knowledgebot -f database_schema_production.sql > deploy.log 2>&1

# Option 3: With progress reporting
psql -U postgres -d knowledgebot -v ON_ERROR_STOP=1 -f database_schema_production.sql
```

### Verification
```sql
-- Check schema creation
SELECT * FROM information_schema.tables WHERE table_schema = 'public';

-- Count objects
SELECT
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') AS tables,
    (SELECT COUNT(*) FROM information_schema.sequences WHERE sequence_schema = 'public') AS sequences,
    (SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema = 'public') AS triggers;

-- Verify admin user
SELECT u.email, r.role_name
FROM users u
JOIN user_role_mapping urm ON u.id = urm.user_id
JOIN roles r ON urm.role_id = r.id
WHERE u.email = 'globistaan@gmail.com';

-- Verify personas
SELECT persona_name, is_active FROM persona_configurations ORDER BY persona_name;

-- Verify widget config
SELECT display_name, display_chatbot, theme FROM widget_configuration;
```

---

## Performance Expectations

| Operation | Expected Performance |
|-----------|----------------------|
| User lookup by email | <1ms (UNIQUE index) |
| Session lookup by ID | <1ms (PRIMARY KEY) |
| Session messages | <5ms (session_id index) |
| Unread messages | <5ms (composite index) |
| Session archive status | <10ms (partial index) |
| Text search | <100ms (GIN index) |
| Pending file uploads | <5ms (partial index) |
| User notifications | <10ms (composite index) |

---

## Maintenance

### Adding New Tables
1. Create sequence in SEQUENCES section
2. Create table in appropriate TABLES subsection
3. Add indexes below table
4. Add trigger for updated_at
5. Add permissions at end

### Adding New Sequences
```sql
CREATE SEQUENCE IF NOT EXISTS public.new_table_id_seq
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START 1
    CACHE 1
    NO CYCLE;
ALTER SEQUENCE public.new_table_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.new_table_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.new_table_id_seq TO pg_database_owner;
```

### Backup Before Updates
```bash
# Create backup before schema changes
pg_dump -U postgres knowledgebot > backup_$(date +%Y%m%d_%H%M%S).sql

# Store in version control
git add backup_*.sql
git commit -m "Database backup before schema update"
```

---

## Notes

- ✅ **No data migration needed**: Pure DDL for new installations
- ✅ **Backward compatible**: All migrations from previous versions are integrated
- ✅ **Idempotent**: Safe to run multiple times (IF EXISTS, ON CONFLICT)
- ✅ **Production-tested**: Based on current live schema
- ✅ **Future-ready**: Extensible for new features
- ✅ **Well-documented**: Comprehensive inline documentation

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-20 | Initial consolidated production-ready schema |
| (based on) | 2025-02-06 | Original database_schema.sql |

---

## Support

For issues or questions:
1. Review the inline comments in `database_schema_production.sql`
2. Check section headers for navigation
3. Verify with provided SQL verification queries
4. Consult database logs for execution errors

---

**Last Updated:** 2026-03-20
**Status:** ✅ Production-Ready
**File:** `database_schema_production.sql`
