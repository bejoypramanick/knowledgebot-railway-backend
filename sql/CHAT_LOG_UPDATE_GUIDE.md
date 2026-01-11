# Backend Code Update Guide - chat_log.py

## Overview
This document details all changes needed in `chat_log.py` to work with the new 3NF schema.

## Key Changes

### 1. Table Name Changes
- `human_agent_sessions` → `session_assignments`
- Column mappings:
  - `customer_session_id` → `session_id` (now UUID FK to chat_sessions.id)
  - `agent_email` → `assignee_email`
  - Add `assignee_type` ('agent' or 'admin')
  - `status` values remain similar but add 'transferred'
  - `connected_at` → `assigned_at`

### 2. Query Pattern Changes

#### OLD Pattern:
```sql
SELECT * FROM human_agent_sessions 
WHERE customer_session_id = $1
```

#### NEW Pattern:
```sql
SELECT sa.* FROM session_assignments sa
INNER JOIN chat_sessions cs ON sa.session_id = cs.id
WHERE cs.session_id = $1
```

### 3. Insert Pattern Changes

#### OLD Pattern:
```sql
INSERT INTO human_agent_sessions (customer_session_id, agent_email, status, connected_at)
VALUES ($1, $2, 'connected', NOW())
```

#### NEW Pattern:
```sql
INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at)
VALUES (
    (SELECT id FROM chat_sessions WHERE session_id = $1),
    $2,
    CASE WHEN EXISTS (SELECT 1 FROM admins WHERE email = $2 AND status = 'confirmed') 
         THEN 'admin' ELSE 'agent' END,
    'active',
    NOW()
)
```

### 4. Update Pattern Changes

#### OLD Pattern:
```sql
UPDATE human_agent_sessions 
SET status = 'ended', ended_at = NOW()
WHERE customer_session_id = $1
```

#### NEW Pattern:
```sql
UPDATE session_assignments 
SET status = 'ended', ended_at = NOW()
WHERE session_id = (SELECT id FROM chat_sessions WHERE session_id = $1)
```

### 5. Join Pattern Changes

#### OLD Pattern:
```sql
FROM chat_sessions cs
INNER JOIN human_agent_sessions has ON cs.session_id = has.customer_session_id
WHERE has.agent_email = $1
```

#### NEW Pattern:
```sql
FROM chat_sessions cs
INNER JOIN session_assignments sa ON cs.id = sa.session_id
WHERE sa.assignee_email = $1
```

## Functions to Update

### 1. `get_agent_online_status()` (Line ~150)
- Update query to use `session_assignments`
- Check for recent `assigned_at` instead of `connected_at`

### 2. `assign_chat_to_agent()` (Line ~220)
- Update INSERT to use `session_assignments`
- Add `assignee_type` determination logic
- Use `session_id` UUID instead of `customer_session_id` string

### 3. `get_agent_chat_count()` (Line ~280)
- Update COUNT query to use `session_assignments`
- Filter by `assignee_email` instead of `agent_email`

### 4. `/chat-sessions` endpoint (Line ~500)
- Update heartbeat logic
- Update session queries to join with `session_assignments`

### 5. `/chat-sessions/{session_id}/messages` endpoint (Line ~640)
- Update assignment check queries
- Update JOIN clauses

### 6. `/chat-sessions` GET endpoint (Line ~700)
- Update all JOINs to use `session_assignments`
- Update column references

### 7. `/agents/online` endpoint (Line ~411)
- Update active session count query

### 8. `/chat-sessions/{session_id}/transfer` endpoint (Line ~1097)
- Update assignment queries
- Add `assignee_type` logic

## Configuration-Related Changes

### Remove from queries:
- `chatbot_configuration.admin_emails`
- `chatbot_configuration.human_agents`
- `chatbot_configuration.hil_enabled` (move to `configuration_metadata`)

### Add new queries for:
- `configuration_metadata.hil_enabled`
- Join with `admins` and `human_agents` tables directly

## Testing Checklist

After making changes, test:
- [ ] Agent can see assigned chats
- [ ] Admin can see assigned chats
- [ ] Chat assignment works
- [ ] Chat transfer works
- [ ] Agent online status detection
- [ ] Active chat counting
- [ ] Session heartbeats
- [ ] WebSocket messaging

## Migration Notes

1. All `customer_session_id` references must be converted to UUID lookups
2. All `agent_email` references become `assignee_email`
3. Add `assignee_type` determination in all INSERT/UPDATE operations
4. Status 'connected' becomes 'active'
5. `connected_at` becomes `assigned_at`
