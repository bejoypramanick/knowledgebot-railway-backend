# OpenTelemetry Configuration Guide

## Overview

This document explains the OpenTelemetry configuration changes to reduce verbose span output while maintaining trace ID and span ID visibility in logs.

## Problem

The previous configuration was outputting detailed span information like:
```json
{
    "events": [],
    "name": "GET",
    "links": [],
    "context": {
        "resource": {
            "trace_id": "0x424916616254175ba7fbf91d2454a896",
            "span_id": "0x75777affa9a6cfdc",
            "attributes": {
                "trace_state": "[]"
            },
            "telemetry.sdk.language": "python",
            "kind": "SpanKind.CLIENT",
            "telemetry.sdk.name": "opentelemetry",
            "parent_id": null,
            "start_time": "2026-02-01T09:19:08.105878Z",
            "telemetry.sdk.version": "1.39.1",
            "service.name": "api-gateway"
        },
        "status": {
            "status_code": "UNSET"
        }
    },
    "attributes": {
        "http.method": "GET",
        "http.url": "http://configuration.railway.internal:8080/api/v1/configuration/users/profile",
        "http.status_code": 200
    }
}
```

This was too verbose and cluttered the logs.

## Solution

### 1. Modified `shared/telemetry.py`

- Added `enable_span_exporter` parameter to `setup_telemetry()` function
- Added environment variable `OTEL_SPAN_EXPORTER_ENABLED` for configuration
- Default behavior: span exporter is **disabled** (no verbose span output)
- Trace ID and Span ID are still included in all log statements

### 2. Updated All Services

All services now use the default behavior:
- `api_gateway/main.py`
- `configuration/main.py` 
- `chatbot_orchestration/main.py`
- `knowledgebase_ingestion/main.py`
- `website_crawling/main.py`

## Log Format

The log format remains the same and includes trace/span IDs:
```
[2026-02-01 09:19:08,123] [INFO] [api-gateway] [0x424916616254175ba7fbf91d2454a896] [0x75777affa9a6cfdc] - Request processed successfully
```

## Configuration Options

### Environment Variable

Set `OTEL_SPAN_EXPORTER_ENABLED=true` to enable detailed span output:

```bash
# Enable verbose span output
export OTEL_SPAN_EXPORTER_ENABLED=true

# Disable verbose span output (default)
export OTEL_SPAN_EXPORTER_ENABLED=false
```

### Programmatic Configuration

You can also control it programmatically if needed:

```python
from shared.telemetry import setup_telemetry

# Enable span exporter
setup_telemetry("my-service", enable_span_exporter=True)

# Disable span exporter  
setup_telemetry("my-service", enable_span_exporter=False)

# Use environment variable (default)
setup_telemetry("my-service")
```

## Benefits

1. **Cleaner Logs**: No more verbose JSON span output cluttering the logs
2. **Traceability**: Trace ID and Span ID are still visible in all log statements
3. **Request Correlation**: Easy to follow requests across all microservices
4. **Configurable**: Can enable detailed spans when needed for debugging
5. **Backward Compatible**: Existing trace context propagation still works

## Trace Context Propagation

The trace context propagation continues to work as before:
- HTTP requests between services include trace headers
- All log statements within a request share the same trace ID
- Easy to correlate logs across all services in a request flow

## Example Log Flow

```
API Gateway:    [INFO] [api-gateway] [abc123] [def456] - Incoming request /api/v1/chat
Configuration: [INFO] [configuration] [abc123] [ghi789] - Fetching user profile  
Chatbot:        [INFO] [chatbot-orchestration] [abc123] [jkl012] - Processing chat request
```

All logs with trace ID `abc123` belong to the same user request, making it easy to trace the complete flow.
