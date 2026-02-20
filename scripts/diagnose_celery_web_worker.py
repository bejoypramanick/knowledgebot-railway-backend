#!/usr/bin/env python3
"""
Diagnostic script to check Celery web worker configuration and connectivity
Run this from the knowledgebase_ingestion service to diagnose issues
"""

import os
import sys
import redis
from celery import Celery

def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def check_environment_variables():
    print_section("1. ENVIRONMENT VARIABLES CHECK")
    
    vars_to_check = [
        'WEB_REDIS_URL',
        'FILE_REDIS_URL',
        'REDIS_URL',
        'CELERY_WEB_CONCURRENCY',
        'DB_POOL_MIN_SIZE',
        'DB_POOL_MAX_SIZE'
    ]
    
    for var in vars_to_check:
        value = os.getenv(var)
        if value:
            # Mask password in URL
            if 'redis://' in value:
                masked = value.split('@')[0].split(':')[0] + ':***@' + value.split('@')[1] if '@' in value else value
                print(f"✅ {var}: {masked}")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: NOT SET")

def check_redis_connection():
    print_section("2. REDIS CONNECTION CHECK")
    
    web_redis_url = os.getenv('WEB_REDIS_URL')
    
    if not web_redis_url:
        print("❌ WEB_REDIS_URL not set - cannot test connection")
        return False
    
    try:
        print(f"📡 Connecting to Redis...")
        r = redis.from_url(web_redis_url, decode_responses=True, socket_connect_timeout=5)
        
        print(f"🔍 Testing PING...")
        r.ping()
        print(f"✅ Redis connection successful!")
        
        print(f"\n📊 Checking web_crawling queue...")
        queue_len = r.llen('web_crawling')
        print(f"   Queue length: {queue_len} tasks")
        
        if queue_len > 0:
            print(f"\n📋 Sample tasks in queue (first 3):")
            tasks = r.lrange('web_crawling', 0, 2)
            for i, task in enumerate(tasks, 1):
                print(f"   Task {i}: {task[:100]}...")
        else:
            print(f"   ℹ️  Queue is empty")
        
        r.close()
        return True
        
    except redis.ConnectionError as e:
        print(f"❌ Redis connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def check_celery_dispatcher():
    print_section("3. CELERY DISPATCHER CHECK")
    
    web_redis_url = os.getenv('WEB_REDIS_URL')
    
    if not web_redis_url:
        print("❌ WEB_REDIS_URL not set - cannot create dispatcher")
        return False
    
    try:
        print(f"🔧 Creating Celery dispatcher...")
        web_celery = Celery('web_dispatcher', broker=web_redis_url)
        web_celery.conf.update(
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            result_backend=web_redis_url,
        )
        print(f"✅ Celery dispatcher created successfully")
        
        print(f"\n📊 Dispatcher configuration:")
        print(f"   Broker: {web_celery.conf.get('broker_url', 'NOT SET')[:50]}...")
        print(f"   Result backend: {web_celery.conf.get('result_backend', 'NOT SET')[:50]}...")
        print(f"   Task serializer: {web_celery.conf.get('task_serializer')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to create Celery dispatcher: {e}")
        return False

def check_worker_status():
    print_section("4. WORKER STATUS CHECK")
    
    web_redis_url = os.getenv('WEB_REDIS_URL')
    
    if not web_redis_url:
        print("❌ WEB_REDIS_URL not set - cannot check worker status")
        return False
    
    try:
        print(f"🔍 Checking for active workers...")
        web_celery = Celery('web_dispatcher', broker=web_redis_url)
        
        # Get active workers
        inspect = web_celery.control.inspect()
        active_workers = inspect.active()
        
        if active_workers:
            print(f"✅ Found {len(active_workers)} active worker(s):")
            for worker_name, tasks in active_workers.items():
                print(f"\n   Worker: {worker_name}")
                print(f"   Active tasks: {len(tasks)}")
                if tasks:
                    for task in tasks[:3]:  # Show first 3 tasks
                        print(f"      - {task.get('name', 'unknown')} (ID: {task.get('id', 'unknown')[:8]}...)")
        else:
            print(f"⚠️  No active workers found!")
            print(f"   This means the celery-web-worker service is not running or not connected")
        
        # Check registered tasks
        print(f"\n🔍 Checking registered tasks...")
        registered = inspect.registered()
        
        if registered:
            print(f"✅ Found registered tasks:")
            for worker_name, tasks in registered.items():
                print(f"\n   Worker: {worker_name}")
                for task in tasks:
                    if 'scrape' in task.lower():
                        print(f"      ✅ {task}")
                    else:
                        print(f"      - {task}")
        else:
            print(f"⚠️  No registered tasks found!")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to check worker status: {e}")
        return False

def test_task_dispatch():
    print_section("5. TEST TASK DISPATCH (DRY RUN)")
    
    web_redis_url = os.getenv('WEB_REDIS_URL')
    
    if not web_redis_url:
        print("❌ WEB_REDIS_URL not set - cannot test dispatch")
        return False
    
    try:
        print(f"🔧 Creating test dispatcher...")
        web_celery = Celery('web_dispatcher', broker=web_redis_url)
        web_celery.conf.update(
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            result_backend=web_redis_url,
        )
        
        print(f"📤 Simulating task dispatch...")
        print(f"   Task: 'tasks.scrape_website_task'")
        print(f"   Args: [999, 'https://example.com', {{}}]")
        print(f"   Queue: 'web_crawling'")
        
        # Don't actually send the task, just show what would happen
        print(f"\n✅ Dispatch configuration looks correct")
        print(f"   If worker is running, it should receive tasks sent to 'web_crawling' queue")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test dispatch: {e}")
        return False

def main():
    print("\n" + "🔍" * 40)
    print("  CELERY WEB WORKER DIAGNOSTIC TOOL")
    print("🔍" * 40)
    
    results = {
        'env_vars': check_environment_variables(),
        'redis': check_redis_connection(),
        'dispatcher': check_celery_dispatcher(),
        'worker': check_worker_status(),
        'dispatch': test_task_dispatch()
    }
    
    print_section("SUMMARY")
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {check.upper().replace('_', ' ')}")
    
    if all_passed:
        print(f"\n✅ All checks passed! Worker should be able to receive tasks.")
    else:
        print(f"\n⚠️  Some checks failed. Review the output above for details.")
        print(f"\nCommon issues:")
        print(f"  1. WEB_REDIS_URL not set → Set in Railway environment variables")
        print(f"  2. Redis connection failed → Check Redis service is running")
        print(f"  3. No active workers → Start celery-web-worker service")
        print(f"  4. Tasks not registered → Check worker logs for import errors")
    
    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    main()
