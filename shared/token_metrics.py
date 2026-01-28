"""
Token Tracking Metrics and Monitoring
Provides metrics collection and monitoring for token tracking failures and performance
"""
import time
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)

@dataclass
class TokenMetrics:
    """Metrics for token tracking operations"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    validation_errors: int = 0
    connection_errors: int = 0
    unexpected_errors: int = 0
    total_tokens_tracked: int = 0
    average_response_time_ms: float = 0.0
    last_error: Optional[str] = None
    last_success_timestamp: Optional[float] = None
    error_rate: float = 0.0
    
    def calculate_error_rate(self) -> float:
        """Calculate error rate as percentage"""
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100
    
    def update_success(self, tokens_tracked: int = 0, response_time_ms: float = 0.0):
        """Update metrics for successful operation"""
        self.total_calls += 1
        self.successful_calls += 1
        self.total_tokens_tracked += tokens_tracked
        self.last_success_timestamp = time.time()
        
        # Update average response time
        if response_time_ms > 0:
            total_time = self.average_response_time_ms * (self.successful_calls - 1) + response_time_ms
            self.average_response_time_ms = total_time / self.successful_calls
        
        self.error_rate = self.calculate_error_rate()
    
    def update_failure(self, error_type: str, error_message: str):
        """Update metrics for failed operation"""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_error = f"{error_type}: {error_message}"
        
        # Update specific error counters
        if error_type == "ValueError":
            self.validation_errors += 1
        elif error_type == "ConnectionError":
            self.connection_errors += 1
        else:
            self.unexpected_errors += 1
        
        self.error_rate = self.calculate_error_rate()

class TokenMetricsCollector:
    """Collects and manages token tracking metrics"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics: Dict[str, TokenMetrics] = defaultdict(TokenMetrics)
        self.response_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self._lock = asyncio.Lock()
    
    async def record_success(self, operation: str, tokens_tracked: int = 0, response_time_ms: float = 0.0):
        """Record a successful token tracking operation"""
        async with self._lock:
            self.metrics[operation].update_success(tokens_tracked, response_time_ms)
            self.response_history[operation].append({
                'timestamp': time.time(),
                'success': True,
                'tokens': tokens_tracked,
                'response_time_ms': response_time_ms
            })
    
    async def record_failure(self, operation: str, error_type: str, error_message: str):
        """Record a failed token tracking operation"""
        async with self._lock:
            self.metrics[operation].update_failure(error_type, error_message)
            self.response_history[operation].append({
                'timestamp': time.time(),
                'success': False,
                'error_type': error_type,
                'error_message': error_message
            })
    
    async def get_metrics(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get metrics for specific operation or all operations"""
        async with self._lock:
            if operation:
                return {operation: self._format_metrics(self.metrics[operation])}
            return {op: self._format_metrics(metrics) for op, metrics in self.metrics.items()}
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get overall health status of token tracking"""
        async with self._lock:
            total_calls = sum(m.total_calls for m in self.metrics.values())
            total_failures = sum(m.failed_calls for m in self.metrics.values())
            overall_error_rate = (total_failures / total_calls * 100) if total_calls > 0 else 0.0
            
            # Check if any operation has high error rate
            high_error_operations = [
                op for op, metrics in self.metrics.items() 
                if metrics.error_rate > 10.0  # 10% error rate threshold
            ]
            
            return {
                'healthy': overall_error_rate < 5.0 and len(high_error_operations) == 0,
                'overall_error_rate': overall_error_rate,
                'total_operations': total_calls,
                'high_error_operations': high_error_operations,
                'last_activity': max(
                    (m.last_success_timestamp for m in self.metrics.values() if m.last_success_timestamp),
                    default=0.0
                )
            }
    
    def _format_metrics(self, metrics: TokenMetrics) -> Dict[str, Any]:
        """Format metrics for serialization"""
        return {
            'total_calls': metrics.total_calls,
            'successful_calls': metrics.successful_calls,
            'failed_calls': metrics.failed_calls,
            'error_rate': metrics.error_rate,
            'validation_errors': metrics.validation_errors,
            'connection_errors': metrics.connection_errors,
            'unexpected_errors': metrics.unexpected_errors,
            'total_tokens_tracked': metrics.total_tokens_tracked,
            'average_response_time_ms': metrics.average_response_time_ms,
            'last_error': metrics.last_error,
            'last_success_timestamp': metrics.last_success_timestamp
        }

# Global metrics collector instance
_metrics_collector: Optional[TokenMetricsCollector] = None

def get_metrics_collector() -> TokenMetricsCollector:
    """Get or create the global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = TokenMetricsCollector()
    return _metrics_collector

async def record_token_tracking_success(operation: str, tokens_tracked: int = 0, response_time_ms: float = 0.0):
    """Record successful token tracking operation"""
    collector = get_metrics_collector()
    await collector.record_success(operation, tokens_tracked, response_time_ms)

async def record_token_tracking_failure(operation: str, error_type: str, error_message: str):
    """Record failed token tracking operation"""
    collector = get_metrics_collector()
    await collector.record_failure(operation, error_type, error_message)

async def get_token_tracking_metrics(operation: Optional[str] = None) -> Dict[str, Any]:
    """Get token tracking metrics"""
    collector = get_metrics_collector()
    return await collector.get_metrics(operation)

async def get_token_tracking_health() -> Dict[str, Any]:
    """Get token tracking health status"""
    collector = get_metrics_collector()
    return await collector.get_health_status()

class MetricsContext:
    """Context manager for measuring operation metrics"""
    
    def __init__(self, operation: str):
        self.operation = operation
        self.start_time = None
        self.tokens_tracked = 0
    
    def set_tokens_tracked(self, tokens: int):
        """Set the number of tokens tracked"""
        self.tokens_tracked = tokens
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        response_time_ms = (time.time() - self.start_time) * 1000 if self.start_time else 0.0
        
        if exc_type is None:
            await record_token_tracking_success(self.operation, self.tokens_tracked, response_time_ms)
        else:
            error_type = exc_type.__name__ if exc_type else "Unknown"
            error_message = str(exc_val) if exc_val else "No error message"
            await record_token_tracking_failure(self.operation, error_type, error_message)

# Decorator for automatic metrics collection
def track_token_metrics(operation: str):
    """Decorator to automatically track metrics for token tracking functions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            async with MetricsContext(operation) as metrics:
                try:
                    result = await func(*args, **kwargs)
                    
                    # Try to extract token count from result or kwargs
                    if isinstance(result, bool) and result:
                        # Function succeeded, try to get token count from kwargs
                        tokens = kwargs.get('total_tokens', 0) or kwargs.get('prompt_tokens', 0) + kwargs.get('completion_tokens', 0)
                        metrics.set_tokens_tracked(tokens)
                    
                    return result
                except Exception as e:
                    # Re-raise the exception after metrics are recorded
                    raise
        return wrapper
    return decorator
