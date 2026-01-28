# Token Tracking Alerting Setup Guide

This guide explains how to configure and use the token tracking alerting system.

## Overview

The token tracking system includes comprehensive alerting and rate limiting capabilities:

- **Real-time Alerting**: Automatic alerts for high error rates, performance issues, and service unavailability
- **Multiple Alert Channels**: Log, webhook, and email notifications
- **Rate Limiting**: Configurable rate limits for metrics endpoints
- **Alert Management**: View and manage alerts through API endpoints

## Alert Types

### 1. High Error Rate Alerts
Triggered when error rates exceed thresholds:
- **Medium**: >10% error rate
- **High**: >15% error rate  
- **Critical**: >25% error rate

### 2. Performance Degradation Alerts
Triggered when response times exceed thresholds:
- **Medium**: >1000ms average response time
- **High**: >2000ms average response time
- **Critical**: >5000ms average response time

### 3. Service Unavailability Alerts
Triggered when no successful operations occur:
- **High**: No success for 5 minutes
- **Critical**: No success for 15 minutes

## Alert Channels

### 1. Log Alerts (Default)
Alerts are automatically logged to the `token_alerts` logger.

### 2. Webhook Alerts
Configure webhook URLs to receive alerts via HTTP POST:

```python
from shared.token_alerting import setup_default_alerting

webhook_url = "https://your-webhook-url.com/alerts"
await setup_default_alerting(webhook_url=webhook_url)
```

Webhook payload format:
```json
{
  "alert_type": "high_error_rate",
  "severity": "high",
  "message": "High error rate detected for track_token_usage: 25.3%",
  "operation": "track_token_usage",
  "current_value": 25.3,
  "threshold": 10.0,
  "timestamp": 1640995200.0,
  "formatted_time": "2022-01-01T12:00:00",
  "metadata": {
    "threshold_type": "percentage",
    "recommended_action": "Check service health and database connectivity"
  }
}
```

### 3. Email Alerts
Configure email notifications:

```python
email_config = {
    "smtp_config": {
        "host": "smtp.gmail.com",
        "port": 587,
        "username": "your-email@gmail.com",
        "password": "your-app-password",
        "use_tls": True
    },
    "recipients": ["admin@yourcompany.com", "devops@yourcompany.com"]
}

await setup_default_alerting(email_config=email_config)
```

## Rate Limiting

### Metrics Endpoints
- **30 requests per minute**
- **500 requests per hour**
- **5000 requests per day**
- **5 burst requests**

### Rate Limit Headers
All rate-limited endpoints include these headers:
```
X-RateLimit-Limit-Minute: 30
X-RateLimit-Remaining-Minute: 25
X-RateLimit-Limit-Hour: 500
X-RateLimit-Remaining-Hour: 475
X-RateLimit-Limit-Day: 5000
X-RateLimit-Remaining-Day: 4975
X-RateLimit-Retry-After: 45
```

### Rate Limit Response
When rate limited:
```json
{
  "detail": "Rate limit exceeded"
}
```
HTTP Status: 429 Too Many Requests

## API Endpoints

### Get Token Metrics
```
GET /api/v1/admin/token-metrics
```
- Rate limited: 30/minute
- Automatically checks for alert conditions

### Get Health Status
```
GET /api/v1/admin/token-metrics/health
```
- Rate limited: 30/minute
- Returns system health status

### Get Alerts
```
GET /api/v1/admin/token-metrics/alerts?hours=24&severity=high
```
- Rate limited: 30/minute
- Query parameters:
  - `hours`: Hours of alert history (default: 24)
  - `severity`: Filter by severity (low, medium, high, critical)

### Get Alert Summary
```
GET /api/v1/admin/token-metrics/alerts/summary?hours=24
```
- Rate limited: 30/minute
- Returns aggregated alert statistics

## Configuration

### Environment Variables
Set these in your environment:

```bash
# Alert Webhook URL
ALERT_WEBHOOK_URL=https://your-webhook-url.com/alerts

# Email Configuration
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USERNAME=your-email@gmail.com
ALERT_SMTP_PASSWORD=your-app-password
ALERT_SMTP_RECIPIENTS=admin@yourcompany.com,devops@yourcompany.com

# Rate Limiting (optional overrides)
METRICS_RATE_LIMIT_MINUTE=30
METRICS_RATE_LIMIT_HOUR=500
METRICS_RATE_LIMIT_DAY=5000
```

### Custom Rate Limits
You can customize rate limits in code:

```python
from shared.rate_limiter import RateLimitConfig, get_rate_limiter

custom_config = RateLimitConfig(
    requests_per_minute=100,
    requests_per_hour=2000,
    requests_per_day=20000,
    burst_size=20
)

limiter = get_rate_limiter("custom", custom_config)
```

## Monitoring and Debugging

### Alert Cooldowns
Alerts have a 5-minute cooldown per alert type and operation to prevent spam.

### Alert History
The system maintains the last 1000 alerts in memory for debugging.

### Logging
Enable debug logging for alerting:
```python
import logging
logging.getLogger("token_alerts").setLevel(logging.DEBUG)
```

## Production Deployment

### 1. Configure Alerting
Set up webhook and/or email alerts in your production configuration.

### 2. Monitor Rate Limits
Monitor the rate limit headers to ensure they're appropriate for your usage.

### 3. Set Up Monitoring
Use the health endpoint to monitor the token tracking system:
```bash
curl -H "Authorization: Bearer your-token" \
     https://your-api.com/api/v1/admin/token-metrics/health
```

### 4. Alert Integration
Integrate webhook alerts with your monitoring system (PagerDuty, Slack, etc.).

## Troubleshooting

### Common Issues

1. **Alerts Not Firing**
   - Check alerting configuration
   - Verify webhook/email settings
   - Check logs for errors

2. **Rate Limiting Too Strict**
   - Adjust rate limit configuration
   - Monitor usage patterns

3. **Missing Alert Data**
   - Check metrics collection is working
   - Verify alert thresholds are appropriate

### Debug Mode
Enable debug logging:
```python
import logging
logging.getLogger("shared.token_alerting").setLevel(logging.DEBUG)
logging.getLogger("shared.rate_limiter").setLevel(logging.DEBUG)
```

## Security Considerations

1. **Authentication**: All endpoints require authentication
2. **Rate Limiting**: Prevents abuse and DoS attacks
3. **Input Validation**: All inputs are validated
4. **Error Handling**: Sensitive information is not exposed in error messages

## Best Practices

1. **Configure Webhooks**: Set up webhook alerts for immediate notification
2. **Monitor Health**: Regularly check the health endpoint
3. **Adjust Thresholds**: Fine-tune alert thresholds based on your usage patterns
4. **Test Alerting**: Test your alert configuration before production deployment
5. **Document Escalation**: Document who to contact for different alert types
