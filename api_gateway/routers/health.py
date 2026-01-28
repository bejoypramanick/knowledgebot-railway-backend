import time
import httpx
import logging
from typing import Dict
from fastapi import APIRouter, HTTPException, Request

from api_gateway.core.config import (
    KNOWLEDGEBASE_INGESTION_URL, 
    WEBSITE_CRAWLING_URL, 
    CHATBOT_ORCHESTRATION_URL
)
from shared.utils import log_endpoint_request

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health")
async def health_check(request: Request):
    """Health check endpoint - returns gateway status with detailed logging."""
    log_endpoint_request("api_gateway", "health", request)
    start_time = time.time()
    logger.info("🔍 Health check request received")

    try:
        health_status = {
            "status": "healthy",
            "service": "api-gateway",
            "timestamp": time.time(),
            "uptime_seconds": time.time() - getattr(request.app, 'start_time', time.time())
        }

        logger.info("✅ Application is responsive")
        logger.info(f"📊 Health status: {health_status['status']}")

        try:
            async with httpx.AsyncClient() as client:
                logger.info("✅ HTTP client initialization successful")
        except Exception as e:
            logger.error(f"❌ HTTP client initialization failed: {e}")
            health_status["status"] = "unhealthy"
            health_status["error"] = f"HTTP client error: {str(e)}"

        service_urls = {
            "knowledgebase_ingestion": KNOWLEDGEBASE_INGESTION_URL,
            "website_scraping": WEBSITE_CRAWLING_URL,
            "chatbot_orchestration": CHATBOT_ORCHESTRATION_URL
        }

        connectivity_checks = {}
        for service_name, url in service_urls.items():
            try:
                parsed_url = httpx.URL(url)
                connectivity_checks[service_name] = {
                    "url": url,
                    "reachable": True,
                    "scheme": parsed_url.scheme,
                    "host": parsed_url.host,
                    "port": parsed_url.port
                }
                logger.info(f"✅ {service_name} URL configured: {url}")
            except Exception as e:
                connectivity_checks[service_name] = {
                    "url": url,
                    "reachable": False,
                    "error": str(e)
                }
                logger.warning(f"⚠️  {service_name} URL configuration issue: {e}")
                health_status["status"] = "degraded"

        health_status["connectivity_checks"] = connectivity_checks

        duration = time.time() - start_time
        logger.info(f"⏱️ Health check duration: {duration:.3f}s")

        if health_status["status"] == "healthy":
            logger.info("🎉 Health check completed successfully")
        elif health_status["status"] == "degraded":
            logger.warning("⚠️  Health check completed with warnings")
        else:
            logger.error("❌ Health check failed")

        return health_status

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"⏱️ Health check heartbeat error after {duration:.3f}s")
        logger.error(f"💥 Critical health check error: {e}")
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@router.get("/status")
async def system_status():
    """Check connections to all downstream services with detailed logging."""
    start_time = time.time()
    logger.info("🔍 System status check initiated")

    services = {
        "knowledgebase": KNOWLEDGEBASE_INGESTION_URL,
        "website_scraping": WEBSITE_CRAWLING_URL,
        "chatbot": CHATBOT_ORCHESTRATION_URL
    }
    statuses = {"gateway": "online"}
    detailed_results = {
        "timestamp": time.time(),
        "overall_status": "checking",
        "services": {}
    }

    logger.info("🌐 Checking downstream service connectivity...")

    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url in services.items():
            service_start_time = time.time()
            logger.info(f"🔗 Checking {name} service at {url}")

            try:
                health_url = f"{url}/health"
                logger.info(f"📡 Making request to: {health_url}")

                resp = await client.get(health_url, timeout=5.0)

                service_duration = time.time() - service_start_time
                
                if resp.status_code == 200:
                    statuses[name] = "online"
                    logger.info(f"✅ {name} service is ONLINE (status: {resp.status_code})")

                    try:
                        response_data = resp.json()
                        detailed_results["services"][name] = {
                            "status": "online",
                            "http_status": resp.status_code,
                            "response_time_seconds": round(service_duration, 3),
                            "health_data": response_data
                        }
                    except Exception as parse_error:
                        detailed_results["services"][name] = {
                            "status": "online",
                            "http_status": resp.status_code,
                            "response_time_seconds": round(service_duration, 3),
                            "response_text": resp.text[:200]
                        }

                else:
                    statuses[name] = f"error: {resp.status_code}"
                    logger.error(f"❌ {name} service returned error status: {resp.status_code}")
                    detailed_results["services"][name] = {
                        "status": "error",
                        "http_status": resp.status_code,
                        "response_time_seconds": round(service_duration, 3),
                        "error": f"HTTP {resp.status_code}",
                        "response_preview": resp.text[:200]
                    }

            except httpx.TimeoutException as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"timeout: {str(e)}"
                logger.error(f"⏰ {name} service health check timed out")
                detailed_results["services"][name] = {
                    "status": "timeout",
                    "error": "Request timeout",
                    "response_time_seconds": round(service_duration, 3),
                    "timeout_seconds": 5.0
                }

            except httpx.ConnectError as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"unreachable: {str(e)}"
                logger.error(f"🚫 {name} service is unreachable: {e}")
                detailed_results["services"][name] = {
                    "status": "unreachable",
                    "error": str(e),
                    "response_time_seconds": round(service_duration, 3)
                }

            except Exception as e:
                service_duration = time.time() - service_start_time
                statuses[name] = f"error: {str(e)}"
                logger.error(f"💥 Unexpected error checking {name} service: {e}")
                detailed_results["services"][name] = {
                    "status": "error",
                    "error": str(e),
                    "response_time_seconds": round(service_duration, 3),
                    "error_type": type(e).__name__
                }

    online_services = sum(1 for status in statuses.values() if status == "online")
    total_services = len(services) + 1

    if online_services == total_services:
        detailed_results["overall_status"] = "healthy"
        logger.info("🎉 All services are healthy")
    elif online_services >= total_services - 1:
        detailed_results["overall_status"] = "degraded"
        logger.warning("⚠️  System is degraded - some services may be unavailable")
    else:
        detailed_results["overall_status"] = "unhealthy"
        logger.error("❌ System is unhealthy - critical services are down")

    return {
        "simple_status": statuses,
        "detailed_status": detailed_results
    }
