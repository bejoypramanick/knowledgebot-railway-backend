"""
Task Control API Endpoints

Provides REST API for external task termination.
Allows stopping Celery tasks from anywhere in the application.
"""
from fastapi import APIRouter, HTTPException
from shared.task_control import TaskControl
from shared.otel_logger import get_otel_logger
from typing import Optional

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = get_otel_logger("task_router", "knowledgebase-ingestion")


@router.post("/stop/{task_id}")
async def stop_task_endpoint(
    task_id: str,
    task_type: str = "auto",
    graceful: bool = False
):
    """
    Stop a Celery task externally.

    **Parameters:**
    - `task_id`: Celery task ID to stop (required)
    - `task_type`: Task type - 'file', 'web', or 'auto' (default: 'auto')
    - `graceful`: Use SIGTERM (True) or SIGKILL (False) (default: False)

    **Signals:**
    - `SIGTERM` (graceful=True): Task gets ~5 seconds to clean up before being killed
    - `SIGKILL` (graceful=False): Task killed immediately with no cleanup

    **Response:**
    - `success`: Whether the task was stopped
    - `task_id`: The task ID that was stopped
    - `message`: Human-readable status message

    **Examples:**
    ```
    # Stop a web task immediately (SIGKILL)
    POST /api/v1/tasks/stop/abc-123-def-456

    # Stop a task with cleanup time (SIGTERM)
    POST /api/v1/tasks/stop/abc-123-def-456?graceful=true

    # Stop a file task specifically
    POST /api/v1/tasks/stop/abc-123-def-456?task_type=file
    ```

    **Response:**
    ```json
    {
        "success": true,
        "task_id": "abc-123-def-456",
        "task_type": "auto",
        "graceful": false,
        "signal": "SIGKILL",
        "message": "Task stopped successfully"
    }
    ```
    """
    try:
        logger.info("=" * 80)
        logger.info(f"📡 [API] Stop task request: {task_id}")
        logger.info(f"   Type: {task_type}, Graceful: {graceful}")
        logger.info("=" * 80)

        signal = "SIGTERM" if graceful else "SIGKILL"

        success = TaskControl.stop_task(
            task_id=task_id,
            task_type=task_type,
            graceful=graceful
        )

        if not success:
            logger.warning(f"⚠️ Failed to stop task {task_id}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop task {task_id}"
            )

        logger.info(f"✅ Task stopped via API: {task_id}")
        return {
            "success": True,
            "task_id": task_id,
            "task_type": task_type,
            "graceful": graceful,
            "signal": signal,
            "message": "Task stopped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [API_ERROR] Error stopping task {task_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error stopping task: {str(e)}"
        )


@router.post("/stop-all")
async def stop_all_tasks_endpoint(
    confirm: bool = False
):
    """
    Stop ALL Celery tasks immediately (emergency shutdown).

    ⚠️ **WARNING**: This will terminate ALL in-progress and queued tasks!

    **Parameters:**
    - `confirm`: Must be True to actually execute (safety check)

    **Response:**
    - `success`: Whether all tasks were stopped
    - `message`: Status message

    **Example:**
    ```
    # Stop all tasks (with confirmation)
    POST /api/v1/tasks/stop-all?confirm=true

    # Without confirmation (dry-run, returns error)
    POST /api/v1/tasks/stop-all
    ```

    **Response:**
    ```json
    {
        "success": true,
        "message": "All tasks stopped successfully",
        "file_tasks_stopped": true,
        "web_tasks_stopped": true,
        "warning": "All in-progress and queued tasks have been terminated"
    }
    ```
    """
    try:
        if not confirm:
            logger.warning("🟡 Stop-all requested without confirmation")
            raise HTTPException(
                status_code=400,
                detail="Must confirm with ?confirm=true to stop all tasks"
            )

        logger.warning("=" * 80)
        logger.warning("🔴 [API] STOPPING ALL TASKS - EMERGENCY SHUTDOWN")
        logger.warning("=" * 80)

        success = TaskControl.stop_all_tasks()

        if not success:
            logger.error("❌ Failed to stop all tasks")
            raise HTTPException(
                status_code=500,
                detail="Failed to stop all tasks"
            )

        logger.warning("✅ All tasks stopped via API")
        return {
            "success": True,
            "message": "All tasks stopped successfully",
            "file_tasks_stopped": True,
            "web_tasks_stopped": True,
            "warning": "All in-progress and queued tasks have been terminated"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [API_ERROR] Error stopping all tasks: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error stopping all tasks: {str(e)}"
        )


