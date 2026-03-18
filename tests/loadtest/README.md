# Enhanced Chatbot Load Test - Customer Chat Endpoint

## Overview
This load test simulates 20 concurrent users, each having 5 consecutive conversations with the **customer-facing chat API** (`/api/v1/gateway/chatbot/chat/stream`) - the same endpoint your frontend uses. The test covers Stockholm-related topics for a total of 100 chat interactions, based on comprehensive Wikipedia content covering history, geography, culture, economy, and tourism.

## Features
- **20 concurrent users** × **5 chats each** = **100 total conversations**
- **Session continuity** - Each user maintains their session across all 5 chats
- **Realistic conversation flows** - Uses predefined conversation sequences
- **Detailed request/response tracking** - Every interaction is logged with full details
- **Real-time web UI** - Custom dashboard showing live results
- **Comprehensive metrics** - TTFC, response times, success rates, and more

## Quick Start

### Local Development

#### 1. Install Dependencies
```bash
cd tests/loadtest
pip install -r requirements.txt
```

#### 2. Run with Web UI
```bash
locust -f locustfile.py --host=https://api-gateway-common.up.railway.app
```
Then open: http://localhost:8089

#### 3. Run Headless (No UI)
```bash
locust -f locustfile.py \
    --host=https://api-gateway-common.up.railway.app \
    --users=20 --spawn-rate=2 --headless
```

### 🚂 Railway Cloud Deployment

For realistic cloud-based load testing, deploy directly to Railway:

#### Quick Deploy
1. **Push to GitHub**: Ensure your code is in a GitHub repository
2. **Deploy on Railway**: 
   - Go to [Railway.app](https://railway.app)
   - New Project → Deploy from GitHub repo
   - Select your repo and `tests/loadtest` directory
3. **Access**: Railway provides a public URL for your load test dashboard

#### Benefits
- **Realistic network conditions** from Railway's infrastructure
- **Team access** via shared public URL
- **Persistent testing** without local machine dependency
- **Auto-scaling** based on load requirements

📖 **Full Railway Guide**: See [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) for detailed instructions

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
- **📄 PDF Export**: Download professional PDF reports
- **📊 CSV Export**: Export raw data for analysis
- **🔗 JSON API**: Programmatic access at `/test-results/json`

## Export Options

### PDF Reports
- **Professional formatting** optimized for printing and sharing
- **Complete test summary** with all key metrics
- **Detailed results table** with individual chat data
- **Test configuration** and timestamp included
- **Print-friendly layout** with proper page breaks

### CSV Data Export
- **Raw data export** for further analysis in Excel/Google Sheets
- **All result fields** including timestamps, user IDs, questions, responses
- **Filename includes timestamp** for easy organization
- **Compatible with data analysis tools**

### JSON API Access
- **Programmatic access** at `/test-results/json`
- **Real-time data** for integration with monitoring systems
- **Complete test configuration** and metadata included
- **Machine-readable format** for automated reporting

## Test Scenarios

### Conversation Sequences (70% of users)
1. **Tourist Planning**: Trip planning → Attractions → Museums/Nobel → Transportation → Best time to visit
2. **Stockholm History**: History overview → Founding → Stockholm Bloodbath → Capital status → Swedish Empire
3. **Geography & Climate**: Geography questions → Islands → Climate → Archipelago → Nordic comparisons  
4. **Culture & Education**: Cultural scene → Universities → Museums → Metro art → Nobel connection
5. **Economy & Technology**: Economic overview → Major companies → Innovation hub → Tech industry → Business attractiveness

### Random Questions (30% of users)
- Individual questions about Stockholm based on Wikipedia content including:
  - Stockholm's name meaning and nicknames
  - Population and demographics  
  - Historical sites (Gamla Stan, Royal Palace, Drottningholm)
  - Transportation (metro, congestion pricing)
  - Culture (museums, ABBA, sports, festivals)
  - Environment and sustainability
  - Geography (archipelago, islands, climate)
  - Economy (companies, stock exchange, tech scene)

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

## Export Options

### PDF Reports
- **Professional formatting** optimized for printing and sharing
- **Complete test summary** with all key metrics
- **Detailed results table** with individual chat data
- **Test configuration** and timestamp included
- **Print-friendly layout** with proper page breaks

### CSV Data Export
- **Raw data export** for further analysis in Excel/Google Sheets
- **All result fields** including timestamps, user IDs, questions, responses
- **Filename includes timestamp** for easy organization
- **Compatible with data analysis tools**

### JSON API Access
- **Programmatic access** at `/test-results/json`
- **Real-time data** for integration with monitoring systems
- **Complete test configuration** and metadata included
- **Machine-readable format** for automated reporting
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