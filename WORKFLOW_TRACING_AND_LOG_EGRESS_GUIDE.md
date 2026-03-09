# Workflow Tracing & Log Egress Guide

## Overview

This guide explains:
1. How to use workflow tracing to track feature workflows (e.g., `human-agent-workflow`)
2. Your current log collection/egress status
3. How logs flow through your infrastructure

---

## 1. Workflow Tracing (NEWLY IMPLEMENTED)

### What is Workflow Tracing?

Workflow tracing allows you to mark a series of related operations with a **workflow identifier** that appears in all logs, making it easy to trace the complete flow of a feature end-to-end.

### Implementation Details

The workflow context is injected into all OTEL logs via:
- **Log message prefix**: `[workflow:human-agent-workflow]` appears at the start of each log
- **Span attributes**: `workflow="human-agent-workflow"` is added to span events
- **Extra fields**: Added to log record extra dictionary for structured logging

### Using Workflow Tracing

#### Basic Usage

```python
from shared.otel_logger import set_workflow, clear_workflow, get_otel_logger

logger = get_otel_logger("my_module", "my_service")

# At the start of a workflow
set_workflow("human-agent-workflow")

# All subsequent logs will include [workflow:human-agent-workflow]
logger.info("Assigning session to agent")  # Outputs: [workflow:human-agent-workflow] Assigning session to agent...
logger.info("Broadcasted session event")   # Outputs: [workflow:human-agent-workflow] Broadcasted session event...

# At the end of the workflow
clear_workflow()
```

#### Log Output Example

```
2026-03-09 14:32:45 [INFO] [chatbot-orchestration] [abc123def456] [span-id-789] - [workflow:human-agent-workflow] 🧑 Tool called: request_human_agent_connection for session xyz-123 (numeric: 45) with reason: User requested agent
2026-03-09 14:32:45 [INFO] [chatbot-orchestration] [abc123def456] [span-id-789] - [workflow:human-agent-workflow session:xyz-123abc16] 📍 Tool execution starting - session_numeric_id=45, session_uuid=xyz-123
2026-03-09 14:32:46 [INFO] [chatbot-orchestration] [abc123def456] [span-id-789] - [workflow:human-agent-workflow] ✅ Agent already assigned: agent@company.com - skipping duplicate assignment
```

### Finding Workflow Logs

**In Railway Logs View:**
```
Filter: "workflow:human-agent-workflow"
```

This will return all logs tagged with this workflow, regardless of service or file, in chronological order.

**Pattern Examples:**
```
# Find all human agent workflow steps
"workflow:human-agent-workflow"

# Find specific workflow step during session
"workflow:human-agent-workflow" AND "session:xyz-123abc16"

# Find all workflow errors
"workflow:human-agent-workflow" AND "ERROR"
```

### Supported Workflows

Current implementations:
- `human-agent-workflow` - Tracks the complete human agent handoff flow from tool invocation through broadcasting to agent

### Adding New Workflows

To add workflow tracing to any feature:

1. **At the start of the operation:**
   ```python
   set_workflow("your-feature-workflow")
   ```

2. **At the end/error handling:**
   ```python
   clear_workflow()
   ```

3. **In all early returns:**
   ```python
   if error_condition:
       clear_workflow()
       return error_response
   ```

---

## 2. Log Collection & Egress Status

### Current Setup: LOCAL LOGS ONLY ✅

**Your logs are NOT being sent to external log aggregators.**

#### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway Deployment                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Services (api_gateway, chatbot_orchestration, etc) │   │
│  │  └─────────────→ stdout/stderr                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                      ↓                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Railway Log Capture                                │   │
│  │  (Captures all stdout/stderr from services)        │   │
│  └─────────────────────────────────────────────────────┘   │
│                      ↓                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Railway Dashboard / Logs Tab                        │   │
│  │  (View logs in web UI - LOCAL ONLY)                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ⚠️ NO EXPORT TO:                                            │
│     • Datadog                                               │
│     • New Relic                                             │
│     • Splunk                                                │
│     • Elastic / ELK                                         │
│     • CloudWatch                                            │
│     • Sumo Logic                                            │
│     • Any other external aggregator                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

#### Configuration Files Checked

1. **`shared/telemetry.py`**
   - ✅ Only configures `ConsoleSpanExporter()` which prints to STDOUT
   - ❌ NO `OTLPSpanExporter` or `BatchSpanProcessor` for external collectors
   - ❌ NO gRPC/HTTP OTLP endpoint configuration

2. **`api_gateway/core/logging_config.py`**
   - ✅ Configured to output to stdout only
   - ✅ `stream=sys.stdout`
   - ❌ NO file handlers, syslog, or external exports

3. **Environment Variables** (`OTEL_EXPORTER_OTLP_*`)
   - ✅ NOT CONFIGURED - No OTLP exporter enabled
   - ✅ NO external trace/metric collectors wired up

### Log Retention

**Railway provides:**
- Log retention in dashboard (duration varies by plan)
- Queryable via Railway web UI
- Downloadable for compliance

