"""
Test HTTPX Trace Context Propagation
Verifies that HTTPX calls include traceparent headers
"""
import asyncio
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.console.trace import ConsoleSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import httpx

# Configure minimal OTel for testing
tracer_provider = TracerProvider()
span_processor = SimpleSpanProcessor(ConsoleSpanExporter())
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)

# Enable HTTPX instrumentation
HTTPXClientInstrumentor.instrument()

async def test_trace_propagation():
    """Test that HTTPX calls include traceparent headers"""
    
    # Create a span to simulate API Gateway request
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("api-gateway-request") as span:
        print(f"🔍 Created span: {span.get_span_context().trace_id}")
        
        # Make HTTP call to microservice
        async with httpx.AsyncClient() as client:
            # This should automatically include traceparent header
            response = await client.get("https://httpbin.org/get")
            
            # Check if traceparent header was sent
            if "traceparent" in response.request.headers:
                print(f"✅ traceparent header found: {response.request.headers['traceparent']}")
            else:
                print("❌ traceparent header NOT found")
            
            print(f"📊 Status: {response.status_code}")
            print(f"🌐 URL: {response.request.url}")

if __name__ == "__main__":
    asyncio.run(test_trace_propagation())
