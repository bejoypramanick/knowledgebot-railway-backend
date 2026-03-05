#!/usr/bin/env python3
"""
Test script to verify OpenTelemetry logging fix
This script tests that logs work correctly even without an active span context
"""
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.telemetry import setup_telemetry
from shared.otel_logger import get_otel_logger

def test_logging_without_span():
    """Test that logging works without an active span (startup scenario)"""
    print("=" * 60)
    print("Testing OpenTelemetry Logging Fix")
    print("=" * 60)
    
    # Initialize telemetry (this is where the error would occur)
    print("\n1. Setting up telemetry...")
    setup_telemetry("test-service")
    print("✅ Telemetry setup successful")
    
    # Get logger
    print("\n2. Getting OTel logger...")
    logger = get_otel_logger("test", "test-service")
    print("✅ Logger created successfully")
    
    # Test logging at different levels WITHOUT an active span
    print("\n3. Testing log levels without active span...")
    logger.info("This is an INFO log without span context")
    logger.warning("This is a WARNING log without span context")
    logger.error("This is an ERROR log without span context")
    logger.debug("This is a DEBUG log without span context")
    print("✅ All log levels work without span context")
    
    # Test standard logging
    print("\n4. Testing standard logging...")
    standard_logger = logging.getLogger("standard-test")
    standard_logger.info("Standard logger INFO message")
    standard_logger.warning("Standard logger WARNING message")
    print("✅ Standard logging works")
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED - No ValueError for missing otelTraceID")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_logging_without_span()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
