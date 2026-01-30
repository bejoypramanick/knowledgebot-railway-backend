# API Gateway Microservices URL Structure

This document shows the complete URL structure for all microservices after the clean URL refactoring.

## URL Structure Overview

All microservices follow the pattern: `/api/v1/{service_name}/{router_path}`

## Complete URL Mapping Table

| Service Name | Router Mapping | Final URL | Description |
|-------------|---------------|-----------|-------------|
| **API Gateway** | | | |
| Gateway | `POST /auth/verify` | `/api/v1/gateway/auth/verify` | Verify Firebase authentication token |
| Gateway | `GET /auth/user/{uid}` | `/api/v1/gateway/auth/user/{uid}` | Get user information by Firebase UID |
| Gateway | `POST /auth/login` | `/api/v1/gateway/auth/login` | Login user with Firebase token |
| Gateway | `GET /config/settings` | `/api/v1/gateway/config/settings` | Get API configuration settings |
| Gateway | `GET /health` | `/api/v1/gateway/health` | Health check endpoint |
| Gateway | `GET /status` | `/api/v1/gateway/status` | Get detailed service status |
| Gateway | `GET /rate-limit/status` | `/api/v1/gateway/rate-limit/status` | Get rate limiting status |
| Gateway | `GET /logs/recent` | `/api/v1/gateway/logs/recent` | Get recent API logs |
| Gateway | `POST /logs/error` | `/api/v1/gateway/logs/error` | Log an error from client |
| Gateway | `GET /metrics/overview` | `/api/v1/gateway/metrics/overview` | Get API metrics overview |
| Gateway | `GET /middleware/cors` | `/api/v1/gateway/middleware/cors` | Get CORS configuration status |
| Gateway | `GET /middleware/auth` | `/api/v1/gateway/middleware/auth` | Get authentication middleware status |
| Gateway | `GET /ws/events` | `/api/v1/gateway/ws/events` | SSE endpoint for WebSocket replacement |
| Gateway | `POST /ws/messages` | `/api/v1/gateway/ws/messages` | HTTP endpoint for WebSocket messages |
| **Configuration Service** | | | |
| Configuration | `GET /chatbot` | `/api/v1/configuration/chatbot` | Get complete chatbot configuration |
| Configuration | `POST /chatbot` | `/api/v1/configuration/chatbot` | Save chatbot configuration |
| Configuration | `GET /personas` | `/api/v1/configuration/personas` | Get all available personas |
| Configuration | `POST /personas/{persona_name}/activate` | `/api/v1/configuration/personas/{persona_name}/activate` | Activate a specific persona |
| Configuration | `POST /personas` | `/api/v1/configuration/personas` | Create a new persona |
| Configuration | `GET /admins` | `/api/v1/configuration/admins` | Get all admin users |
| Configuration | `POST /admins` | `/api/v1/configuration/admins` | Add a new admin user |
| Configuration | `DELETE /admins/{email}` | `/api/v1/configuration/admins/{email}` | Remove an admin user |
| Configuration | `GET /human-agents` | `/api/v1/configuration/human-agents` | Get all human agents |
| Configuration | `POST /human-agents` | `/api/v1/configuration/human-agents` | Add a new human agent |
| Configuration | `DELETE /human-agents/{email}` | `/api/v1/configuration/human-agents/{email}` | Remove a human agent |
| Configuration | `GET /chat-logs` | `/api/v1/configuration/chat-logs` | Get all chat logs |
| Configuration | `DELETE /chat-logs/{session_id}` | `/api/v1/configuration/chat-logs/{session_id}` | Delete a chat log |
| Configuration | `GET /notifications/settings` | `/api/v1/configuration/notifications/settings` | Get notification settings |
| Configuration | `POST /notifications/settings` | `/api/v1/configuration/notifications/settings` | Update notification settings |
| Configuration | `POST /notifications/send` | `/api/v1/configuration/notifications/send` | Send a notification |
| Configuration | `GET /performance/metrics` | `/api/v1/configuration/performance/metrics` | Get performance metrics |
| Configuration | `POST /feedback` | `/api/v1/configuration/feedback` | Submit feedback |
| Configuration | `GET /feedback` | `/api/v1/configuration/feedback` | Get all feedback |
| Configuration | `GET /users/profile` | `/api/v1/configuration/users/profile` | Get user profile information |
| Configuration | `PUT /users/profile` | `/api/v1/configuration/users/profile` | Update user profile information |
| Configuration | `GET /users` | `/api/v1/configuration/users` | Get all users (admin only) |
| Configuration | `GET /health` | `/api/v1/configuration/health` | Health check endpoint |
| **Chatbot Orchestration** | | | |
| Chatbot | `POST /chat` | `/api/v1/chatbot/chat` | Chat with AI agent |
| Chatbot | `POST /chat/stream` | `/api/v1/chatbot/chat/stream` | Chat with AI agent (streaming) |
| Chatbot | `GET /chat/history/{session_id}` | `/api/v1/chatbot/chat/history/{session_id}` | Get chat history for a session |
| Chatbot | `DELETE /chat/session/{session_id}` | `/api/v1/chatbot/chat/session/{session_id}` | Delete a chat session |
| Chatbot | `POST /chat/session` | `/api/v1/chatbot/chat/session` | Create a new chat session |
| Chatbot | `GET /chat/sessions` | `/api/v1/chatbot/chat/sessions` | Get all chat sessions |
| Chatbot | `GET /agents` | `/api/v1/chatbot/agents` | Get list of available agents |
| Chatbot | `GET /agents/{agent_id}` | `/api/v1/chatbot/agents/{agent_id}` | Get information about a specific agent |
| Chatbot | `GET /health` | `/api/v1/chatbot/health` | Health check endpoint |
| **Knowledgebase Ingestion** | | | |
| Knowledgebase | `POST /files/upload` | `/api/v1/knowledgebase/files/upload` | Upload a file to the knowledgebase |
| Knowledgebase | `GET /files` | `/api/v1/knowledgebase/files` | List all files |
| Knowledgebase | `DELETE /files/{file_id}` | `/api/v1/knowledgebase/files/{file_id}` | Delete a file |
| Knowledgebase | `GET /health` | `/api/v1/knowledgebase/health` | Health check endpoint |
| **Website Crawling** | | | |
| Web Crawling | `POST /` | `/api/v1/webcrawl/` | Scrape a single website (root endpoint) |
| Web Crawling | `GET /jobs` | `/api/v1/webcrawl/jobs` | Get all scraping jobs |
| Web Crawling | `GET /jobs/{job_id}` | `/api/v1/webcrawl/jobs/{job_id}` | Get details of a specific scraping job |
| Web Crawling | `DELETE /jobs/{job_id}` | `/api/v1/webcrawl/jobs/{job_id}` | Delete a scraping job |
| Web Crawling | `POST /crawl` | `/api/v1/webcrawl/crawl` | Start a crawl session for multiple websites |
| Web Crawling | `GET /crawl/sessions` | `/api/v1/webcrawl/crawl/sessions` | Get all crawl sessions |
| Web Crawling | `GET /crawl/sessions/{session_id}` | `/api/v1/webcrawl/crawl/sessions/{session_id}` | Get details of a crawl session |
| Web Crawling | `POST /crawl/sessions/{session_id}/stop` | `/api/v1/webcrawl/crawl/sessions/{session_id}/stop` | Stop a running crawl session |
| Web Crawling | `GET /jobs/{job_id}/content` | `/api/v1/webcrawl/jobs/{job_id}/content` | Get extracted content from a scraping job |
| Web Crawling | `GET /search` | `/api/v1/webcrawl/search` | Search across extracted content |
| Web Crawling | `GET /analytics/scraping` | `/api/v1/webcrawl/analytics/scraping` | Get scraping analytics summary |
| Web Crawling | `GET /analytics/domains` | `/api/v1/webcrawl/analytics/domains` | Get domain-specific analytics |
| Web Crawling | `GET /health` | `/api/v1/webcrawl/health` | Health check endpoint |

