# Backend Integration Guide

This guide outlines the steps needed to successfully integrate all the new backend features.

## 📋 Prerequisites

1. **Database Access**: Ensure you have access to your PostgreSQL database
2. **Environment Variables**: Set up all required environment variables
3. **Email Service**: Configure SMTP settings for email notifications
4. **API Keys**: Have Gemini and OpenAI API keys ready

## 🔧 Step 1: Run Database Migrations

Run the SQL migration file to create all necessary tables:

```bash
# Connect to your PostgreSQL database
psql $DATABASE_URL

# Or use your database management tool
# Then run:
\i sql/chatbot_configuration_features.sql
```

**Or** execute the SQL file directly:

```bash
psql $DATABASE_URL -f sql/chatbot_configuration_features.sql
```

This will create:
- `human_agents` table
- `human_agent_sessions` table
- `chat_feedback` table
- `token_usage_cache` table
- Update `chatbot_configuration` table with new columns

## 🔧 Step 2: Install Required Python Packages

Add these packages to `requirements.txt` if not already present:

```txt
jinja2>=3.0.0  # For email templates (optional, if using template rendering)
```

The email service uses Python's built-in `smtplib` and `email` modules, so no additional packages are needed for basic email functionality.

## 🔧 Step 3: Configure Environment Variables

Add these environment variables to your Railway project or `.env` file:

### Email Configuration
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Use app-specific password for Gmail
EMAIL_FROM=noreply@knowledgebot.com
WIDGET_BASE_URL=https://widget.yourdomain.com
```

**Note for Gmail**: You'll need to:
1. Enable 2-factor authentication
2. Generate an "App Password" (not your regular password)
3. Use the app password in `SMTP_PASSWORD`

### LLM API Keys (if not already set)
```env
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key
```

## 🔧 Step 4: Update API Gateway Routes

The new endpoints are automatically included in the configuration service. However, you need to ensure the API Gateway routes them correctly.

### Routes to Add/Verify in API Gateway:

1. **Human Agent Endpoints** (in configuration service):
   - `POST /api/v1/admin/human-agents` → Configuration Service
   - `POST /api/v1/admin/human-agents/confirm` → Configuration Service
   - `DELETE /api/v1/admin/human-agents/{email}` → Configuration Service

2. **Feedback Endpoint**:
   - `POST /api/v1/feedback` → Configuration Service

3. **Token Usage Endpoint**:
   - `GET /api/v1/admin/token-usage` → Configuration Service

4. **Chat Endpoint** (updated):
   - `POST /api/v1/chat` → Chatbot Orchestration Service
   - Now accepts `system_prompt` and `response_policy` parameters

### API Gateway Configuration

If using Railway, the API Gateway should automatically route based on service URLs. Verify these environment variables are set:

```env
CONFIGURATION_SERVICE_URL=http://configuration-service:8004
CHATBOT_ORCHESTRATION_URL=http://chatbot-orchestration:8003
```

## 🔧 Step 5: Test the Integration

### 1. Test Human Agent Email Flow

```bash
# Add human agents
curl -X POST http://your-api-gateway/api/v1/admin/human-agents \
  -H "Content-Type: application/json" \
  -d '{"emails": ["test@example.com"]}'

# Check email inbox for confirmation link
# Then confirm the agent
curl -X POST http://your-api-gateway/api/v1/admin/human-agents/confirm \
  -H "Content-Type: application/json" \
  -d '{"token": "confirmation-token-from-email"}'
```

### 2. Test Feedback Endpoint

```bash
curl -X POST http://your-api-gateway/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "msg-123",
    "session_id": "session-456",
    "feedback": "positive"
  }'
```

### 3. Test Token Usage Endpoint

```bash
curl http://your-api-gateway/api/v1/admin/token-usage
```

### 4. Test Chat with System Prompt and Response Policy

```bash
curl -X POST http://your-api-gateway/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the product catalog?",
    "system_prompt": "You are a helpful sales assistant.",
    "response_policy": 50
  }'
```

## 🔧 Step 6: Token Usage API Integration (Optional)

The token usage endpoints currently return cached values from the database. To get real-time usage:

### For Gemini:
- Use Google Cloud Billing API
- Or track usage manually by recording token counts from API responses

### For OpenAI:
- Use OpenAI Dashboard API (if available)
- Or track usage manually by recording token counts from API responses

You can update the `token_usage.py` file to integrate with these APIs.

## 🔧 Step 7: WebSocket for Human Agent Chat (Future)

The WebSocket implementation for human agent chat is not included in this initial release. To implement:

1. Set up a WebSocket server (e.g., using FastAPI WebSockets)
2. Create connection management for customer-agent pairs
3. Route messages between customer and agent
4. Update frontend to connect to WebSocket endpoint

## 📝 Database Schema Notes

### Migration from Deepseek to OpenAI

The migration script automatically converts `deepseek` references to `openai` in the `llm_tokens` JSONB column. If you're using a different column structure, you may need to adjust the migration.

### Token Usage Caching

The `token_usage_cache` table is optional. You can populate it by:
1. Calling the Gemini/OpenAI APIs periodically
2. Storing the results in the cache table
3. Returning cached values from the endpoint

## 🐛 Troubleshooting

### Email Not Sending

1. Check SMTP credentials are correct
2. Verify SMTP port (587 for TLS, 465 for SSL)
3. For Gmail, ensure you're using an App Password, not your regular password
4. Check firewall/network restrictions

### Database Connection Issues

1. Verify `DATABASE_URL` or `RAILWAY_POSTGRES_URL` is set
2. Check database is accessible from your services
3. Verify database user has CREATE TABLE permissions

### Endpoints Not Found

1. Verify API Gateway routes are configured correctly
2. Check service URLs in environment variables
3. Ensure services are running and healthy

## ✅ Verification Checklist

- [ ] Database migrations run successfully
- [ ] All environment variables set
- [ ] Email service configured and tested
- [ ] Human agent endpoints working
- [ ] Feedback endpoint working
- [ ] Token usage endpoint working
- [ ] Chat endpoint accepts system_prompt and response_policy
- [ ] Frontend can connect to all endpoints

## 📚 Additional Resources

- See `BACKEND_REQUIREMENTS.md` for detailed API specifications
- Check service logs for debugging: `railway logs`
- Test endpoints using Postman or curl

## 🚀 Deployment

After completing all steps:

1. Commit all changes to your repository
2. Deploy to Railway (or your hosting platform)
3. Verify all services are running
4. Test endpoints from production
5. Monitor logs for any errors

---

**Need Help?** Check the service logs or review the error messages in the API responses.

