"""
OpenTelemetry Tracing Decorators
Automatically instrument routers, services, and DAOs with spans for complete request tracing
"""
import functools
import inspect
from typing import Any, Callable
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

def trace_function(
    span_name: str = None,
    layer: str = "function",
    capture_args: bool = True,
    capture_result: bool = False
):
    """
    Decorator to trace function execution with OpenTelemetry spans.
    
    Usage:
        @trace_function(layer="router")
        async def my_endpoint(...):
            ...
        
        @trace_function(layer="service")
        async def my_service_method(...):
            ...
        
        @trace_function(layer="dao")
        async def my_dao_query(...):
            ...
    
    Args:
        span_name: Custom span name (defaults to function name)
        layer: Layer type (router, service, dao, function)
        capture_args: Whether to capture function arguments as span attributes
        capture_result: Whether to capture return value as span attribute
    
    Returns:
        Decorated function with automatic span creation
    """
    def decorator(func: Callable) -> Callable:
        # Get function metadata
        func_name = func.__name__
        func_module = func.__module__
        is_async = inspect.iscoroutinefunction(func)
        
        # Determine span name
        final_span_name = span_name or f"{layer}.{func_name}"
        
        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> Any:
                tracer = trace.get_tracer(__name__)
                
                with tracer.start_as_current_span(final_span_name) as span:
                    # Add layer and function metadata
                    span.set_attribute("code.function", func_name)
                    span.set_attribute("code.namespace", func_module)
                    span.set_attribute("code.layer", layer)
                    
                    # Capture arguments if enabled
                    if capture_args:
                        _capture_arguments(span, func, args, kwargs)
                    
                    try:
                        # Execute function
                        result = await func(*args, **kwargs)
                        
                        # Mark span as successful
                        span.set_status(Status(StatusCode.OK))
                        
                        # Capture result if enabled
                        if capture_result and result is not None:
                            span.set_attribute("result.type", type(result).__name__)
                            if isinstance(result, (str, int, float, bool)):
                                span.set_attribute("result.value", str(result))
                        
                        return result
                        
                    except Exception as e:
                        # Record exception in span
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.set_attribute("error.type", type(e).__name__)
                        span.set_attribute("error.message", str(e))
                        raise
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs) -> Any:
                tracer = trace.get_tracer(__name__)
                
                with tracer.start_as_current_span(final_span_name) as span:
                    # Add layer and function metadata
                    span.set_attribute("code.function", func_name)
                    span.set_attribute("code.namespace", func_module)
                    span.set_attribute("code.layer", layer)
                    
                    # Capture arguments if enabled
                    if capture_args:
                        _capture_arguments(span, func, args, kwargs)
                    
                    try:
                        # Execute function
                        result = func(*args, **kwargs)
                        
                        # Mark span as successful
                        span.set_status(Status(StatusCode.OK))
                        
                        # Capture result if enabled
                        if capture_result and result is not None:
                            span.set_attribute("result.type", type(result).__name__)
                            if isinstance(result, (str, int, float, bool)):
                                span.set_attribute("result.value", str(result))
                        
                        return result
                        
                    except Exception as e:
                        # Record exception in span
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.set_attribute("error.type", type(e).__name__)
                        span.set_attribute("error.message", str(e))
                        raise
            
            return sync_wrapper
    
    return decorator


def _capture_arguments(span, func, args, kwargs):
    """Capture function arguments as span attributes"""
    try:
        # Get function signature
        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        
        # Capture each argument
        for param_name, param_value in bound_args.arguments.items():
            # Skip self, cls, request, response (too verbose)
            if param_name in ('self', 'cls', 'request', 'response', 'req'):
                continue
            
            # Capture primitive types
            if isinstance(param_value, (str, int, float, bool, type(None))):
                span.set_attribute(f"arg.{param_name}", str(param_value))
            # Capture type for complex objects
            else:
                span.set_attribute(f"arg.{param_name}.type", type(param_value).__name__)
    
    except Exception:
        # Don't fail if argument capture fails
        pass


# Convenience decorators for each layer
def trace_router(span_name: str = None, capture_args: bool = True):
    """Decorator for router/endpoint functions"""
    return trace_function(span_name=span_name, layer="router", capture_args=capture_args)


def trace_service(span_name: str = None, capture_args: bool = True):
    """Decorator for service layer functions"""
    return trace_function(span_name=span_name, layer="service", capture_args=capture_args)


def trace_dao(span_name: str = None, capture_args: bool = True, capture_result: bool = False):
    """Decorator for DAO layer functions"""
    return trace_function(span_name=span_name, layer="dao", capture_args=capture_args, capture_result=capture_result)


# Class decorator to automatically trace all methods
def trace_class(layer: str = "service", exclude_methods: list = None):
    """
    Class decorator to automatically trace all public methods.
    
    Usage:
        @trace_class(layer="service")
        class MyService:
            def method1(self):
                ...
            
            def method2(self):
                ...
    
    Args:
        layer: Layer type (service, dao)
        exclude_methods: List of method names to exclude from tracing
    
    Returns:
        Decorated class with all methods traced
    """
    exclude_methods = exclude_methods or ['__init__', '__del__', '__repr__', '__str__']
    
    def decorator(cls):
        # Get all methods
        for attr_name in dir(cls):
            # Skip private methods and excluded methods
            if attr_name.startswith('_') or attr_name in exclude_methods:
                continue
            
            attr = getattr(cls, attr_name)
            
            # Only decorate callable methods
            if callable(attr) and not isinstance(attr, type):
                # Create span name
                span_name = f"{layer}.{cls.__name__}.{attr_name}"
                
                # Apply tracing decorator
                traced_method = trace_function(
                    span_name=span_name,
                    layer=layer,
                    capture_args=True
                )(attr)
                
                # Replace method with traced version
                setattr(cls, attr_name, traced_method)
        
        return cls
    
    return decorator