## API Gateway Proxy Endpoints

| Proxy Mapping | Target Service | Target URL |
|---------------|---------------|-----------|
| `GET /configuration/users/profile` | Configuration | `CONFIGURATION_SERVICE_URL/api/v1/configuration/users/profile` |
| `PUT /configuration/users/profile` | Configuration | `CONFIGURATION_SERVICE_URL/api/v1/configuration/users/profile` |
| `GET /configuration/users` | Configuration | `CONFIGURATION_SERVICE_URL/api/v1/configuration/users` |
| `GET /configuration/chat/{session_id}/events` | Configuration | `CONFIGURATION_SERVICE_URL/api/v1/configuration/chat/{session_id}/events` |
| `GET /configuration/admin/chat-sessions/{session_id}/events` | Configuration | `CONFIGURATION_SERVICE_URL/api/v1/configuration/admin/chat-sessions/{session_id}/events` |
| `POST /chatbot/chat/stream` | Chatbot | `CHATBOT_ORCHESTRATION_URL/api/v1/chatbot/chat/stream` |
| `POST /chatbot/suggested-messages` | Chatbot | `CHATBOT_ORCHESTRATION_URL/api/v1/chatbot/suggested-messages` |
| `GET /chatbot/sessions` | Chatbot | `CHATBOT_ORCHESTRATION_URL/api/v1/chatbot/sessions` |
| `DELETE /chatbot/sessions/{session_id}` | Chatbot | `CHATBOT_ORCHESTRATION_URL/api/v1/chatbot/sessions/{session_id}` |

## App-Level Endpoints (No Prefix)

All services also have app-level endpoints that don't include the service prefix:

| Service | App Mapping | Final URL | Description |
|---------|------------|-----------|-------------|
| All Services | `GET /` | `/` | Root endpoint |
| All Services | `GET /health` | `/health` | Health check endpoint |

## URL Structure Summary

- **Pattern**: `/api/v1/{service_name}/{router_path}`
- **Service Names**: `gateway`, `configuration`, `chatbot`, `knowledgebase`, `webcrawl`
- **Router Paths**: All start with `/` (proper relative paths)
- **Proxy Endpoints**: API Gateway forwards to appropriate service URLs
- **App-Level**: Direct endpoints like `/health` and `/`
