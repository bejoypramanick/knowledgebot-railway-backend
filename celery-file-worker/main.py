"""
FastAPI application for File Processing Worker
Polls Redis for file processing tasks and executes them asynchronously
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.otel_logger import get_otel_logger
from shared.middleware import CorrelationIDMiddleware
from shared.redis_message_queue import redis_message_queue
from service.processing_service import process_file_content

logger = get_otel_logger("celery-file-worker", "celery-file-worker")

# Background task for worker loop
worker_loop_task = None


async def file_worker_loop():
    """
    Main worker loop that polls Redis for file tasks and processes them.
    Runs continuously in the background.
    """
    logger.info("🚀 File worker loop started - waiting for tasks from Redis")

    while True:
        try:
            # Block waiting for next task with 5-second timeout
            task = redis_message_queue.get_file_task(timeout=5)

            if task:
                logger.info(f"📥 Got file task from Redis: file_id={task.get('file_id')}")

                try:
                    # Process the file
                    await process_file_content(
                        original_filename=task['original_filename'],
                        file_display_name=task['file_display_name'],
                        s3_key=task['s3_key'],
                        file_size=task['file_size'],
                        user_email=task['user_email'],
                        celery_task_id=task['celery_task_id']
                    )
                    logger.info(f"✅ Completed file task: file_id={task.get('file_id')}")

                except Exception as e:
                    logger.error(f"❌ Error processing file task: {e}", exc_info=True)
                    # Error handling is done by process_file_content publishing error result

            # Small sleep to prevent busy-waiting
            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"❌ Error in file worker loop: {e}", exc_info=True)
            await asyncio.sleep(1)  # Back off on error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    global worker_loop_task

    try:
        logger.info("🚀 File worker service starting up")

        # Check Redis connection
        if not redis_message_queue.is_available():
            logger.error("❌ Redis not available - worker cannot start")
            raise Exception("Redis connection failed")

        logger.info("✅ Redis connection verified")

        # Start the background worker loop
        worker_loop_task = asyncio.create_task(file_worker_loop())
        logger.info("✅ File worker loop task created")

        yield

    except Exception as e:
        logger.error(f"❌ Error in lifespan startup: {e}")
        raise

    finally:
        # Cleanup on shutdown
        if worker_loop_task:
            logger.info("🛑 Shutting down file worker loop...")
            worker_loop_task.cancel()
            try:
                await worker_loop_task
            except asyncio.CancelledError:
                logger.info("✅ File worker loop cancelled cleanly")


app = FastAPI(
    title="File Processing Worker",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include internal router for health checks only
from routers.router import router
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"service": "celery-file-worker", "status": "running", "mode": "Redis-polling"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "celery-file-worker",
        "redis_available": redis_message_queue.is_available(),
        "mode": "Redis-polling"
    }
