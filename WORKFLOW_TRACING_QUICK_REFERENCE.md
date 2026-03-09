# Workflow Tracing - Quick Reference

## TL;DR

✅ **Workflow tracing is now available** - Add `[workflow:name]` tags to all your logs
✅ **Logs are LOCAL only** - No egress to external aggregators (Datadog, New Relic, etc.)
✅ **Human agent workflow is implemented** - Currently tracing `human-agent-workflow`

---

## Quick Setup (30 seconds)

```python
# 1. Import at the top of your module
from shared.otel_logger import set_workflow, clear_workflow, get_otel_logger

logger = get_otel_logger("my_module", "my_service")

# 2. At the START of your workflow
async def some_feature():
    set_workflow("feature-name-workflow")

    # 3. Do your work - all logs automatically include [workflow:feature-name-workflow]
    logger.info("Step 1")  # → [workflow:feature-name-workflow] Step 1
    logger.info("Step 2")  # → [workflow:feature-name-workflow] Step 2

    # 4. ALWAYS clear at the END (including error paths!)
    clear_workflow()
    return result
```

---

## Log Output Format

```
[workflow:feature-name] [admin:email@domain.com role:admin] [session:xyz-session-16] Message here
```

Context layers (in order):
1. `workflow` (highest priority)
2. `admin` (if admin operation)
3. `session` (if chat session)
4. `task` (if background task)

---

## Railway Log Filtering

**Search for workflow in Railway dashboard:**
```
Filter: workflow:human-agent-workflow
```

Returns all logs with that workflow tag across all services.

---

## Currently Active Workflows

| Workflow | File | Function | Status |
|----------|------|----------|--------|
| `human-agent-workflow` | `chatbot_orchestration/tools/knowledge_tools.py` | `request_human_agent_connection()` | ✅ Active |

---

## Function Reference

### `set_workflow(name: str)`
Set the workflow name (appears in all subsequent logs).
```python
set_workflow("my-workflow")  # All logs now tagged with this
```

### `get_workflow() -> Optional[str]`
Get the current workflow.
```python
current = get_workflow()  # Returns "my-workflow" or None
```

### `clear_workflow()`
Clear the workflow tag (call when done).
```python
clear_workflow()  # Remove workflow from logs
```

---

## Log Egress Status

| Aspect | Status | Details |
|--------|--------|---------|
| **External Collection** | ❌ DISABLED | No OTLP exporter configured |
| **Data Location** | 🇮🇳 LOCAL | All logs stay in Railway |
| **Privacy** | ✅ SAFE | No third-party access |
| **Compliance** | ✅ GDPR-friendly | No automatic data sharing |

### Configured Exporters
- ✅ Console (stdout only - for development/Railway capture)
- ❌ OTLP (not configured)
- ❌ Datadog (not configured)
- ❌ New Relic (not configured)
- ❌ Splunk (not configured)

### If You Need External Logs
To export logs to Datadog/New Relic/Splunk:
```python
# Add to shared/telemetry.py:
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

exporter = OTLPSpanExporter(endpoint="grpc://your-collector:4317")
provider.add_span_processor(BatchSpanProcessor(exporter))
```

Or use Railway's native integrations (Datadog plugin in Railway dashboard).

---

## Common Patterns

### Pattern 1: Single workflow boundary
```python
async def handle_request():
    set_workflow("request-workflow")
    try:
        logger.info("Processing request")
        result = await do_work()
        logger.info("Request complete")
        return result
    finally:
        clear_workflow()
```

### Pattern 2: Multiple service calls with same workflow
```python
# Service A
set_workflow("multi-service-workflow")
logger.info("Step 1 in Service A")
call_service_b()  # Service B will inherit workflow context

# Service B
logger.info("Step 2 in Service B")  # Still has workflow:multi-service-workflow
```

### Pattern 3: Nested operation (reuse parent workflow)
```python
set_workflow("parent-workflow")
logger.info("Parent starting")

# Inside called function:
logger.info("Child operation")  # Still has parent workflow

clear_workflow()
```

---

## Troubleshooting

**Q: Workflow tag not appearing in logs?**
- A: Check that `set_workflow()` is called before logging
- A: Verify workflow string has no spaces/special chars
- A: Check you're not clearing too early

**Q: Workflows from different operations getting mixed?**
- A: Make sure to `clear_workflow()` in ALL return paths
- A: Use try/finally to ensure cleanup on errors
- A: Use `session:xyz` to correlate logs if needed

**Q: Too much output from workflow logging?**
- A: Only use workflows for feature-level boundaries
- A: Don't set workflow for every tiny function
- A: Filter logs: `workflow:name AND ERROR` to see just issues

---

## Log Flow Diagram

```
Your Code
    ↓
logger.info("message")
    ↓
OTEL Logger (with workflow context)
    ↓
stdout (formatted with [workflow:name])
    ↓
Railway's log capture
    ↓
Railway dashboard (searchable, LOCAL only)
    ↓
❌ NO external export (unless explicitly configured)
```

---

## Files Modified

- ✅ `shared/otel_logger.py` - Added workflow context variables and functions
- ✅ `chatbot_orchestration/tools/knowledge_tools.py` - Human agent workflow tracing

---

## Next Steps

1. **Deploy changes** to Railway
2. **Test human agent workflow** - Check Railway logs for `workflow:human-agent-workflow`
3. **Add more workflows** as needed using the pattern above
4. **Monitor log volume** - Workflow tags are helpful but add ~20 bytes per log

---

## Questions?

See full guide: `WORKFLOW_TRACING_AND_LOG_EGRESS_GUIDE.md`
