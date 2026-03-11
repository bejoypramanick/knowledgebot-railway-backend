"""
Unit tests for configuration data endpoints:
- GET /api/v1/gateway/configuration/data/security-settings
- GET /api/v1/gateway/configuration/data/llm-providers
- GET /api/v1/gateway/configuration/data/active-persona
- GET /api/v1/gateway/configuration/data/human-agents
- GET /api/v1/gateway/configuration/data/admin-emails

Request Flow:
1. GET /api/v1/gateway/configuration/data/{endpoint}
2. Call ConfigurationService method
3. ConfigurationService calls ChatAgentConfigDAO method
4. DAO queries database
5. Return formatted response

Files Involved:
- configuration/routers/router.py::get_security_settings
- configuration/routers/router.py::get_llm_providers
- configuration/routers/router.py::get_active_persona
- configuration/routers/router.py::get_human_agents
- configuration/routers/router.py::get_admin_emails
- configuration/service/configuration_service.py::ConfigurationService
- configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TestSecuritySettingsEndpoint:
    """Test suite for GET /data/security-settings endpoint"""

    @pytest.mark.asyncio
    async def test_get_security_settings_success(
        self,
        mock_configuration_service,
        mock_security_settings
    ):
        """
        Test successful security settings retrieval.
        
        Covers: configuration/routers/router.py::get_security_settings
        Covers: configuration/service/configuration_service.py::ConfigurationService.get_security_settings
        Covers: configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO.get_security_settings
        """
        logger.info("🧪 Testing successful security settings retrieval")
        
        # Setup
        mock_configuration_service.get_security_settings.return_value = mock_security_settings
        
        # Execute
        logger.info("📤 Fetching security settings")
        from configuration.routers.router import get_security_settings
        
        result = await get_security_settings()
        
        # Verify
        logger.info("✅ Verifying security settings response")
        assert result is not None
        assert "setting_key" in result or "settings" in result
        
        logger.info("✅ Security settings test passed")

    @pytest.mark.asyncio
    async def test_get_security_settings_empty(
        self,
        mock_configuration_service
    ):
        """
        Test security settings retrieval when no settings exist.
        
        Covers: configuration/routers/router.py::get_security_settings
        
        Edge Case: No security settings in database
        """
        logger.info("🧪 Testing security settings retrieval with empty results")
        
        # Setup
        mock_configuration_service.get_security_settings.return_value = {}
        
        # Execute
        logger.info("📤 Fetching empty security settings")
        from configuration.routers.router import get_security_settings
        
        result = await get_security_settings()
        
        # Verify
        logger.info("✅ Verifying empty settings handling")
        assert result is not None
        
        logger.info("✅ Empty settings test passed")

    @pytest.mark.asyncio
    async def test_get_security_settings_database_error(
        self,
        mock_configuration_service
    ):
        """
        Test security settings retrieval with database error.
        
        Covers: configuration/routers/router.py::get_security_settings
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing security settings with database error")
        
        # Setup
        mock_configuration_service.get_security_settings.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching settings with database error")
        from configuration.routers.router import get_security_settings
        
        with pytest.raises(HTTPException) as exc_info:
            await get_security_settings()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")

    @pytest.mark.asyncio
    async def test_get_security_settings_timeout(
        self,
        mock_configuration_service
    ):
        """
        Test security settings retrieval with timeout.
        
        Covers: configuration/routers/router.py::get_security_settings
        
        Edge Case: Database query timeout
        """
        logger.info("🧪 Testing security settings with timeout")
        
        # Setup
        mock_configuration_service.get_security_settings.side_effect = TimeoutError("Query timeout")
        
        # Execute
        logger.info("📤 Fetching settings with timeout")
        from configuration.routers.router import get_security_settings
        
        with pytest.raises(HTTPException) as exc_info:
            await get_security_settings()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Timeout test passed")


