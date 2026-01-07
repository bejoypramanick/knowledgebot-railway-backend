# Architecture Overview

## Database Architecture

### Firebase Firestore
**Purpose**: OAuth credential storage ONLY

**Collections**:
- `email_config/gmail_oauth` - Gmail OAuth2 credentials (Client ID, Secret, Refresh Token)

**Why Firebase for OAuth?**
- Secure credential storage
- Update credentials without redeploying
- Centralized management
- Separation from application data

### PostgreSQL (Railway)
**Purpose**: All application data storage

**Tables**:
- `human_agents` - Human agent information and status
- `human_agent_sessions` - Agent-customer chat sessions
- `chat_feedback` - User feedback on chat messages
- `token_usage_cache` - LLM token usage statistics
- `chatbot_configuration` - Chatbot settings and configuration
- `widget_configuration` - Widget appearance and behavior settings
- `chat_sessions` - Chat session metadata
- `chat_messages` - Individual chat messages
- `file_uploads` - Document upload metadata
- Other application tables...

**Why PostgreSQL?**
- Relational data structure
- ACID compliance
- Complex queries and joins
- Transaction support
- Standard SQL interface

## Data Flow

### Email Sending Flow
1. Application needs to send email (e.g., human agent confirmation)
2. Email service requests OAuth credentials from **Firebase Firestore**
3. Firebase returns Client ID, Secret, Refresh Token
4. Email service exchanges Refresh Token for Access Token (Google OAuth API)
5. Email service sends email via Gmail SMTP using Access Token
6. Application data (human agent record) stored in **PostgreSQL**

### Human Agent Management Flow
1. Admin adds human agent email
2. Record created in **PostgreSQL** `human_agents` table
3. Confirmation token generated and stored in **PostgreSQL**
4. Email service gets OAuth credentials from **Firebase**
5. Confirmation email sent via Gmail
6. Agent confirms → Status updated in **PostgreSQL**
7. Widget link and password stored in **PostgreSQL**

### Feedback Flow
1. User submits feedback (thumbs up/down)
2. Feedback record created in **PostgreSQL** `chat_feedback` table
3. No Firebase interaction needed

## Service Responsibilities

### Configuration Service
- Manages chatbot and widget configuration
- Stores configuration in **PostgreSQL**
- Uses Firebase only for email OAuth credentials

### Email Service
- Gets OAuth credentials from **Firebase Firestore**
- Sends emails via Gmail SMTP
- Does NOT store application data

### Chatbot Orchestration Service
- Handles chat queries
- Stores chat sessions and messages in **PostgreSQL**
- No Firebase interaction

## Security Model

### Firebase Security
- Firestore security rules prevent client-side access
- Only Firebase Admin SDK (server-side) can read OAuth credentials
- OAuth credentials encrypted at rest in Firestore

### PostgreSQL Security
- Connection via Railway's secure database URL
- Credentials stored as environment variables
- Application data encrypted at rest
- Access controlled via Railway service permissions

## Summary

| Component | Storage | Purpose |
|-----------|---------|---------|
| OAuth Credentials | Firebase Firestore | Gmail OAuth2 (Client ID, Secret, Refresh Token) |
| Human Agents | PostgreSQL | Agent information, status, tokens |
| Feedback | PostgreSQL | User feedback on messages |
| Chat Sessions | PostgreSQL | Chat history and metadata |
| Configuration | PostgreSQL | Chatbot and widget settings |
| Token Usage | PostgreSQL | LLM token statistics |

**Key Principle**: Firebase = OAuth credentials only. Everything else = PostgreSQL.

