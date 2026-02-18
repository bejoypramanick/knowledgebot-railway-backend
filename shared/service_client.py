"""
Service-to-Service HTTP Client
Handles communication between different Railway services via internal URLs
"""
import os
import httpx
from typing import Dict, Any, Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("service_client", "shared")

class ServiceClient:
    """HTTP client for internal service communication"""
    
    def __init__(self):
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        self.base_urls = {
            'knowledgebase_ingestion': os.getenv('KNOWLEDGEBASE_INGESTION_URL', 'http://knowledge-base.railway.internal:8080'),
            'chatbot_orchestration': os.getenv('CHATBOT_ORCHESTRATION_URL', 'http://chatbot.railway.internal:8080'),
            'celery_web_worker': os.getenv('CELERY_WEB_WORKER_URL', 'http://celery-web-worker.railway.internal:8080'),
            'celery_file_worker': os.getenv('CELERY_FILE_WORKER_URL', 'http://celery-file-worker.railway.internal:8080'),
        }
    
    async def _make_request(self, service: str, method: str, endpoint: str, 
                          data: Optional[Dict[str, Any]] = None, 
                          params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make HTTP request to another service"""
        base_url = self.base_urls.get(service)
        if not base_url:
            raise ValueError(f"Unknown service: {service}")
        
        url = f"{base_url}{endpoint}"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method.upper() == 'GET':
                    response = await client.get(url, params=params)
                elif method.upper() == 'POST':
                    response = await client.post(url, json=data, params=params)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, params=params)
                elif method.upper() == 'PUT':
                    response = await client.put(url, json=data, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.json()
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error calling {service}{endpoint}: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error calling {service}{endpoint}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error calling {service}{endpoint}: {e}")
            raise
    
    async def purge_celery_queue(self, service: str) -> bool:
        """Purge Celery queue for a specific service"""
        try:
            result = await self._make_request(service, 'POST', '/internal/celery/purge')
            return result.get('success', False)
        except Exception as e:
            logger.warning(f"Failed to purge {service} Celery queue: {e}")
            return False
    
    async def revoke_celery_task(self, service: str, task_id: str) -> bool:
        """Revoke a specific Celery task in a service"""
        try:
            result = await self._make_request(service, 'POST', f'/internal/celery/revoke/{task_id}')
            return result.get('success', False)
        except Exception as e:
            logger.warning(f"Failed to revoke task {task_id} in {service}: {e}")
            return False
    
    async def cancel_all_tasks(self, service: str) -> bool:
        """Cancel all tasks in a service"""
        try:
            result = await self._make_request(service, 'POST', '/internal/cancel-all')
            return result.get('success', False)
        except Exception as e:
            logger.warning(f"Failed to cancel all tasks in {service}: {e}")
            return False
    
    async def health_check(self, service: str) -> bool:
        """Check if a service is healthy"""
        try:
            result = await self._make_request(service, 'GET', '/health')
            return result.get('status') == 'healthy'
        except Exception as e:
            logger.warning(f"Health check failed for {service}: {e}")
            return False

    async def dispatch_file_task(self, service: str, **kwargs) -> Dict[str, Any]:
        """Dispatch a file processing task to worker service"""
        try:
            result = await self._make_request(service, 'POST', '/internal/dispatch-file', data=kwargs)
            return result
        except Exception as e:
            logger.error(f"Failed to dispatch file task to {service}: {e}")
            return {"success": False, "error": str(e)}
    
    async def dispatch_website_task(self, service: str, **kwargs) -> Dict[str, Any]:
        """Dispatch a website scraping task to worker service"""
        try:
            result = await self._make_request(service, 'POST', '/internal/dispatch-website', data=kwargs)
            return result
        except Exception as e:
            logger.error(f"Failed to dispatch website task to {service}: {e}")
            return {"success": False, "error": str(e)}

# Global instance
service_client = ServiceClient()
