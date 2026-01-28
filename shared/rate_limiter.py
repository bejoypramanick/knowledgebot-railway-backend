"""
Rate Limiter for API Endpoints
Provides rate limiting functionality for metrics endpoints and other APIs
"""
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Tuple

from fastapi import HTTPException, Request
from fastapi.security import HTTPException as FastAPIHTTPException

from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_size: int = 10  # Allow short bursts
    
class RateLimiter:
    """Token bucket rate limiter with multiple time windows"""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.requests: Dict[str, Dict[str, deque]] = defaultdict(lambda: {
            'minute': deque(maxlen=config.requests_per_minute),
            'hour': deque(maxlen=config.requests_per_hour),
            'day': deque(maxlen=config.requests_per_day),
            'burst': deque(maxlen=config.burst_size)
        })
        self._lock = asyncio.Lock()
    
    def _get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Try to get user ID from request state (set by auth middleware)
        if hasattr(request.state, 'user') and request.state.user:
            user_id = request.state.user.get('email') or request.state.user.get('uid')
            if user_id:
                return f"user:{user_id}"
        
        # Fall back to IP address
        client_ip = self._get_client_ip(request)
        return f"ip:{client_ip}"
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check for forwarded IP headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the list
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to client IP
        return request.client.host if request.client else "unknown"
    
    async def is_allowed(self, request: Request) -> Tuple[bool, Dict[str, int]]:
        """Check if request is allowed and return remaining limits"""
        async with self._lock:
            client_id = self._get_client_identifier(request)
            current_time = time.time()
            
            # Get or create client request tracking
            client_requests = self.requests[client_id]
            
            # Clean old requests from each time window
            minute_ago = current_time - 60
            hour_ago = current_time - 3600
            day_ago = current_time - 86400
            
            # Clean old requests
            client_requests['minute'] = deque(
                [req_time for req_time in client_requests['minute'] if req_time > minute_ago],
                maxlen=self.config.requests_per_minute
            )
            client_requests['hour'] = deque(
                [req_time for req_time in client_requests['hour'] if req_time > hour_ago],
                maxlen=self.config.requests_per_hour
            )
            client_requests['day'] = deque(
                [req_time for req_time in client_requests['day'] if req_time > day_ago],
                maxlen=self.config.requests_per_day
            )
            
            # Check burst limit first (short-term protection)
            recent_burst = [req_time for req_time in client_requests['burst'] 
                           if current_time - req_time < 10]  # 10-second burst window
            
            if len(recent_burst) >= self.config.burst_size:
                return False, {
                    'remaining_minute': max(0, self.config.requests_per_minute - len(client_requests['minute'])),
                    'remaining_hour': max(0, self.config.requests_per_hour - len(client_requests['hour'])),
                    'remaining_day': max(0, self.config.requests_per_day - len(client_requests['day'])),
                    'burst_remaining': 0,
                    'retry_after': 10
                }
            
            # Check all time windows
            if (len(client_requests['minute']) >= self.config.requests_per_minute or
                len(client_requests['hour']) >= self.config.requests_per_hour or
                len(client_requests['day']) >= self.config.requests_per_day):
                
                # Calculate retry after time
                retry_after = 60  # Default to minute
                if len(client_requests['hour']) >= self.config.requests_per_hour:
                    retry_after = max(retry_after, int(3600 - (current_time - client_requests['hour'][0])))
                if len(client_requests['day']) >= self.config.requests_per_day:
                    retry_after = max(retry_after, int(86400 - (current_time - client_requests['day'][0])))
                
                return False, {
                    'remaining_minute': max(0, self.config.requests_per_minute - len(client_requests['minute'])),
                    'remaining_hour': max(0, self.config.requests_per_hour - len(client_requests['hour'])),
                    'remaining_day': max(0, self.config.requests_per_day - len(client_requests['day'])),
                    'burst_remaining': max(0, self.config.burst_size - len(recent_burst)),
                    'retry_after': retry_after
                }
            
            # Add current request to all windows
            client_requests['minute'].append(current_time)
            client_requests['hour'].append(current_time)
            client_requests['day'].append(current_time)
            client_requests['burst'].append(current_time)
            
            return True, {
                'remaining_minute': self.config.requests_per_minute - len(client_requests['minute']),
                'remaining_hour': self.config.requests_per_hour - len(client_requests['hour']),
                'remaining_day': self.config.requests_per_day - len(client_requests['day']),
                'burst_remaining': self.config.burst_size - len(recent_burst),
                'retry_after': 0
            }
    
    async def get_rate_limit_headers(self, request: Request) -> Dict[str, str]:
        """Get rate limit headers for response"""
        allowed, limits = await self.is_allowed(request)
        
        return {
            'X-RateLimit-Limit-Minute': str(self.config.requests_per_minute),
            'X-RateLimit-Remaining-Minute': str(limits['remaining_minute']),
            'X-RateLimit-Limit-Hour': str(self.config.requests_per_hour),
            'X-RateLimit-Remaining-Hour': str(limits['remaining_hour']),
            'X-RateLimit-Limit-Day': str(self.config.requests_per_day),
            'X-RateLimit-Remaining-Day': str(limits['remaining_day']),
            'X-RateLimit-Burst-Remaining': str(limits['burst_remaining']),
            'X-RateLimit-Retry-After': str(limits['retry_after'])
        }

