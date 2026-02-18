"""
Celery Dispatcher for Knowledgebase Ingestion Service
Used to dispatch tasks to workers without importing worker code directly.
"""
import os
from celery import Celery

# File processing: Redis DB 0
file_redis_url = os.getenv('FILE_REDIS_URL', os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Web crawling: Redis DB 1
web_redis_url = os.getenv('WEB_REDIS_URL', os.getenv('REDIS_URL', 'redis://localhost:6379/1'))

# Dispatcher app for file processing tasks (DB 0)
file_celery = Celery('file_dispatcher', broker=file_redis_url)
file_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
)

# Dispatcher app for web crawling tasks (DB 1)
web_celery = Celery('web_dispatcher', broker=web_redis_url)
web_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
)
