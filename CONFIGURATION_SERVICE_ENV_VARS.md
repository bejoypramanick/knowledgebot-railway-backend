# Configuration Service Environment Variables

The configuration service requires the following environment variables to be set in Railway:

## Required Environment Variables

### Database
- `DATABASE_URL` - PostgreSQL connection string (automatically provided by Railway)

### Redis (Required for SSE and Session Management)
- `REDIS_URL` - Redis connection string for Pub/Sub and session storage

  **Format**: `redis://default:<password>@<host>:<port>`
  
  **Example**: `redis://default:mypassword@redis.railway.internal:6379`
  
  **Railway Setup**:
  1. Go to your Railway project
  2. Find your Redis service
  3. Copy the `REDIS_URL` variable
  4. Add it to the Configuration service environment variables
  
  **Note**: The system uses different Redis databases:
  - Database 0: Celery task queue
  - Database 1: Web crawling cache
  - Database 2: File processing cache
  - Database 3: Session storage
  - Database 4: Pub/Sub for SSE events

### Firebase Admin SDK
- `FIREBASE_PROJECT_ID` - Your Firebase project ID
- `FIREBASE_CREDENTIALS_JSON` - Firebase service account credentials (JSON string)

### Service URLs (Internal Railway URLs)
- `CHATBOT_ORCHESTRATION_URL` - URL of chatbot orchestration service
  - Example: `http://chatbot-orchestration.railway.internal:8080`
  
- `KNOWLEDGEBASE_INGESTION_URL` - URL of knowledgebase ingestion service
  - Example: `http://knowledgebase-ingestion.railway.internal:8080`

### OpenTelemetry (Optional)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OpenTelemetry collector endpoint (optional)
- `OTEL_SERVICE_NAME` - Service name for tracing (default: "configuration")

## How to Set Environment Variables in Railway

1. Open your Railway project
2. Select the Configuration service
3. Go to the "Variables" tab
4. Click "New Variable"
5. Add each variable with its value
6. Railway will automatically redeploy the service

## Verifying Configuration

After setting the environment variables, check the Railway logs for:

```
✅ SessionStore initialized with Redis
🔌 Agent <email> connecting to Redis Pub/Sub SSE stream
```

If you see errors like:
```
❌ REDIS_URL environment variable not set
```

Then the `REDIS_URL` variable is missing or incorrect.

## Common Issues

### Issue: "REDIS_URL environment variable not set"
**Solution**: Add the `REDIS_URL` variable from your Railway Redis service

### Issue: "Connection refused" to Redis
**Solution**: 
- Verify Redis service is running in Railway
- Check that the Redis URL uses the internal Railway hostname
- Ensure the Redis service is in the same Railway project

### Issue: "Connection refused" to other services
**Solution**:
- Verify all services are deployed and running
- Use Railway internal URLs (e.g., `http://service-name.railway.internal:8080`)
- Check that services are in the same Railway project/environment