class TestLLMProvidersEndpoint:
    """Test suite for GET /data/llm-providers endpoint"""

    @pytest.mark.asyncio
    async def test_get_llm_providers_success(
        self,
        mock_configuration_service,
        mock_llm_providers
    ):
        """
        Test successful LLM providers retrieval.
        
        Covers: configuration/routers/router.py::get_llm_providers
        Covers: configuration/service/configuration_service.py::ConfigurationService.get_llm_providers
        Covers: configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO.get_llm_providers
        """
        logger.info("🧪 Testing successful LLM providers retrieval")
        
        # Setup
        mock_configuration_service.get_llm_providers.return_value = mock_llm_providers
        
        # Execute
        logger.info("📤 Fetching LLM providers")
        from configuration.routers.router import get_llm_providers
        
        result = await get_llm_providers()
        
        # Verify
        logger.info("✅ Verifying LLM providers response")
        assert result is not None
        assert "providers" in result or len(result) > 0
        
        logger.info("✅ LLM providers test passed")

    @pytest.mark.asyncio
    async def test_get_llm_providers_empty(
        self,
        mock_configuration_service
    ):
        """
        Test LLM providers retrieval when no providers exist.
        
        Covers: configuration/routers/router.py::get_llm_providers
        
        Edge Case: No LLM providers configured
        """
        logger.info("🧪 Testing LLM providers retrieval with empty results")
        
        # Setup
        mock_configuration_service.get_llm_providers.return_value = {"providers": []}
        
        # Execute
        logger.info("📤 Fetching empty LLM providers")
        from configuration.routers.router import get_llm_providers
        
        result = await get_llm_providers()
        
        # Verify
        logger.info("✅ Verifying empty providers handling")
        assert result is not None
        
        logger.info("✅ Empty providers test passed")

    @pytest.mark.asyncio
    async def test_get_llm_providers_token_limits(
        self,
        mock_configuration_service
    ):
        """
        Test LLM providers with token limit information.
        
        Covers: configuration/routers/router.py::get_llm_providers
        
        Edge Case: Token usage tracking
        """
        logger.info("🧪 Testing LLM providers with token limits")
        
        # Setup
        providers_with_tokens = {
            "providers": [
                {
                    "provider_name": "OpenAI",
                    "token_limit": 8000,
                    "tokens_used": 7500,
                    "tokens_remaining": 500
                }
            ]
        }
        mock_configuration_service.get_llm_providers.return_value = providers_with_tokens
        
        # Execute
        logger.info("📤 Fetching providers with token info")
        from configuration.routers.router import get_llm_providers
        
        result = await get_llm_providers()
        
        # Verify
        logger.info("✅ Verifying token information")
        assert result["providers"][0]["tokens_remaining"] == 500
        
        logger.info("✅ Token limits test passed")

    @pytest.mark.asyncio
    async def test_get_llm_providers_database_error(
        self,
        mock_configuration_service
    ):
        """
        Test LLM providers retrieval with database error.
        
        Covers: configuration/routers/router.py::get_llm_providers
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing LLM providers with database error")
        
        # Setup
        mock_configuration_service.get_llm_providers.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching providers with database error")
        from configuration.routers.router import get_llm_providers
        
        with pytest.raises(HTTPException) as exc_info:
            await get_llm_providers()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")


class TestActivePersonaEndpoint:
    """Test suite for GET /data/active-persona endpoint"""

    @pytest.mark.asyncio
    async def test_get_active_persona_success(
        self,
        mock_configuration_service,
        mock_active_persona
    ):
        """
        Test successful active persona retrieval.
        
        Covers: configuration/routers/router.py::get_active_persona
        Covers: configuration/service/configuration_service.py::ConfigurationService.get_active_persona
        Covers: configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO.get_active_persona
        """
        logger.info("🧪 Testing successful active persona retrieval")
        
        # Setup
        mock_configuration_service.get_active_persona.return_value = mock_active_persona
        
        # Execute
        logger.info("📤 Fetching active persona")
        from configuration.routers.router import get_active_persona
        
        result = await get_active_persona()
        
        # Verify
        logger.info("✅ Verifying active persona response")
        assert result is not None
        assert "persona_name" in result or "system_prompt" in result
        
        logger.info("✅ Active persona test passed")

    @pytest.mark.asyncio
    async def test_get_active_persona_none(
        self,
        mock_configuration_service
    ):
        """
        Test active persona retrieval when no persona is active.
        
        Covers: configuration/routers/router.py::get_active_persona
        
        Edge Case: No active persona configured
        """
        logger.info("🧪 Testing active persona retrieval with no active persona")
        
        # Setup
        mock_configuration_service.get_active_persona.return_value = None
        
        # Execute
        logger.info("📤 Fetching with no active persona")
        from configuration.routers.router import get_active_persona
        
        result = await get_active_persona()
        
        # Verify
        logger.info("✅ Verifying no active persona handling")
        assert result is None or result == {}
        
        logger.info("✅ No active persona test passed")

    @pytest.mark.asyncio
    async def test_get_active_persona_with_system_prompt(
        self,
        mock_configuration_service
    ):
        """
        Test active persona with system prompt.
        
        Covers: configuration/routers/router.py::get_active_persona
        
        Edge Case: Persona with detailed system prompt
        """
        logger.info("🧪 Testing active persona with system prompt")
        
        # Setup
        persona_with_prompt = {
            "persona_id": 1,
            "persona_name": "Helpful Assistant",
            "system_prompt": "You are a helpful assistant. Your role is to...",
            "description": "A friendly chatbot",
            "is_active": True
        }
        mock_configuration_service.get_active_persona.return_value = persona_with_prompt
        
        # Execute
        logger.info("📤 Fetching persona with system prompt")
        from configuration.routers.router import get_active_persona
        
        result = await get_active_persona()
        
        # Verify
        logger.info("✅ Verifying system prompt")
        assert "system_prompt" in result
        assert len(result["system_prompt"]) > 0
        
        logger.info("✅ System prompt test passed")

    @pytest.mark.asyncio
    async def test_get_active_persona_database_error(
        self,
        mock_configuration_service
    ):
        """
        Test active persona retrieval with database error.
        
        Covers: configuration/routers/router.py::get_active_persona
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing active persona with database error")
        
        # Setup
        mock_configuration_service.get_active_persona.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching persona with database error")
        from configuration.routers.router import get_active_persona
        
        with pytest.raises(HTTPException) as exc_info:
            await get_active_persona()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")


