#!/usr/bin/env python3
"""
Simple test script to check if the chatbot orchestration service can start.
This will help diagnose the 502 Bad Gateway error.
"""

import os
import sys
import traceback

# Add the project directory to the path
sys.path.insert(0, '/Users/bejoypramanick/iCloud Drive (Archive) - 1/Desktop/globistaan/projects/knowledgebot-railway-backend')

def test_service_imports():
    """Test if the service modules can be imported."""

    print("🔍 Testing Chatbot Orchestration Service Imports")
    print("=" * 50)

    # Check environment variables
    print("\n📋 Environment Variables Check:")
    required_vars = ['GEMINI_API_KEY', 'CHATBOT_ORCH_PORT', 'PORT']
    optional_vars = ['RAILWAY_POSTGRES_URL', 'NEON_DB_URL']

    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {'*' * len(value) if 'KEY' in var else value[:20] + '...' if len(value) > 20 else value}")
        else:
            print(f"❌ {var}: NOT SET")

    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"ℹ️  {var}: SET (length: {len(value)})")
        else:
            print(f"ℹ️  {var}: NOT SET (optional)")

    # Check if we can import the service
    print("\n📦 Module Import Test:")

    try:
        print("Testing shared modules...")
        from shared.config import settings
        print("✅ Successfully imported shared.config")

        from shared.db import init_railway_db, init_neon_db
        print("✅ Successfully imported shared.db")

        print("Testing FastAPI imports...")
        from fastapi import FastAPI
        print("✅ Successfully imported FastAPI")

        print("Testing Pydantic AI...")
        from pydantic_ai import Agent
        print("✅ Successfully imported pydantic_ai")

        print("Testing Google GenAI...")
        from google import genai
        print("✅ Successfully imported google.genai")

        print("Testing chatbot orchestration main...")
        from services.chatbot_orchestration.main import app
        print("✅ Successfully imported chatbot orchestration app")

        return True

    except Exception as e:
        print(f"❌ Import failed: {e}")
        print("Full traceback:")
        traceback.print_exc()
        return False

def analyze_potential_issues():
    """Analyze potential issues that could cause 502 errors."""

    print("\n🔍 Analyzing Potential Issues:")
    print("=" * 30)

    issues = []

    # Check GEMINI_API_KEY
    gemini_key = os.getenv('GEMINI_API_KEY')
    if not gemini_key:
        issues.append("❌ GEMINI_API_KEY is not set - this will prevent the AI agent from working")
    elif len(gemini_key) < 10:
        issues.append("⚠️  GEMINI_API_KEY seems too short - verify it's correct")

    # Check port configuration
    port = os.getenv('CHATBOT_ORCH_PORT') or os.getenv('PORT') or '8003'
    print(f"ℹ️  Service will try to bind to port: {port}")

    # Check database URLs
    railway_db = os.getenv('RAILWAY_POSTGRES_URL')
    neon_db = os.getenv('NEON_DB_URL')

    if railway_db:
        print("ℹ️  Railway PostgreSQL URL is configured")
    else:
        print("ℹ️  Railway PostgreSQL URL not set (optional)")

    if neon_db:
        print("ℹ️  Neon DB URL is configured")
    else:
        print("ℹ️  Neon DB URL not set (optional)")

    # Railway-specific issues
    print("\n🚂 Railway-Specific Checks:")
    railway_env_vars = [
        'RAILWAY_PROJECT_ID',
        'RAILWAY_ENVIRONMENT_ID',
        'RAILWAY_SERVICE_ID',
        'RAILWAY_SERVICE_NAME'
    ]

    railway_vars_set = 0
    for var in railway_env_vars:
        if os.getenv(var):
            railway_vars_set += 1

    if railway_vars_set == 0:
        issues.append("ℹ️  No Railway environment variables detected - this might be a local test")

    print(f"ℹ️  {railway_vars_set}/{len(railway_env_vars)} Railway environment variables are set")

    return issues

def main():
    """Main diagnostic function."""

    print("🧪 Chatbot Orchestration Service Diagnostic Test")
    print("This will help identify why you're getting 502 errors on Railway")
    print()

    # Test basic imports
    imports_ok = test_service_imports()

    # Analyze potential issues
    issues = analyze_potential_issues()

    # Summary
    print("\n📋 Diagnostic Summary:")
    if imports_ok:
        print("✅ Basic imports successful - service should be able to start")
    else:
        print("❌ Import failures detected - service will not start")

    if issues:
        print("\n🚨 Potential Issues Found:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ No obvious configuration issues detected")

    print("\n🔧 Recommended Next Steps:")
    print("1. Check Railway deployment logs for startup errors")
    print("2. Verify GEMINI_API_KEY is set in Railway environment variables")
    print("3. Check if database URLs are correct (if using database features)")
    print("4. Ensure Docker container has all required Python packages")
    print("5. Try redeploying the service in Railway")

    print("\n📊 Current Environment:")
    print(f"  Python: {sys.version}")
    print(f"  Working Directory: {os.getcwd()}")
    print(f"  Python Path: {sys.path[:3]}...")

if __name__ == "__main__":
    main()