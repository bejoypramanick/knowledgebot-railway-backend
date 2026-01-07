# Backend Requirements for Chatbot Configuration Features

This document outlines the backend requirements for implementing the new chatbot configuration features.

## 1. Human Agent Email Confirmation Flow

### Database Schema
```sql
CREATE TABLE human_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'removed'
    confirmation_token VARCHAR(255) UNIQUE,
    widget_link VARCHAR(500),
    auto_generated_password VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    removed_at TIMESTAMP
);

CREATE INDEX idx_human_agents_email ON human_agents(email);
CREATE INDEX idx_human_agents_status ON human_agents(status);
CREATE INDEX idx_human_agents_token ON human_agents(confirmation_token);
```

### API Endpoints

#### 1.1 Save Human Agents
**POST** `/api/v1/admin/human-agents`

**Request Body:**
```json
{
  "emails": ["agent1@example.com", "agent2@example.com"]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Confirmation emails sent to agents",
  "agents": [
    {
      "email": "agent1@example.com",
      "status": "pending",
      "confirmation_token": "abc123..."
    }
  ]
}
```

**Backend Logic:**
1. For each email in the request:
   - Check if agent already exists
   - If new: Generate confirmation token, create record with status='pending'
   - If existing and confirmed: Keep as is
   - If existing and pending: Resend confirmation email
2. Send confirmation email to each new/pending agent
3. Email should contain:
   - Confirmation link with token
   - Instructions to confirm their account

#### 1.2 Confirm Human Agent
**POST** `/api/v1/admin/human-agents/confirm`

**Request Body:**
```json
{
  "token": "abc123..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Agent confirmed successfully",
  "agent": {
    "email": "agent1@example.com",
    "widget_link": "https://widget.example.com/agent/unique-id",
    "password": "auto-generated-password"
  }
}
```

**Backend Logic:**
1. Validate token
2. Generate unique widget link (short URL or unique ID)
3. Generate auto password (secure random string)
4. Update agent status to 'confirmed'
5. Send email with:
   - Widget link
   - Auto-generated password
   - Login instructions

#### 1.3 Remove Human Agent
**DELETE** `/api/v1/admin/human-agents/{email}`

**Response:**
```json
{
  "success": true,
  "message": "Agent removed successfully"
}
```

**Backend Logic:**
1. Update agent status to 'removed'
2. Set removed_at timestamp
3. Send removal notification email
4. Optionally revoke widget access

### Email Templates

#### Confirmation Email
```
Subject: Confirm Your Human Agent Account

Hello,

You have been added as a human agent for the KnowledgeBot chatbot system.

Please confirm your account by clicking the link below:
[Confirmation Link]

If you did not request this, please ignore this email.

Best regards,
KnowledgeBot Team
```

#### Confirmation Success Email
```
Subject: Your Human Agent Account is Ready

Hello,

Your account has been confirmed. You can now access the chatbot widget.

Widget Link: [Unique Widget Link]
Password: [Auto-generated Password]

Please log in and change your password after first login.

Best regards,
KnowledgeBot Team
```

#### Removal Email
```
Subject: Human Agent Access Removed

Hello,

Your access as a human agent has been removed from the KnowledgeBot system.

If you believe this is an error, please contact the administrator.

Best regards,
KnowledgeBot Team
```

## 2. Human Agent WebSocket Connection

### WebSocket Endpoint
**WS** `/ws/human-agent`

### Connection Flow
1. Customer clicks "Connect me to a human agent"
2. Frontend sends message to backend via regular API
3. Backend creates a "human agent request" in database
4. Backend notifies available human agents via WebSocket
5. When agent accepts, establish WebSocket connection between customer and agent
6. Messages flow through backend WebSocket server

### Database Schema
```sql
CREATE TABLE human_agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_session_id VARCHAR(255) NOT NULL,
    agent_email VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'waiting', -- 'waiting', 'connected', 'ended'
    created_at TIMESTAMP DEFAULT NOW(),
    connected_at TIMESTAMP,
    ended_at TIMESTAMP,
    FOREIGN KEY (agent_email) REFERENCES human_agents(email)
);

CREATE INDEX idx_human_agent_sessions_customer ON human_agent_sessions(customer_session_id);
CREATE INDEX idx_human_agent_sessions_agent ON human_agent_sessions(agent_email);
CREATE INDEX idx_human_agent_sessions_status ON human_agent_sessions(status);
```

### WebSocket Message Format

#### Customer to Agent
```json
{
  "type": "customer_message",
  "session_id": "customer-session-id",
  "message": "Hello, I need help",
  "timestamp": "2025-01-06T12:00:00Z"
}
```

#### Agent to Customer
```json
{
  "type": "agent_message",
  "session_id": "customer-session-id",
  "agent_email": "agent@example.com",
  "message": "How can I help you?",
  "timestamp": "2025-01-06T12:00:01Z"
}
```

