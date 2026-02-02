#!/usr/bin/env python3
"""
Comprehensive API Testing Script for KnowledgeBot Frontend Screens
Tests all 5 screens: ChatAgent Configuration, Widget Configuration, Chat Agent Performance, Chat Log, KnowledgeBase
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import Dict, Any, List

# Railway API Configuration
API_BASE_URL = "https://api-gateway-common.up.railway.app/api/v1/gateway"
API_TOKEN = "3216ea08-a123-45d4-b8de-dd971de81b8a"

class APITester:
    def __init__(self):
        self.base_url = API_BASE_URL
        self.token = API_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.results = {
            "chat_agent_config": {"tests": [], "passed": 0, "failed": 0},
            "widget_config": {"tests": [], "passed": 0, "failed": 0},
            "chat_performance": {"tests": [], "passed": 0, "failed": 0},
            "chat_log": {"tests": [], "passed": 0, "failed": 0},
            "knowledgebase": {"tests": [], "passed": 0, "failed": 0}
        }
    
    async def test_endpoint(self, method: str, endpoint: str, data: Dict = None, screen: str = "unknown", test_name: str = "unknown") -> Dict[str, Any]:
        """Test a single API endpoint"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "GET":
                    async with session.get(url, headers=self.headers) as response:
                        result = await response.json()
                        status = response.status
                elif method.upper() == "POST":
                    async with session.post(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        status = response.status
                elif method.upper() == "PUT":
                    async with session.put(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        status = response.status
                elif method.upper() == "DELETE":
                    async with session.delete(url, headers=self.headers) as response:
                        result = await response.json()
                        status = response.status
                else:
                    raise ValueError(f"Unsupported method: {method}")
            
            duration = time.time() - start_time
            success = 200 <= status < 300
            
            test_result = {
                "screen": screen,
                "test_name": test_name,
                "method": method,
                "endpoint": endpoint,
                "status": status,
                "success": success,
                "duration": duration,
                "response": result,
                "timestamp": datetime.now().isoformat()
            }
            
            self.results[screen]["tests"].append(test_result)
            if success:
                self.results[screen]["passed"] += 1
                print(f"✅ [{screen}] {test_name} - {method} {endpoint} - {status} ({duration:.2f}s)")
            else:
                self.results[screen]["failed"] += 1
                print(f"❌ [{screen}] {test_name} - {method} {endpoint} - {status} ({duration:.2f}s)")
                print(f"   Response: {json.dumps(result, indent=2)}")
            
            return test_result
            
        except Exception as e:
            duration = time.time() - start_time
            test_result = {
                "screen": screen,
                "test_name": test_name,
                "method": method,
                "endpoint": endpoint,
                "status": 0,
                "success": False,
                "duration": duration,
                "response": {"error": str(e)},
                "timestamp": datetime.now().isoformat()
            }
            
            self.results[screen]["tests"].append(test_result)
            self.results[screen]["failed"] += 1
            print(f"❌ [{screen}] {test_name} - {method} {endpoint} - ERROR ({duration:.2f}s)")
            print(f"   Error: {str(e)}")
            
            return test_result
    
    async def test_chat_agent_config(self):
        """Test Chat Agent Configuration screen APIs"""
        print("\n🎯 Testing Chat Agent Configuration APIs...")
        
        # Test 1: Get chatbot configuration
        await self.test_endpoint(
            "GET", 
            "/configuration/chatAgentConfig",
            screen="chat_agent_config",
            test_name="Get Chatbot Configuration"
        )
        
        # Test 2: Save chatbot configuration
        config_data = {
            "admin_emails": ["admin@example.com"],
            "human_agents": ["agent@example.com"],
            "hil_enabled": True,
            "security": {
                "response_timeout": 30,
                "remove_pii": False,
                "restrict_config": False
            },
            "response_policy": 30,
            "data_management": {
                "backup_logs": False
            },
            "persona": {
                "system_prompt": "You are a helpful AI assistant.",
                "selected_persona": "friendly-receptionist"
            }
        }
        
        await self.test_endpoint(
            "POST",
            "/configuration/chatAgentConfig",
            data=config_data,
            screen="chat_agent_config",
            test_name="Save Chatbot Configuration"
        )
        
        # Test 3: Get personas
        await self.test_endpoint(
            "GET",
            "/configuration/personas",
            screen="chat_agent_config",
            test_name="Get Personas"
        )
        
        # Test 4: Get performance metrics
        await self.test_endpoint(
            "GET",
            "/configuration/performance",
            screen="chat_agent_config",
            test_name="Get Performance Metrics"
        )
    
    async def test_widget_config(self):
        """Test Widget Configuration screen APIs"""
        print("\n🎯 Testing Widget Configuration APIs...")
        
        # Test 1: Get widget configuration
        await self.test_endpoint(
            "GET",
            "/configuration/widget",
            screen="widget_config",
            test_name="Get Widget Configuration"
        )
        
        # Test 2: Save widget configuration
        widget_data = {
            "display_name": "KnowledgeBot",
            "initial_message": "Hello! How can I help you today?",
            "theme": "light",
            "primary_color": "#3b82f6",
            "position": "bottom-right",
            "auto_show_duration": 5,
            "suggested_messages": [
                "What services do you offer?",
                "How can I contact support?",
                "Tell me about your products"
            ]
        }
        
        await self.test_endpoint(
            "POST",
            "/configuration/widget",
            data=widget_data,
            screen="widget_config",
            test_name="Save Widget Configuration"
        )
        
        # Test 3: Generate embed script
        embed_config = {
            "baseUrl": "https://your-domain.com",
            "theme": "light",
            "primaryColor": "#3b82f6",
            "position": "bottom-right"
        }
        
        await self.test_endpoint(
            "POST",
            "/configuration/widget/embed-script",
            data=embed_config,
            screen="widget_config",
            test_name="Generate Embed Script"
        )
    
    async def test_chat_performance(self):
        """Test Chat Agent Performance screen APIs"""
        print("\n🎯 Testing Chat Agent Performance APIs...")
        
        # Test 1: Get performance metrics
        await self.test_endpoint(
            "GET",
            "/configuration/performance",
            screen="chat_performance",
            test_name="Get Performance Metrics"
        )
        
        # Test 2: Get detailed token usage
        await self.test_endpoint(
            "GET",
            "/configuration/token-usage/detailed?limit=50",
            screen="chat_performance",
            test_name="Get Detailed Token Usage"
        )
    
    async def test_chat_log(self):
        """Test Chat Log screen APIs"""
        print("\n🎯 Testing Chat Log APIs...")
        
        # Test 1: Get admin chat sessions
        await self.test_endpoint(
            "GET",
            "/configuration/admin/chat-sessions",
            screen="chat_log",
            test_name="Get Admin Chat Sessions"
        )
        
        # Test 2: Get online agents
        await self.test_endpoint(
            "GET",
            "/configuration/admin/agents/online",
            screen="chat_log",
            test_name="Get Online Agents"
        )
        
        # Test 3: Get human agents
        await self.test_endpoint(
            "GET",
            "/configuration/human-agents",
            screen="chat_log",
            test_name="Get Human Agents"
        )
        
        # Test 4: Get chat logs
        await self.test_endpoint(
            "GET",
            "/configuration/chat-logs",
            screen="chat_log",
            test_name="Get Chat Logs"
        )
    
    async def test_knowledgebase(self):
        """Test KnowledgeBase Management screen APIs"""
        print("\n🎯 Testing KnowledgeBase Management APIs...")
        
        # Test 1: Get files
        await self.test_endpoint(
            "GET",
            "/knowledgebase/files",
            screen="knowledgebase",
            test_name="Get KnowledgeBase Files"
        )
        
        # Test 2: Get upload constraints
        await self.test_endpoint(
            "GET",
            "/knowledgebase/upload/constraints",
            screen="knowledgebase",
            test_name="Get Upload Constraints"
        )
        
        # Test 3: Test website scraping endpoint (without actual scraping)
        scrape_data = {
            "url": "https://example.com",
            "max_pages": 1,
            "crawl_mode": "single",
            "follow_links": False,
            "respect_robots_txt": True,
            "crawl_delay": 1
        }
        
        await self.test_endpoint(
            "POST",
            "/knowledgebase/scrape",
            data=scrape_data,
            screen="knowledgebase",
            test_name="Test Website Scraping"
        )
    
    async def run_all_tests(self):
        """Run all tests for all screens"""
        print("🚀 Starting Comprehensive API Testing for KnowledgeBot Frontend Screens")
        print("=" * 80)
        
        start_time = time.time()
        
        # Test all screens
        await self.test_chat_agent_config()
        await self.test_widget_config()
        await self.test_chat_performance()
        await self.test_chat_log()
        await self.test_knowledgebase()
        
        total_duration = time.time() - start_time
        
        # Print summary
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        
        total_passed = 0
        total_failed = 0
        
        for screen, results in self.results.items():
            passed = results["passed"]
            failed = results["failed"]
            total = passed + failed
            total_passed += passed
            total_failed += failed
            
            print(f"\n🎯 {screen.upper()}:")
            print(f"   ✅ Passed: {passed}/{total}")
            print(f"   ❌ Failed: {failed}/{total}")
            
            if failed > 0:
                print("   Failed tests:")
                for test in results["tests"]:
                    if not test["success"]:
                        print(f"     - {test['test_name']}: {test['status']} {test['endpoint']}")
        
        print(f"\n🏆 OVERALL RESULTS:")
        print(f"   ✅ Total Passed: {total_passed}")
        print(f"   ❌ Total Failed: {total_failed}")
        print(f"   ⏱️  Total Duration: {total_duration:.2f}s")
        
        if total_failed == 0:
            print("   🎉 ALL TESTS PASSED!")
        else:
            print(f"   ⚠️  {total_failed} tests failed")
        
        # Save detailed results
        with open("api_test_results.json", "w") as f:
            json.dump(self.results, f, indent=2)
        
        print(f"\n📄 Detailed results saved to: api_test_results.json")
        
        return self.results

async def main():
    """Main function to run the API tests"""
    tester = APITester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