class TestHumanAgentsEndpoint:
    """Test suite for GET /data/human-agents endpoint"""

    @pytest.mark.asyncio
    async def test_get_human_agents_success(
        self,
        mock_configuration_service,
        mock_human_agents_list
    ):
        """
        Test successful human agents retrieval.
        
        Covers: configuration/routers/router.py::get_human_agents
        Covers: configuration/service/configuration_service.py::ConfigurationService.get_human_agents
        Covers: configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO.get_human_agents
        """
        logger.info("🧪 Testing successful human agents retrieval")
        
        # Setup
        mock_configuration_service.get_human_agents.return_value = mock_human_agents_list
        
        # Execute
        logger.info("📤 Fetching human agents")
        from configuration.routers.router import get_human_agents
        
        result = await get_human_agents()
        
        # Verify
        logger.info("✅ Verifying human agents response")
        assert result is not None
        assert "agents" in result or len(result) > 0
        
        logger.info("✅ Human agents test passed")

    @pytest.mark.asyncio
    async def test_get_human_agents_empty(
        self,
        mock_configuration_service
    ):
        """
        Test human agents retrieval when no agents exist.
        
        Covers: configuration/routers/router.py::get_human_agents
        
        Edge Case: No human agents configured
        """
        logger.info("🧪 Testing human agents retrieval with empty results")
        
        # Setup
        mock_configuration_service.get_human_agents.return_value = {"agents": []}
        
        # Execute
        logger.info("📤 Fetching empty human agents")
        from configuration.routers.router import get_human_agents
        
        result = await get_human_agents()
        
        # Verify
        logger.info("✅ Verifying empty agents handling")
        assert result is not None
        
        logger.info("✅ Empty agents test passed")

    @pytest.mark.asyncio
    async def test_get_human_agents_with_status(
        self,
        mock_configuration_service
    ):
        """
        Test human agents with availability status.
        
        Covers: configuration/routers/router.py::get_human_agents
        
        Edge Case: Agent status tracking
        """
        logger.info("🧪 Testing human agents with status")
        
        # Setup
        agents_with_status = {
            "agents": [
                {
                    "agent_id": 1,
                    "email": "agent@example.com",
                    "name": "Agent",
                    "status": "available",
                    "current_sessions": 2
                }
            ]
        }
        mock_configuration_service.get_human_agents.return_value = agents_with_status
        
        # Execute
        logger.info("📤 Fetching agents with status")
        from configuration.routers.router import get_human_agents
        
        result = await get_human_agents()
        
        # Verify
        logger.info("✅ Verifying agent status")
        assert result["agents"][0]["status"] in ["available", "busy", "offline"]
        
        logger.info("✅ Agent status test passed")

    @pytest.mark.asyncio
    async def test_get_human_agents_database_error(
        self,
        mock_configuration_service
    ):
        """
        Test human agents retrieval with database error.
        
        Covers: configuration/routers/router.py::get_human_agents
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing human agents with database error")
        
        # Setup
        mock_configuration_service.get_human_agents.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching agents with database error")
        from configuration.routers.router import get_human_agents
        
        with pytest.raises(HTTPException) as exc_info:
            await get_human_agents()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")


class TestAdminEmailsEndpoint:
    """Test suite for GET /data/admin-emails endpoint"""

    @pytest.mark.asyncio
    async def test_get_admin_emails_success(
        self,
        mock_configuration_service,
        mock_admin_emails_list
    ):
        """
        Test successful admin emails retrieval.
        
        Covers: configuration/routers/router.py::get_admin_emails
        Covers: configuration/service/configuration_service.py::ConfigurationService.get_admin_emails
        Covers: configuration/dao/chat_agent_config_dao.py::ChatAgentConfigDAO.get_admins
        """
        logger.info("🧪 Testing successful admin emails retrieval")
        
        # Setup
        mock_configuration_service.get_admin_emails.return_value = mock_admin_emails_list
        
        # Execute
        logger.info("📤 Fetching admin emails")
        from configuration.routers.router import get_admin_emails
        
        result = await get_admin_emails()
        
        # Verify
        logger.info("✅ Verifying admin emails response")
        assert result is not None
        assert "admins" in result or len(result) > 0
        
        logger.info("✅ Admin emails test passed")

    @pytest.mark.asyncio
    async def test_get_admin_emails_empty(
        self,
        mock_configuration_service
    ):
        """
        Test admin emails retrieval when no admins exist.
        
        Covers: configuration/routers/router.py::get_admin_emails
        
        Edge Case: No admins configured
        """
        logger.info("🧪 Testing admin emails retrieval with empty results")
        
        # Setup
        mock_configuration_service.get_admin_emails.return_value = {"admins": []}
        
        # Execute
        logger.info("📤 Fetching empty admin emails")
        from configuration.routers.router import get_admin_emails
        
        result = await get_admin_emails()
        
        # Verify
        logger.info("✅ Verifying empty admins handling")
        assert result is not None
        
        logger.info("✅ Empty admins test passed")

    @pytest.mark.asyncio
    async def test_get_admin_emails_database_error(
        self,
        mock_configuration_service
    ):
        """
        Test admin emails retrieval with database error.
        
        Covers: configuration/routers/router.py::get_admin_emails
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing admin emails with database error")
        
        # Setup
        mock_configuration_service.get_admin_emails.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching admin emails with database error")
        from configuration.routers.router import get_admin_emails
        
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_emails()
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")

    @pytest.mark.asyncio
    async def test_get_admin_emails_multiple_admins(
        self,
        mock_configuration_service
    ):
        """
        Test admin emails with multiple admins.
        
        Covers: configuration/routers/router.py::get_admin_emails
        
        Edge Case: Multiple admin accounts
        """
        logger.info("🧪 Testing admin emails with multiple admins")
        
        # Setup
        multiple_admins = {
            "admins": [
                {"admin_id": 1, "email": "admin1@example.com", "name": "Admin 1"},
                {"admin_id": 2, "email": "admin2@example.com", "name": "Admin 2"},
                {"admin_id": 3, "email": "admin3@example.com", "name": "Admin 3"}
            ]
        }
        mock_configuration_service.get_admin_emails.return_value = multiple_admins
        
        # Execute
        logger.info("📤 Fetching multiple admin emails")
        from configuration.routers.router import get_admin_emails
        
        result = await get_admin_emails()
        
        # Verify
        logger.info("✅ Verifying multiple admins")
        assert len(result["admins"]) == 3
        
        logger.info("✅ Multiple admins test passed")
