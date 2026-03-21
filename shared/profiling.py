"""
Remote Profiling Module (Yappi + OTEL Spans)

Provides:
1. Yappi-based CPU profiling with start/stop/stats API endpoints
2. OTEL span helpers for instrumenting the chat stream pipeline

Usage:
  - Mount profiling router in the chatbot orchestration app
  - Use @trace_phase() decorator or trace_phase_ctx() context manager in streaming_service.py
"""

import os
import io
import time
import asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from functools import wraps

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("profiling", "chatbot-orchestration")
tracer = trace.get_tracer("chatbot-orchestration.profiling")

# ============================================================
# YAPPI PROFILING (remote toggle via API)
# ============================================================

_yappi_available = False
try:
    import yappi
    _yappi_available = True
except ImportError:
    logger.warning("yappi not installed - profiling endpoints will return 501")


def is_profiling_active() -> bool:
    if not _yappi_available:
        return False
    return yappi.is_running()


def start_profiling(clock_type: str = "wall") -> dict:
    """Start yappi profiler. clock_type: 'wall' or 'cpu'."""
    if not _yappi_available:
        return {"error": "yappi not installed", "status": 501}
    if yappi.is_running():
        return {"message": "Profiler already running", "clock_type": yappi.get_clock_type()}
    yappi.clear_stats()
    yappi.set_clock_type(clock_type)
    yappi.start(builtins=True)
    logger.info(f"Yappi profiler STARTED (clock={clock_type})")
    return {"message": "Profiler started", "clock_type": clock_type}


def stop_profiling() -> dict:
    """Stop yappi profiler."""
    if not _yappi_available:
        return {"error": "yappi not installed", "status": 501}
    if not yappi.is_running():
        return {"message": "Profiler not running"}
    yappi.stop()
    logger.info("Yappi profiler STOPPED")
    return {"message": "Profiler stopped"}


def get_profiling_stats(sort_by: str = "ttot", limit: int = 50, filter_module: Optional[str] = None) -> dict:
    """Return profiling stats as structured data.

    sort_by: 'ttot' (total time), 'tsub' (own time), 'ncall' (call count), 'tavg' (avg time)
    filter_module: Only show functions whose module contains this string (e.g. 'streaming_service')
    """
    if not _yappi_available:
        return {"error": "yappi not installed", "status": 501}

    stats = yappi.get_func_stats()
    stats.sort(sort_by, "desc")

    rows = []
    for stat in stats:
        module = stat.module or ""
        if filter_module and filter_module not in module:
            continue
        rows.append({
            "name": stat.name,
            "module": module,
            "lineno": stat.lineno,
            "ncall": stat.ncall,
            "nactcall": stat.nactcall,
            "ttot": round(stat.ttot, 6),
            "tsub": round(stat.tsub, 6),
            "tavg": round(stat.tavg, 6),
        })
        if len(rows) >= limit:
            break

    # Also capture pstat-format text for download
    text_buf = io.StringIO()
    stats.print_all(out=text_buf)
    pstat_text = text_buf.getvalue()

    return {
        "is_running": yappi.is_running(),
        "clock_type": yappi.get_clock_type() if _yappi_available else None,
        "total_functions": len(stats),
        "showing": len(rows),
        "sort_by": sort_by,
        "filter_module": filter_module,
        "stats": rows,
        "pstat_text": pstat_text,
    }


def get_thread_stats() -> dict:
    """Return per-thread timing stats."""
    if not _yappi_available:
        return {"error": "yappi not installed", "status": 501}

    thread_stats = yappi.get_thread_stats()
    rows = []
    for ts in thread_stats:
        rows.append({
            "name": ts.name,
            "id": ts.id,
            "tid": ts.tid,
            "ttot": round(ts.ttot, 6),
            "sched_count": ts.sched_count,
        })
    return {"threads": rows}


# ============================================================
# OTEL SPAN INSTRUMENTATION (for chat stream pipeline)
# ============================================================