#### Agent Status Updates
```json
{
  "type": "agent_status",
  "status": "available" | "busy" | "offline",
  "agent_email": "agent@example.com"
}
```

## 3. Feedback Recording

### Database Schema
```sql
CREATE TABLE chat_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    feedback_type VARCHAR(20) NOT NULL, -- 'positive', 'negative'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chat_feedback_message ON chat_feedback(message_id);
CREATE INDEX idx_chat_feedback_session ON chat_feedback(session_id);
CREATE INDEX idx_chat_feedback_type ON chat_feedback(feedback_type);
```

### API Endpoint
**POST** `/api/v1/feedback`

**Request Body:**
```json
{
  "message_id": "message-123",
  "session_id": "session-456",
  "feedback": "positive" | "negative"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Feedback recorded"
}
```

## 4. LLM Token Usage API

### API Endpoint
**GET** `/api/v1/admin/token-usage`

**Response:**
```json
{
  "gemini": {
    "used": 15000,
    "available": 20000,
    "limit": 20000
  },
  "openai": {
    "used": 50000,
    "available": 150000,
    "limit": 150000
  }
}
```

### Backend Logic
1. Call Gemini API to get usage statistics
   - Use Google Cloud API: `https://generativelanguage.googleapis.com/v1beta/models?key=API_KEY`
   - Or use billing API to get token usage
2. Call OpenAI API to get usage statistics
   - Use OpenAI Usage API: `https://api.openai.com/v1/usage`
   - Requires API key with billing access
3. Return combined statistics

### Database Schema (Optional - for caching)
```sql
CREATE TABLE token_usage_cache (
    provider VARCHAR(50) PRIMARY KEY, -- 'gemini', 'openai'
    used BIGINT NOT NULL,
    available BIGINT NOT NULL,
    limit_value BIGINT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW()
);
```

## 5. Response Policy Implementation

The response policy (0-100) should affect how the LLM generates responses:

- **0-30 (Flexible)**: Allow more creative, general responses. Less strict adherence to knowledge base.
- **31-70 (Balanced)**: Default behavior. Balance between knowledge base and general knowledge.
- **71-100 (Strict)**: Strictly adhere to knowledge base. Only use information from provided sources.

### Implementation in RAG Query
The `response_policy` parameter should be passed to the LLM API call and used to adjust:
- Temperature (lower for strict, higher for flexible)
- System prompt instructions
- Source relevance weighting

## 6. System Prompt Appending

### Current Behavior
The system prompt should be built as:
```
[Default System Prompt]

[Persona Prompt (if selected)]

[Custom System Prompt (user input)]
```

### API Integration
The `/api/v1/chat` endpoint should accept:
```json
{
  "message": "user query",
  "system_prompt": "Complete system prompt (default + persona + custom)",
  "response_policy": 30
}
```

The backend should use this system prompt when calling the LLM API.

## 7. Database Updates for Configuration

### Update chatbot_configurations table
```sql
ALTER TABLE chatbot_configurations 
ADD COLUMN IF NOT EXISTS response_policy INTEGER DEFAULT 30,
ADD COLUMN IF NOT EXISTS system_prompt TEXT,
ADD COLUMN IF NOT EXISTS selected_persona VARCHAR(100) DEFAULT 'friendly-receptionist';
```

## 8. API Endpoints Summary

### Admin Endpoints
- `POST /api/v1/admin/human-agents` - Add human agents
- `DELETE /api/v1/admin/human-agents/{email}` - Remove human agent
- `GET /api/v1/admin/token-usage` - Get token usage

### Public Endpoints
- `POST /api/v1/admin/human-agents/confirm` - Confirm agent account
- `POST /api/v1/feedback` - Submit feedback
- `POST /api/v1/chat` - Chat query (with system_prompt and response_policy)

### WebSocket
- `WS /ws/human-agent` - Human agent chat connection

## 9. Environment Variables

```env
# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@example.com
SMTP_PASSWORD=your-password
EMAIL_FROM=noreply@knowledgebot.com

# LLM API Keys
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key

# WebSocket Configuration
WS_PORT=8080
WS_PATH=/ws/human-agent

# Widget Link Base URL
WIDGET_BASE_URL=https://widget.example.com
```

## 10. Implementation Priority

1. **High Priority:**
   - Human agent email confirmation flow
   - Feedback recording API
   - Token usage API
   - System prompt appending in chat API

2. **Medium Priority:**
   - Human agent WebSocket connection
   - Response policy implementation

3. **Low Priority:**
   - Token usage caching
   - Advanced analytics for feedback

## 11. Testing Requirements

- Unit tests for email sending
- Integration tests for WebSocket connections
- API tests for all endpoints
- Load tests for WebSocket server
- Email delivery tests

