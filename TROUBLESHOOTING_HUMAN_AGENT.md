# Troubleshooting: Human Agent Connection Errors

## Error Message
"I encountered an error while trying to connect you to a human agent. Please try again later or continue chatting with me."

## Common Causes and Solutions

### 1. No Human Agents Configured
**Error Message**: "No human agents are configured. Please contact your administrator to set up human agents."

**Solution**:
- Go to Admin Panel → Human Agents
- Add and confirm at least one human agent
- Ensure the agent's status is 'confirmed'

**Check**:
```sql
SELECT email, status FROM human_agents WHERE status = 'confirmed';
```

### 2. No Agents Online
**Error Message**: "No human agents are currently online. Agents need to access the chat log to be marked as online. Please try again later."

**Solution**:
- Agents must access the Chat Log page to be marked as "online"
- An agent is considered online if they've accessed the chat log within the last 30 minutes
- Have agents log in and navigate to the Chat Log page
- The system creates a "heartbeat" entry when agents access the chat log

**Check**:
```sql
-- Check for recent agent activity (heartbeat)
SELECT DISTINCT agent_email, MAX(connected_at) as last_activity
FROM human_agent_sessions
WHERE customer_session_id LIKE 'heartbeat_%'
AND connected_at > NOW() - INTERVAL '30 minutes'
GROUP BY agent_email;
```

### 3. Human in the Loop (HIL) Disabled
**Error Message**: "Human agent support is currently disabled"

**Solution**:
- Go to Admin Panel → Chatbot Configuration
- Enable "Human in the Loop" (HIL)
- Ensure `hil_enabled` is set to `true` in `chatbot_configuration` table

**Check**:
```sql
SELECT hil_enabled FROM chatbot_configuration WHERE admin_user = 'GLOBISTAAN';
```

### 4. Database Connection Issues
**Symptoms**: Generic error message, no specific details

**Solution**:
- Check Railway logs for database connection errors
- Verify database credentials are correct
- Ensure database is accessible from the configuration service

### 5. API Gateway Routing Issues
**Symptoms**: Network errors, 404/500 errors

**Solution**:
- Verify API Gateway is routing `/api/v1/chat/{session_id}/request-human-agent` correctly
- Check that configuration service is running and accessible
- Verify CORS settings allow requests from frontend

## Debugging Steps

### 1. Check Browser Console
Open browser DevTools (F12) → Console tab
Look for detailed error logs that show:
- HTTP status code
- Error response from API
- Network request details

### 2. Check Backend Logs
In Railway, check the configuration service logs for:
- "No confirmed human agents available"
- "No online agents available"
- Database connection errors
- Load balancing errors

### 3. Verify Agent Setup
```sql
-- Check all agents
SELECT email, status, created_at, confirmed_at 
FROM human_agents 
ORDER BY created_at DESC;

-- Check agent online status
SELECT 
    ha.email,
    ha.status,
    MAX(has.connected_at) as last_activity,
    CASE 
        WHEN MAX(has.connected_at) > NOW() - INTERVAL '30 minutes' THEN 'ONLINE'
        ELSE 'OFFLINE'
    END as online_status
FROM human_agents ha
LEFT JOIN human_agent_sessions has ON ha.email = has.agent_email
WHERE ha.status = 'confirmed'
GROUP BY ha.email, ha.status;
```

### 4. Test the Endpoint Directly
```bash
curl -X POST https://your-api-gateway.up.railway.app/api/v1/chat/{session_id}/request-human-agent \
  -H "Content-Type: application/json"
```

## Quick Fix Checklist

- [ ] At least one human agent exists with status='confirmed'
- [ ] Agent has logged in and accessed Chat Log page (creates heartbeat)
- [ ] HIL is enabled in chatbot configuration
- [ ] Database is accessible and connection is working
- [ ] API Gateway is routing requests correctly
- [ ] Check browser console for detailed error messages

## How Agent Online Status Works

An agent is marked as "online" when:
1. They access the Chat Log page (creates a heartbeat entry)
2. The heartbeat entry is within the last 30 minutes
3. OR they have recent activity in assigned chats

The heartbeat is created automatically when:
- Agent navigates to Chat Log page
- Agent calls `/api/v1/admin/agents/heartbeat` endpoint
- Agent accesses `/api/v1/admin/chat-sessions` endpoint

## Testing Agent Connection

1. **As Admin**: Go to Human Agents section, add and confirm an agent
2. **As Agent**: Log in with agent credentials, navigate to Chat Log page
3. **As Customer**: Try to connect to human agent in chatbot
4. **Check Logs**: Verify assignment happened in backend logs