class RateLimitMiddleware:
    """FastAPI middleware for rate limiting"""
    
    def __init__(self, limiter: RateLimiter):
        self.limiter = limiter
    
    async def __call__(self, request: Request, call_next):
        """Rate limiting middleware"""
        # Skip rate limiting for health checks and static assets
        if request.url.path in ['/health', '/docs', '/openapi.json', '/favicon.ico']:
            return await call_next(request)
        
        # Check rate limit
        allowed, limits = await self.limiter.is_allowed(request)
        
        if not allowed:
            raise FastAPIHTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    'Retry-After': str(limits['retry_after']),
                    'X-RateLimit-Limit-Minute': str(self.limiter.config.requests_per_minute),
                    'X-RateLimit-Remaining-Minute': str(limits['remaining_minute']),
                    'X-RateLimit-Limit-Hour': str(self.limiter.config.requests_per_hour),
                    'X-RateLimit-Remaining-Hour': str(limits['remaining_hour']),
                    'X-RateLimit-Limit-Day': str(self.limiter.config.requests_per_day),
                    'X-RateLimit-Remaining-Day': str(limits['remaining_day']),
                }
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to response
        headers = await self.limiter.get_rate_limit_headers(request)
        for key, value in headers.items():
            response.headers[key] = value
        
        return response

# Predefined rate limit configurations
METRICS_RATE_LIMIT = RateLimitConfig(
    requests_per_minute=30,    # Stricter for metrics endpoints
    requests_per_hour=500,
    requests_per_day=5000,
    burst_size=5
)

ADMIN_RATE_LIMIT = RateLimitConfig(
    requests_per_minute=60,
    requests_per_hour=1000,
    requests_per_day=10000,
    burst_size=10
)

API_RATE_LIMIT = RateLimitConfig(
    requests_per_minute=100,
    requests_per_hour=2000,
    requests_per_day=20000,
    burst_size=20
)

# Global rate limiters
_rate_limiters: Dict[str, RateLimiter] = {}

def get_rate_limiter(name: str, config: RateLimitConfig) -> RateLimiter:
    """Get or create a rate limiter"""
    if name not in _rate_limiters:
        _rate_limiters[name] = RateLimiter(config)
    return _rate_limiters[name]

def create_rate_limit_decorator(limiter_name: str, config: RateLimitConfig):
    """Create a rate limit decorator for FastAPI endpoints"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract request from kwargs (FastAPI dependency injection)
            request = kwargs.get('request')
            if not request:
                # Try to get request from args
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request:
                limiter = get_rate_limiter(limiter_name, config)
                allowed, limits = await limiter.is_allowed(request)
                
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded",
                        headers={
                            'Retry-After': str(limits['retry_after']),
                            'X-RateLimit-Limit-Minute': str(config.requests_per_minute),
                            'X-RateLimit-Remaining-Minute': str(limits['remaining_minute']),
                            'X-RateLimit-Limit-Hour': str(config.requests_per_hour),
                            'X-RateLimit-Remaining-Hour': str(limits['remaining_hour']),
                            'X-RateLimit-Limit-Day': str(config.requests_per_day),
                            'X-RateLimit-Remaining-Day': str(limits['remaining_day']),
                        }
                    )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Rate limiting decorators
@create_rate_limit_decorator("metrics", METRICS_RATE_LIMIT)
async def rate_limit_metrics():
    """Rate limiting decorator for metrics endpoints"""

@create_rate_limit_decorator("admin", ADMIN_RATE_LIMIT)
async def rate_limit_admin():
    """Rate limiting decorator for admin endpoints"""

@create_rate_limit_decorator("api", API_RATE_LIMIT)
async def rate_limit_api():
    """Rate limiting decorator for general API endpoints"""
