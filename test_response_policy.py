#!/usr/bin/env python3
"""
Test script to verify response_policy persistence issue
"""

import asyncio
import aiohttp
import json

API_BASE_URL = "https://api-gateway-common.up.railway.app/api/v1/gateway"

async def test_response_policy_persistence():
    """Test response_policy persistence"""
    
    # Test data with response_policy: 100
    config_data = {
        "admin_emails": ["globistaan@gmail.com", "v.pramanick@gmail.com"],
        "human_agents": ["globistaan@gmail.com", "v.pramanick@gmail.com"],
        "hil_enabled": True,
        "security": {
            "response_timeout": 30,
            "remove_pii": False,
            "restrict_config": False
        },
        "response_policy": 100,  # This should be persisted
        "data_management": {
            "backup_logs": False
        },
        "persona": {
            "system_prompt": "You are Friendly Receptionist, a helpful AI assistant. Your role is to assist users with their questions and provide accurate, helpful responses.",
            "selected_persona": "Friendly Receptionist"
        }
    }
    
    print("🔍 Testing response_policy persistence...")
    print(f"📤 Sending config with response_policy: {config_data['response_policy']}")
    
    try:
        async with aiohttp.ClientSession() as session:
            # First, save the configuration
            print("\n1️⃣ Saving configuration...")
            async with session.post(
                f"{API_BASE_URL}/configuration/chatAgentConfig",
                json=config_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                result = await response.json()
                print(f"   Status: {response.status}")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                if response.status == 200:
                    print("✅ Configuration saved successfully")
                else:
                    print(f"❌ Failed to save: {result}")
                    return
            
            # Wait a moment for persistence
            await asyncio.sleep(1)
            
            # Then, retrieve the configuration to verify
            print("\n2️⃣ Retrieving configuration...")
            async with session.get(
                f"{API_BASE_URL}/configuration/chatAgentConfig",
                headers={"Content-Type": "application/json"}
            ) as response:
                result = await response.json()
                print(f"   Status: {response.status}")
                
                if response.status == 200:
                    print("✅ Configuration retrieved successfully")
                    
                    # Check if response_policy is persisted
                    if 'data' in result and 'response_policy' in result['data']:
                        persisted_value = result['data']['response_policy']
                        print(f"📊 Persisted response_policy: {persisted_value}")
                        
                        if persisted_value == 100:
                            print("✅ SUCCESS: response_policy persisted correctly!")
                        else:
                            print(f"❌ FAILURE: response_policy was {persisted_value}, expected 100")
                    else:
                        print("❌ FAILURE: response_policy not found in response")
                        print(f"   Response data: {json.dumps(result, indent=2)}")
                else:
                    print(f"❌ Failed to retrieve: {result}")
                    return
            
            print("\n3️⃣ Testing direct metadata endpoint...")
            async with session.get(
                f"{API_BASE_URL}/configuration/test",
                headers={"Content-Type": "application/json"}
            ) as response:
                result = await response.json()
                print(f"   Status: {response.status}")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
    except Exception as e:
        print(f"❌ Error during test: {e}")

if __name__ == "__main__":
    asyncio.run(test_response_policy_persistence())
