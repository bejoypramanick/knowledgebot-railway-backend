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
# HTML DASHBOARD RENDERER
# ============================================================

def _render_stats_html(result: dict, sort_by: str, limit: int, filter_module: Optional[str]) -> str:
    """Render profiling stats as a styled HTML dashboard."""
    stats = result.get("stats", [])
    is_running = result.get("is_running", False)
    clock_type = result.get("clock_type", "?")
    total_functions = result.get("total_functions", 0)

    # Build table rows
    rows_html = ""
    for i, s in enumerate(stats):
        ttot = s["ttot"]
        # Color-code by total time
        if ttot > 1.0:
            bar_color = "#ef4444"  # red
        elif ttot > 0.1:
            bar_color = "#f59e0b"  # amber
        elif ttot > 0.01:
            bar_color = "#3b82f6"  # blue
        else:
            bar_color = "#22c55e"  # green

        # Bar width relative to max ttot
        max_ttot = stats[0]["ttot"] if stats else 1
        bar_pct = min((ttot / max_ttot) * 100, 100) if max_ttot > 0 else 0

        rows_html += f"""
        <tr>
            <td class="rank">{i+1}</td>
            <td class="fn-name" title="{s['module']}:{s['lineno']}">{s['name']}</td>
            <td class="module">{s['module']}:{s['lineno']}</td>
            <td class="num">{s['ncall']}</td>
            <td class="num time">
                <div class="bar-container">
                    <div class="bar" style="width:{bar_pct:.1f}%;background:{bar_color}"></div>
                    <span>{ttot:.4f}s</span>
                </div>
            </td>
            <td class="num">{s['tsub']:.4f}s</td>
            <td class="num">{s['tavg']:.6f}s</td>
        </tr>"""

    status_badge = (
        '<span class="badge running">PROFILING</span>'
        if is_running else
        '<span class="badge stopped">STOPPED</span>'
    )

    filter_info = f' | filter: <code>{filter_module}</code>' if filter_module else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yappi Profiler Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 8px; color: #f8fafc; }}
  .meta {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 20px; }}
  .meta code {{ background: #1e293b; padding: 2px 6px; border-radius: 4px; color: #38bdf8; }}
  .badge {{ padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }}
  .badge.running {{ background: #22c55e20; color: #4ade80; border: 1px solid #22c55e40; }}
  .badge.stopped {{ background: #64748b20; color: #94a3b8; border: 1px solid #64748b40; }}
  .controls {{ margin-bottom: 20px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .controls a {{ background: #1e293b; color: #38bdf8; padding: 8px 16px; border-radius: 6px;
                 text-decoration: none; font-size: 0.85rem; border: 1px solid #334155;
                 transition: background 0.2s; }}
  .controls a:hover {{ background: #334155; }}
  .controls a.danger {{ color: #f87171; border-color: #7f1d1d; }}
  .controls a.danger:hover {{ background: #7f1d1d40; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; padding: 10px 12px; background: #1e293b; color: #94a3b8;
       font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.05em;
       border-bottom: 2px solid #334155; position: sticky; top: 0; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; }}
  tr:hover {{ background: #1e293b60; }}
  .rank {{ color: #64748b; width: 40px; }}
  .fn-name {{ color: #f8fafc; font-weight: 500; max-width: 300px; overflow: hidden;
              text-overflow: ellipsis; white-space: nowrap; }}
  .module {{ color: #64748b; font-size: 0.75rem; max-width: 250px; overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .time {{ min-width: 180px; }}
  .bar-container {{ display: flex; align-items: center; gap: 8px; }}
  .bar {{ height: 6px; border-radius: 3px; min-width: 2px; }}
  .bar-container span {{ white-space: nowrap; }}
  .sort-link {{ color: #94a3b8; text-decoration: none; }}
  .sort-link:hover {{ color: #38bdf8; }}
  .sort-active {{ color: #38bdf8; font-weight: 700; }}
  .empty {{ text-align: center; padding: 40px; color: #64748b; }}
</style>
</head>
<body>
<h1>Yappi Profiler Dashboard {status_badge}</h1>
<p class="meta">
  clock: <code>{clock_type}</code> |
  showing {len(stats)} of {total_functions} functions |
  sorted by: <code>{sort_by}</code>{filter_info}
</p>

<div class="controls">
  <a href="start?clock_type=wall">Start (wall)</a>
  <a href="start?clock_type=cpu">Start (cpu)</a>
  <a href="stop" class="danger">Stop</a>
  <a href="stats?format=html&sort_by=ttot&limit={limit}{'&filter_module=' + filter_module if filter_module else ''}">Refresh</a>
  <a href="stats?format=html&sort_by=ttot&limit={limit}&filter_module=streaming_service">Filter: streaming</a>
  <a href="stats?format=html&sort_by=ttot&limit={limit}&filter_module=knowledge_tools">Filter: RAG</a>
  <a href="stats?format=html&sort_by=ttot&limit={limit}">All modules</a>
  <a href="threads">Threads (JSON)</a>
  <a href="stats?format=json&sort_by={sort_by}&limit={limit}">Raw JSON</a>
</div>

<table>
<thead>
<tr>
  <th>#</th>
  <th>Function</th>
  <th>Module</th>
  <th><a class="sort-link {'sort-active' if sort_by=='ncall' else ''}" href="stats?format=html&sort_by=ncall&limit={limit}{'&filter_module=' + filter_module if filter_module else ''}">Calls</a></th>
  <th><a class="sort-link {'sort-active' if sort_by=='ttot' else ''}" href="stats?format=html&sort_by=ttot&limit={limit}{'&filter_module=' + filter_module if filter_module else ''}">Total Time</a></th>
  <th><a class="sort-link {'sort-active' if sort_by=='tsub' else ''}" href="stats?format=html&sort_by=tsub&limit={limit}{'&filter_module=' + filter_module if filter_module else ''}">Own Time</a></th>
  <th><a class="sort-link {'sort-active' if sort_by=='tavg' else ''}" href="stats?format=html&sort_by=tavg&limit={limit}{'&filter_module=' + filter_module if filter_module else ''}">Avg Time</a></th>
</tr>
</thead>
<tbody>
{rows_html if rows_html else '<tr><td colspan="7" class="empty">No profiling data. Start the profiler, send some chat messages, then refresh.</td></tr>'}
</tbody>
</table>
</body>
</html>"""


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

    @router.get("/start")
    async def api_start_profiling(clock_type: str = Query("wall", enum=["wall", "cpu"])):
        """Start the yappi profiler."""
        result = start_profiling(clock_type)
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)
        return result

    @router.get("/stop")
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
        format: str = Query("json", enum=["json", "text", "html"]),
    ):
        """Get profiling stats. Use format=html for a styled dashboard view."""
        result = get_profiling_stats(sort_by, limit, filter_module)
        status = result.pop("status", 200)
        if status != 200:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status)

        if format == "text":
            return PlainTextResponse(result.get("pstat_text", "No stats available"))

        if format == "html":
            from fastapi.responses import HTMLResponse
            html = _render_stats_html(result, sort_by, limit, filter_module)
            return HTMLResponse(content=html)

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