@asynccontextmanager
async def trace_phase(name: str, attributes: Optional[dict] = None):
    """Async context manager that creates an OTEL span for a pipeline phase.

    Usage:
        async with trace_phase("fetch_chat_history", {"session_id": sid}):
            history = await get_history(sid)
    """
    with tracer.start_as_current_span(f"chat_stream.{name}") as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        start = time.monotonic()
        try:
            yield span
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            span.set_attribute("duration_ms", round(elapsed_ms, 2))
            logger.info(f"[PERF] {name}: {elapsed_ms:.1f}ms")


@contextmanager
def trace_phase_sync(name: str, attributes: Optional[dict] = None):
    """Sync version of trace_phase for non-async code."""
    with tracer.start_as_current_span(f"chat_stream.{name}") as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        start = time.monotonic()
        try:
            yield span
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            span.set_attribute("duration_ms", round(elapsed_ms, 2))
            logger.info(f"[PERF] {name}: {elapsed_ms:.1f}ms")


class PipelineTimer:
    """Lightweight timer that collects phase durations and logs a summary.

    Usage:
        timer = PipelineTimer(session_id)
        timer.mark("session_lookup")
        ...do work...
        timer.mark("fetch_history")
        ...do work...
        timer.mark("agent_inference")
        ...do work...
        timer.done()  # logs full breakdown
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._phases: list[tuple[str, float]] = []
        self._start = time.monotonic()
        self._last = self._start

    def mark(self, phase_name: str):
        """Record the end of a phase (start of next)."""
        now = time.monotonic()
        elapsed_ms = (now - self._last) * 1000
        self._phases.append((phase_name, elapsed_ms))
        self._last = now

    def done(self):
        """Log the full pipeline breakdown."""
        total_ms = (time.monotonic() - self._start) * 1000
        parts = " | ".join(f"{name}={ms:.0f}ms" for name, ms in self._phases)
        logger.info(f"[PIPELINE] session={self.session_id} total={total_ms:.0f}ms | {parts}")

        # Also set on current span if available
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("pipeline.total_ms", round(total_ms, 2))
            for name, ms in self._phases:
                span.set_attribute(f"pipeline.{name}_ms", round(ms, 2))

        return {
            "session_id": self.session_id,
            "total_ms": round(total_ms, 2),
            "phases": {name: round(ms, 2) for name, ms in self._phases},
        }


# ============================================================
# FASTAPI ROUTER (mount in chatbot orchestration app)
# ============================================================

def create_profiling_router():
    """Create FastAPI router with profiling control endpoints.

    Mount in your app:
        from shared.profiling import create_profiling_router
        app.include_router(create_profiling_router(), prefix="/api/v1/chatbot/profiling")
    """
    from fastapi import APIRouter, Query
    from fastapi.responses import PlainTextResponse

    router = APIRouter(tags=["profiling"])

    @router.post("/start")
    async def api_start_profiling(clock_type: str = Query("wall", enum=["wall", "cpu"])):
        """Start the yappi profiler."""
        result = start_profiling(clock_type)
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)
        return result

    @router.post("/stop")
    async def api_stop_profiling():
        """Stop the yappi profiler."""
        result = stop_profiling()
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)
        return result

    @router.get("/stats")
    async def api_get_stats(
        sort_by: str = Query("ttot", enum=["ttot", "tsub", "ncall", "tavg"]),
        limit: int = Query(50, ge=1, le=500),
        filter_module: Optional[str] = Query(None, description="Filter by module name substring"),
        format: str = Query("json", enum=["json", "text"]),
    ):
        """Get profiling stats. Use format=text for pstat-style output."""
        result = get_profiling_stats(sort_by, limit, filter_module)
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)

        if format == "text":
            return PlainTextResponse(result.get("pstat_text", "No stats available"))
        return result

    @router.get("/threads")
    async def api_get_thread_stats():
        """Get per-thread timing stats."""
        result = get_thread_stats()
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)
        return result

    @router.get("/status")
    async def api_profiling_status():
        """Check if profiler is running."""
        return {
            "yappi_available": _yappi_available,
            "is_running": is_profiling_active(),
            "clock_type": yappi.get_clock_type() if _yappi_available and yappi.is_running() else None,
        }

    return router
