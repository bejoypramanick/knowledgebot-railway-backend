"""
Unit tests for ChatAgentConfig Router Endpoints
Tests HTTP endpoint layer for chat agent configuration

Files covered:
- knowledgebot-railway-backend/configuration/routers/router.py

Functions tested:
- get_chatbot_config() - GET /chatAgentConfig
- save_chatbot_config() - POST /chatAgentConfig
- get_security_settings() - GET /data/security-settings
- get_llm_providers() - GET /data/llm-providers
- get_active_persona() - GET /data/active-persona
- get_human_agents() - GET /data/human-agents
- get_admin_emails() - GET /data/admin-emails
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from typing import Dict, Any


@pytest.mark.asyncio
async def test_get_chatbot_config_success(complete_config_response):
    """
    Test: get_chatbot_config() - Success case
    File: configuration/routers/router.py
    Function: get_chatbot_config()
    Endpoint: GET /chatAgentConfig
    
    Verifies endpoint returns complete configuration with success flag
    """
    from configuration.routers.router import get_chatbot_config
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_chatAgent_config = AsyncMock(return_value=complete_config_response)
        
        result = await get_chatbot_config(cache=True)
        
        assert result['success'] is True
        assert 'data' in result
        assert result['data'] == complete_config_response
        mock_service.get_chatAgent_config.assert_called_once()


@pytest.mark.asyncio
async def test_get_chatbot_config_with_cache_false(complete_config_response):
    """
    Test: get_chatbot_config() - Cache disabled
    File: configuration/routers/router.py
    Function: get_chatbot_config()
    Endpoint: GET /chatAgentConfig?cache=false
    
    Edge case: Cache parameter set to false
    Verifies endpoint still returns data
    """
    from configuration.routers.router import get_chatbot_config
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_chatAgent_config = AsyncMock(return_value=complete_config_response)
        
        result = await get_chatbot_config(cache=False)
        
        assert result['success'] is True
        assert 'data' in result


@pytest.mark.asyncio
async def test_get_chatbot_config_service_error():
    """
    Test: get_chatbot_config() - Service error
    File: configuration/routers/router.py
    Function: get_chatbot_config()
    Endpoint: GET /chatAgentConfig
    
    Edge case: Service raises exception
    Verifies HTTPException is raised with 500 status
    """
    from configuration.routers.router import get_chatbot_config
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_chatAgent_config = AsyncMock(
            side_effect=Exception("Database connection failed")
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_chatbot_config(cache=True)
        
        assert exc_info.value.status_code == 500
        assert "Database connection failed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_save_chatbot_config_success():
    """
    Test: save_chatbot_config() - Success case
    File: configuration/routers/router.py
    Function: save_chatbot_config()
    Endpoint: POST /chatAgentConfig
    
    Verifies configuration is saved and success response returned
    """
    from configuration.routers.router import save_chatbot_config
    from configuration.models import ChatbotConfigRequest
    
    config_request = ChatbotConfigRequest(
        admin_emails=['admin@example.com'],
        human_agents=['agent@example.com'],
        security={'response_timeout': 30},
        persona={'system_prompt': 'Test prompt', 'selected_persona': 'test'}
    )
    
    mock_request = MagicMock()
    mock_request.headers = {}
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.save_chatbot_config = AsyncMock(return_value=True)
        
        result = await save_chatbot_config(config_request, mock_request)
        
        assert result['success'] is True
        assert 'message' in result
        mock_service.save_chatbot_config.assert_called_once()


@pytest.mark.asyncio
async def test_save_chatbot_config_service_error():
    """
    Test: save_chatbot_config() - Service error
    File: configuration/routers/router.py
    Function: save_chatbot_config()
    Endpoint: POST /chatAgentConfig
    
    Edge case: Service raises exception during save
    Verifies HTTPException is raised with 500 status
    """
    from configuration.routers.router import save_chatbot_config
    from configuration.models import ChatbotConfigRequest
    
    config_request = ChatbotConfigRequest(
        admin_emails=['admin@example.com'],
        human_agents=['agent@example.com']
    )
    
    mock_request = MagicMock()
    mock_request.headers = {}
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.save_chatbot_config = AsyncMock(
            side_effect=Exception("Failed to save config")
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await save_chatbot_config(config_request, mock_request)
        
        assert exc_info.value.status_code == 500
        assert "Failed to save config" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_security_settings_success(mock_security_settings):
    """
    Test: get_security_settings() - Success case
    File: configuration/routers/router.py
    Function: get_security_settings()
    Endpoint: GET /data/security-settings
    
    Verifies security settings endpoint returns data
    """
    from configuration.routers.router import get_security_settings
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_security_settings = AsyncMock(
            return_value={'response_timeout': 30}
        )
        
        result = await get_security_settings()
        
        assert 'response_timeout' in result


@pytest.mark.asyncio
async def test_get_llm_providers_success(mock_llm_providers):
    """
    Test: get_llm_providers() - Success case
    File: configuration/routers/router.py
    Function: get_llm_providers()
    Endpoint: GET /data/llm-providers
    
    Verifies LLM providers endpoint returns data
    """
    from configuration.routers.router import get_llm_providers
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_llm_providers = AsyncMock(
            return_value={'gemini': 1000000}
        )
        
        result = await get_llm_providers()
        
        assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_active_persona_success(mock_persona):
    """
    Test: get_active_persona() - Success case
    File: configuration/routers/router.py
    Function: get_active_persona()
    Endpoint: GET /data/active-persona
    
    Verifies active persona endpoint returns persona data
    """
    from configuration.routers.router import get_active_persona
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_active_persona = AsyncMock(return_value=mock_persona)
        
        result = await get_active_persona()
        
        assert result['persona_name'] == 'helpful_assistant'


@pytest.mark.asyncio
async def test_get_human_agents_success(mock_human_agents):
    """
    Test: get_human_agents() - Success case
    File: configuration/routers/router.py
    Function: get_human_agents()
    Endpoint: GET /data/human-agents
    
    Verifies human agents endpoint returns list
    """
    from configuration.routers.router import get_human_agents
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_human_agents = AsyncMock(return_value=mock_human_agents)
        
        result = await get_human_agents()
        
        assert len(result) == 3
        assert 'agent1@example.com' in result


@pytest.mark.asyncio
async def test_get_admin_emails_success(mock_admin_emails):
    """
    Test: get_admin_emails() - Success case
    File: configuration/routers/router.py
    Function: get_admin_emails()
    Endpoint: GET /data/admin-emails
    
    Verifies admin emails endpoint returns list
    """
    from configuration.routers.router import get_admin_emails
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_admin_emails = AsyncMock(return_value=mock_admin_emails)
        
        result = await get_admin_emails()
        
        assert len(result) == 2
        assert 'admin1@example.com' in result


@pytest.mark.asyncio
async def test_get_admin_emails_empty():
    """
    Test: get_admin_emails() - No admins
    File: configuration/routers/router.py
    Function: get_admin_emails()
    Endpoint: GET /data/admin-emails
    
    Edge case: No admins in system
    """
    from configuration.routers.router import get_admin_emails
    
    with patch('configuration.routers.router.config_service') as mock_service:
        mock_service.get_admin_emails = AsyncMock(return_value=[])
        
        result = await get_admin_emails()
        
        assert result == []
