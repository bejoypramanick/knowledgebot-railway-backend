"""
FastAPI application for Website Processing Worker
Polls Redis for website scraping tasks and executes them asynchronously
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.otel_logger import get_otel_logger
from shared.middleware import CorrelationIDMiddleware
from shared.redis_message_queue import redis_message_queue
from service.processing_service import process_website_content

logger = get_otel_logger("celery-web-worker", "celery-web-worker")

# Background task for worker loop
worker_loop_task = None


async def web_worker_loop():
    """
    Main worker loop that polls Redis for website tasks and processes them.
    Runs continuously in the background.
    """
    logger.info("🚀 Web worker loop started - waiting for tasks from Redis")

    while True:
        try:
            # Block waiting for next task with 5-second timeout
            task = redis_message_queue.get_web_task(timeout=5)

            if task:
                logger.info(f"📥 Got web task from Redis: website_id={task.get('website_id')}")

                try:
                    # Process the website
                    await process_website_content(
                        website_id=task['website_id'],
                        url=task['url'],
                        max_depth=task['max_depth'],
                        max_pages=task['max_pages'],
                        max_concurrent=task['max_concurrent'],
                        delay_between_requests=task['delay_between_requests'],
                        user_email=task['user_email'],
                        celery_task_id=task['celery_task_id'],
                        **task.get('options', {})
                    )
                    logger.info(f"✅ Completed web task: website_id={task.get('website_id')}")

                except Exception as e:
                    logger.error(f"❌ Error processing web task: {e}", exc_info=True)
                    # Error handling is done by process_website_content publishing error result

            # Small sleep to prevent busy-waiting
            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"❌ Error in web worker loop: {e}", exc_info=True)
            await asyncio.sleep(1)  # Back off on error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    global worker_loop_task

    try:
        logger.info("🚀 Web worker service starting up")

        # Check Redis connection
        if not redis_message_queue.is_available():
            logger.error("❌ Redis not available - worker cannot start")
            raise Exception("Redis connection failed")

        logger.info("✅ Redis connection verified")

        # Start the background worker loop
        worker_loop_task = asyncio.create_task(web_worker_loop())
        logger.info("✅ Web worker loop task created")

        yield

    except Exception as e:
        logger.error(f"❌ Error in lifespan startup: {e}")
        raise

    finally:
        # Cleanup on shutdown
        if worker_loop_task:
            logger.info("🛑 Shutting down web worker loop...")
            worker_loop_task.cancel()
            try:
                await worker_loop_task
            except asyncio.CancelledError:
                logger.info("✅ Web worker loop cancelled cleanly")


app = FastAPI(
    title="Website Processing Worker",
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
    return {"service": "celery-web-worker", "status": "running", "mode": "Redis-polling"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "celery-web-worker",
        "redis_available": redis_message_queue.is_available(),
        "mode": "Redis-polling"
    }
