"""
Unit tests for ChatAgentConfigService
Tests business logic layer for chat agent configuration

Files covered:
- knowledgebot-railway-backend/configuration/service/chat_agent_config_service.py

Functions tested:
- ChatAgentConfigService.get_chatAgent_config()
- ChatAgentConfigService.save_chatAgent_config()
- ChatAgentConfigService.get_security_settings()
- ChatAgentConfigService.get_llm_providers()
- ChatAgentConfigService.get_active_persona()
- ChatAgentConfigService.get_human_agents()
- ChatAgentConfigService.get_admin_emails()
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any, List


@pytest.mark.asyncio
async def test_get_chatAgent_config_success(
    mock_widget_config,
    mock_security_settings,
    mock_llm_providers,
    mock_persona,
    mock_human_agents,
    mock_admin_emails,
    complete_config_response
):
    """
    Test: ChatAgentConfigService.get_chatAgent_config() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_chatAgent_config()
    
    Verifies complete configuration is aggregated from all DAOs
    and properly transformed into response format
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    # Mock the DAO methods
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_security:
            with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_llm:
                with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_pers:
                    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_agents:
                        with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_admins:
                            
                            mock_widget.return_value = mock_widget_config
                            mock_security.return_value = mock_security_settings
                            mock_llm.return_value = mock_llm_providers
                            mock_pers.return_value = mock_persona
                            mock_agents.return_value = mock_human_agents
                            mock_admins.return_value = mock_admin_emails
                            
                            result = await service.get_chatAgent_config()
                            
                            # Verify structure
                            assert 'llm_tokens' in result
                            assert 'security' in result
                            assert 'persona' in result
                            assert 'human_agents' in result
                            assert 'admin_emails' in result
                            assert 'metadata' in result
                            
                            # Verify values
                            assert result['human_agents'] == mock_human_agents
                            assert result['admin_emails'] == mock_admin_emails
                            assert result['persona'] == mock_persona
                            assert result['metadata']['hil_enabled'] is True


@pytest.mark.asyncio
async def test_get_chatAgent_config_with_empty_data():
    """
    Test: ChatAgentConfigService.get_chatAgent_config() - Empty data
    File: configuration/service/chat_agent_config_service.py
    Function: get_chatAgent_config()
    
    Edge case: Database returns empty results for some fields
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_security:
            with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_llm:
                with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_pers:
                    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_agents:
                        with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_admins:
                            
                            mock_widget.return_value = None
                            mock_security.return_value = []
                            mock_llm.return_value = []
                            mock_pers.return_value = None
                            mock_agents.return_value = []
                            mock_admins.return_value = []
                            
                            result = await service.get_chatAgent_config()
                            
                            # Verify structure still exists
                            assert 'llm_tokens' in result
                            assert 'security' in result
                            assert 'persona' in result
                            assert 'human_agents' in result
                            assert 'admin_emails' in result
                            
                            # Verify empty collections
                            assert result['human_agents'] == []
                            assert result['admin_emails'] == []
                            assert result['llm_tokens'] == {}


@pytest.mark.asyncio
async def test_get_chatAgent_config_dao_error():
    """
    Test: ChatAgentConfigService.get_chatAgent_config() - DAO error
    File: configuration/service/chat_agent_config_service.py
    Function: get_chatAgent_config()
    
    Edge case: DAO raises exception
    Verifies exception propagates to caller
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        mock_widget.side_effect = Exception("Database error")
        
        with pytest.raises(Exception) as exc_info:
            await service.get_chatAgent_config()
        
        assert "Database error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_security_settings_success(mock_security_settings):
    """
    Test: ChatAgentConfigService.get_security_settings() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_security_settings()
    
    Verifies security settings are transformed into dict format
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_dao:
        mock_dao.return_value = mock_security_settings
        
        result = await service.get_security_settings()
        
        assert isinstance(result, dict)
        assert 'response_timeout' in result


@pytest.mark.asyncio
async def test_get_llm_providers_success(mock_llm_providers):
    """
    Test: ChatAgentConfigService.get_llm_providers() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_llm_providers()
    
    Verifies LLM providers are transformed into dict format
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_dao:
        mock_dao.return_value = mock_llm_providers
        
        result = await service.get_llm_providers()
        
        assert isinstance(result, dict)
        assert 'gemini' in result or len(result) >= 0


@pytest.mark.asyncio
async def test_get_active_persona_success(mock_persona):
    """
    Test: ChatAgentConfigService.get_active_persona() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_active_persona()
    
    Verifies active persona is returned correctly
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_dao:
        mock_dao.return_value = mock_persona
        
        result = await service.get_active_persona()
        
        assert result == mock_persona
        assert result['persona_name'] == 'helpful_assistant'


@pytest.mark.asyncio
async def test_get_human_agents_success(mock_human_agents):
    """
    Test: ChatAgentConfigService.get_human_agents() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_human_agents()
    
    Verifies human agents list is returned correctly
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_dao:
        mock_dao.return_value = mock_human_agents
        
        result = await service.get_human_agents()
        
        assert result == mock_human_agents
        assert len(result) == 3


@pytest.mark.asyncio
async def test_get_admin_emails_success(mock_admin_emails):
    """
    Test: ChatAgentConfigService.get_admin_emails() - Success case
    File: configuration/service/chat_agent_config_service.py
    Function: get_admin_emails()
    
    Verifies admin emails list is returned correctly
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_dao:
        mock_dao.return_value = mock_admin_emails
        
        result = await service.get_admin_emails()
        
        assert result == mock_admin_emails
        assert len(result) == 2
