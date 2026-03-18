# Enhanced Chatbot Load Test

## Overview
This load test simulates 20 concurrent users, each having 5 consecutive conversations with the chatbot API, for a total of 100 chat interactions.

## Features
- **20 concurrent users** × **5 chats each** = **100 total conversations**
- **Session continuity** - Each user maintains their session across all 5 chats
- **Realistic conversation flows** - Uses predefined conversation sequences
- **Detailed request/response tracking** - Every interaction is logged with full details
- **Real-time web UI** - Custom dashboard showing live results
- **Comprehensive metrics** - TTFC, response times, success rates, and more

## Quick Start

### 1. Install Dependencies
```bash
cd tests/loadtest
pip install -r requirements.txt
```

### 2. Run with Web UI
```bash
locust -f locustfile.py --host=https://api-gateway-common.up.railway.app
```
Then open: http://localhost:8089

### 3. Run Headless (No UI)
```bash
locust -f locustfile.py \
    --host=https://api-gateway-common.up.railway.app \
    --users=20 --spawn-rate=2 --headless
```

## Web UI Features

### Main Dashboard (http://localhost:8089)
- **Users**: Set to 20 (each user will do 5 chats)
- **Spawn Rate**: 2 users/second (10-second ramp-up)
- **Standard Locust metrics**: RPS, response times, failures

### Detailed Results (http://localhost:8089/test-results)
- **Real-time progress tracking** (auto-refreshes every 5 seconds)
- **Summary statistics**: Total chats, success rate, average times
- **Individual request/response details**: Question, response preview, timings
- **Status tracking**: Success/failure for each chat
- **Session continuity**: Track conversations across multiple chats

## Test Scenarios

### Conversation Sequences (70% of users)
1. **Customer Journey**: Product inquiry → Popular items → Pricing → Shipping → Order
2. **Support Journey**: Account help → Password reset → Email issues → Profile update → Contact support
3. **Product Inquiry**: Services overview → Tiers → Enterprise → Timelines → Quote
4. **Technical Support**: Issues → Slow loading → Dashboard access → Outages → Cache clearing
5. **General Inquiry**: New user → Platform explanation → Differentiators → Tutorials → Getting started

### Random Questions (30% of users)
- Individual questions selected randomly from a pool of 15 common inquiries

## Metrics Tracked

### Standard Locust Metrics
- `/chat/stream [Chat-N]` - Performance for each chat round (1-5)
- `/chat/stream` - Overall end-to-end response time
- `/chat/stream [TTFC]` - Time to First Chunk (how fast AI starts responding)

### Custom Detailed Metrics
- **Request/Response pairs** - Full question and response text
- **Session continuity** - Track session IDs across conversations
- **Chunk analysis** - Number of streaming chunks per response
- **Failure analysis** - Detailed error messages and context
- **User journey tracking** - Progress through 5-chat sequences

## Expected Behavior

1. **Ramp-up**: 20 users spawn at 2/second over 10 seconds
2. **Execution**: Each user sends 5 consecutive messages with 1-3 second delays
3. **Session Management**: Session ID maintained across all 5 chats per user
4. **Auto-termination**: Test stops when all 20 users complete their 5 chats
5. **Total Duration**: Approximately 2-5 minutes depending on API response times

## Monitoring

- **Console Output**: Real-time progress and individual chat results
- **Main UI**: Standard Locust performance metrics
- **Custom Dashboard**: Detailed request/response tracking with auto-refresh
- **Progress Bar**: Visual indication of test completion (0-100 chats)

## Troubleshooting

### Common Issues
- **Empty responses**: Usually indicates API gateway timeouts under load
- **Session errors**: Check if session management is working correctly
- **High failure rates**: May indicate API capacity limits or configuration issues

### Debug Information
- Each request logs: User ID, chat number, question preview, response length, timings
- Failures include: HTTP status codes, error messages, response previews
- Session tracking shows continuity across conversations

## Configuration

### Modify Test Parameters
Edit `locustfile.py` to change:
- `TARGET_USERS = 20` - Number of concurrent users
- `CHATS_PER_USER = 5` - Conversations per user
- `CHAT_SEQUENCES` - Predefined conversation flows
- `INDIVIDUAL_QUESTIONS` - Random question pool

### API Endpoint
Update the `--host` parameter to point to your API gateway:
```bash
--host=https://your-api-gateway.com
```