@router.post("/stop/file/{task_id}")
async def stop_file_task_endpoint(
    task_id: str,
    graceful: bool = False
):
    """
    Stop a file processing task specifically.

    **Parameters:**
    - `task_id`: Celery file processing task ID
    - `graceful`: Use SIGTERM (True) or SIGKILL (False)

    **Response:**
    ```json
    {
        "success": true,
        "task_id": "abc-123-def-456",
        "task_type": "file",
        "signal": "SIGKILL",
        "message": "File task stopped successfully"
    }
    ```
    """
    try:
        logger.info(f"📡 [API] Stop file task: {task_id}")

        signal = "SIGTERM" if graceful else "SIGKILL"
        success = TaskControl.stop_file_task(task_id, graceful)

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop file task {task_id}"
            )

        logger.info(f"✅ File task stopped: {task_id}")
        return {
            "success": True,
            "task_id": task_id,
            "task_type": "file",
            "signal": signal,
            "message": "File task stopped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error stopping file task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/web/{task_id}")
async def stop_web_task_endpoint(
    task_id: str,
    graceful: bool = False
):
    """
    Stop a website scraping task specifically.

    **Parameters:**
    - `task_id`: Celery web scraping task ID
    - `graceful`: Use SIGTERM (True) or SIGKILL (False)

    **Response:**
    ```json
    {
        "success": true,
        "task_id": "xyz-789-ghi-012",
        "task_type": "web",
        "signal": "SIGKILL",
        "message": "Web task stopped successfully"
    }
    ```
    """
    try:
        logger.info(f"📡 [API] Stop web task: {task_id}")

        signal = "SIGTERM" if graceful else "SIGKILL"
        success = TaskControl.stop_web_task(task_id, graceful)

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop web task {task_id}"
            )

        logger.info(f"✅ Web task stopped: {task_id}")
        return {
            "success": True,
            "task_id": task_id,
            "task_type": "web",
            "signal": signal,
            "message": "Web task stopped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error stopping web task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def task_control_status():
    """
    Get current task control status and queue information.

    **Response:**
    ```json
    {
        "file_redis_available": true,
        "web_redis_available": true,
        "file_task_queue_length": 5,
        "web_task_queue_length": 3,
        "message": "Task control is operational"
    }
    ```

    **Status codes:**
    - `file_redis_available`: Whether file Redis (DB 0) is connected
    - `web_redis_available`: Whether web Redis (DB 1) is connected
    - `file_task_queue_length`: Number of pending file tasks
    - `web_task_queue_length`: Number of pending web tasks

    **Example:**
    ```
    GET /api/v1/tasks/status
    ```
    """
    try:
        logger.info("📡 [API] Task status request")

        status = TaskControl.status_summary()

        logger.info(f"✅ Status retrieved: {status}")
        return status

    except Exception as e:
        logger.error(f"❌ Error getting task status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting status: {str(e)}"
        )


@router.post("/health-check")
async def task_control_health():
    """
    Health check for task control system.

    **Response:**
    ```json
    {
        "healthy": true,
        "file_redis_connected": true,
        "web_redis_connected": true,
        "message": "Task control system is operational"
    }
    ```

    **Status Indicators:**
    - `healthy`: True if at least one Redis connection is active
    - `file_redis_connected`: File task Redis (DB 0)
    - `web_redis_connected`: Web task Redis (DB 1)

    **Example:**
    ```
    POST /api/v1/tasks/health-check
    ```
    """
    try:
        logger.debug("📡 [API] Task control health check")

        status = TaskControl.status_summary()

        # Consider healthy if no errors and at least one redis is available
        healthy = (
            "error" not in status and
            (status.get("file_redis_available") or status.get("web_redis_available"))
        )

        return {
            "healthy": healthy,
            "file_redis_connected": status.get("file_redis_available", False),
            "web_redis_connected": status.get("web_redis_available", False),
            "message": "Task control system is operational" if healthy else "Task control system has issues"
        }

    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e),
            "message": "Task control system is unavailable"
        }