**You are responsible for:**
- Archiving logs if long-term retention needed
- Setting up external log forwarding if required

### If You Need to Export Logs

To enable log egress to an external aggregator, you would need to:

1. **Option A: Add OTLP Exporter** (for OpenTelemetry metrics/traces)
   ```python
   # In shared/telemetry.py
   from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

   otlp_exporter = OTLPSpanExporter(
       endpoint="grpc://your-collector.example.com:4317"
   )
   provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
   ```

2. **Option B: Add Fluent Forward / Syslog Handler** (for raw logs)
   ```python
   # In logging_config.py
   # Add handler that forwards logs to external service
   ```

3. **Option C: Use Railway's Native Integrations**
   - Enable Datadog/New Relic integration in Railway dashboard
   - Automatically captures stdout and forwards

### Data Privacy Note

✅ **No egress by default** - All logs stay within Railway's infrastructure
✅ **GDPR/Data residency friendly** - No logs sent to third parties
⚠️ **Audit/Compliance** - If required, you must explicitly configure external collection

---

## 3. Log Context Hierarchy

All logs now include multiple context layers (in order of priority):

```
[PRIORITY 1: Workflow] [PRIORITY 2: Admin] [PRIORITY 3: Session] [PRIORITY 4: Task] - Message
```

### Example with All Contexts

```
[workflow:human-agent-workflow admin:user@company.com role:admin admin_session:abc12345 session:xyz-session-abc16 task:task-12345]
  📍 Assigning session to agent
```

### Log Field Breakdown

| Field | Source | Example | Visibility |
|-------|--------|---------|------------|
| `workflow` | `set_workflow()` | `human-agent-workflow` | Message prefix + span attributes |
| `admin` | `set_admin_context()` | `user@company.com` | Message prefix + span attributes |
| `role` | `set_admin_context()` | `admin`, `viewer` | Message prefix + span attributes |
| `admin_session` | `set_admin_context()` | `abc12345` (first 8 chars) | Message prefix + span attributes |
| `session` | `set_session_id()` | `xyz-abc16` (first 16 chars) | Message prefix + span attributes |
| `task` | `set_task_id()` | `task-12345` (first 16 chars) | Message prefix + span attributes |

---

## 4. Usage Examples

### Example 1: Tracing Human Agent Workflow

**File: `chatbot_orchestration/tools/knowledge_tools.py`**

```python
async def request_human_agent_connection(ctx: RunContext[ChatSessionDeps], reason: str) -> str:
    # Set workflow context
    set_workflow("human-agent-workflow")

    logger.info("Starting human agent assignment...")
    # Output: [workflow:human-agent-workflow] Starting human agent assignment...

    # Do work...
    logger.info(f"Found available agent: {agent}")
    # Output: [workflow:human-agent-workflow] Found available agent: agent@company.com

    # Always clean up at the end
    clear_workflow()
    return success_message
```

### Example 2: Multiple Workflows in Different Services

```python
# In chatbot_orchestration
set_workflow("chat-message-flow")
logger.info("Processing user message")

# In configuration service
set_workflow("chat-message-flow")  # Same workflow across services
logger.info("Updating chat session state")
```

### Example 3: Nested Operations (be careful)

```python
set_workflow("parent-workflow")
logger.info("Starting parent operation")

# Inside a called function:
set_workflow("parent-workflow")  # Still the same workflow
logger.info("Child operation step 1")

clear_workflow()
```

---

## 5. Debugging Workflow Issues

### Problem: Logs not showing workflow context

**Solution:**
1. Verify `set_workflow()` is called
2. Check workflow name is correct (no spaces, valid identifier)
3. Verify `clear_workflow()` is called in ALL return paths
4. Check log level is not filtering out your logs

### Problem: Workflow spans don't appear together

**Solution:**
1. Verify same workflow name across all logs
2. Check clock skew if services are distributed
3. Use `session:xyz` to correlate logs if workflow ID not consistent
4. Check if service crashed mid-workflow (no clear_workflow call)

### Problem: Too many workflows in output

**Solution:**
```python
# Only set workflow for complex operations
# Not every small function

# ✅ Good - workflow for feature boundary
set_workflow("human-agent-workflow")  # Complex multi-step operation

# ❌ Bad - too granular
set_workflow("get-agent-email-workflow")  # Too small to be useful
```

---

## 6. Summary

| Aspect | Status |
|--------|--------|
| **Workflow Tracing** | ✅ Implemented (human-agent-workflow active) |
| **Log Egress** | ❌ Disabled (local-only, no external collection) |
| **Privacy** | ✅ Data stays in Railway infrastructure |
| **Compliance** | ✅ No automatic third-party sharing |
| **Audit Trail** | ✅ Complete with admin/session/workflow context |

---

## Questions?

- **How to add a new workflow?** See "Adding New Workflows" section above
- **How to export logs?** See "If You Need to Export Logs" section
- **How to debug workflow issues?** See "Debugging Workflow Issues" section
