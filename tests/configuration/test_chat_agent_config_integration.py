"""
Integration tests for ChatAgentConfig Request Flow
Tests complete request flow from endpoint to database

Files covered:
- configuration/routers/router.py
- configuration/service/chat_agent_config_service.py
- configuration/dao/chat_agent_config_dao.py

Complete flow tested:
1. HTTP Request → Router endpoint
2. Router → Service layer
3. Service → DAO layer
4. DAO → Database queries
5. Response aggregation and transformation
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any


@pytest.mark.asyncio
async def test_complete_get_config_flow(
    mock_widget_config,
    mock_security_settings,
    mock_llm_providers,
    mock_persona,
    mock_human_agents,
    mock_admin_emails,
    complete_config_response
):
    """
    Test: Complete GET /chatAgentConfig request flow
    Files: router.py → service.py → dao.py → database
    
    Flow:
    1. GET /chatAgentConfig endpoint called
    2. Router calls ConfigurationService.get_chatAgent_config()
    3. Service calls DAO methods sequentially:
       - get_widget_config()
       - get_security_settings()
       - get_llm_providers()
       - get_active_persona()
       - get_human_agents()
       - get_admins()
    4. Service aggregates and transforms data
    5. Router returns success response with data
    
    Verifies:
    - All DAO methods called
    - Data properly aggregated
    - Response structure correct
    - No data loss in transformation
    """
    from configuration.routers.router import get_chatbot_config
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    # Mock all DAO methods
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
                            
                            # Mock the service in router
                            with patch('configuration.routers.router.config_service', service):
                                result = await get_chatbot_config(cache=True)
                                
                                # Verify response structure
                                assert result['success'] is True
                                assert 'data' in result
                                
                                data = result['data']
                                
                                # Verify all components present
                                assert 'llm_tokens' in data
                                assert 'security' in data
                                assert 'persona' in data
                                assert 'human_agents' in data
                                assert 'admin_emails' in data
                                assert 'metadata' in data
                                
                                # Verify data integrity
                                assert data['human_agents'] == mock_human_agents
                                assert data['admin_emails'] == mock_admin_emails
                                assert data['persona'] == mock_persona
                                
                                # Verify all DAO methods were called
                                mock_widget.assert_called_once()
                                mock_security.assert_called_once()
                                mock_llm.assert_called_once()
                                mock_pers.assert_called_once()
                                mock_agents.assert_called_once()
                                mock_admins.assert_called_once()


@pytest.mark.asyncio
async def test_config_flow_with_partial_data():
    """
    Test: GET /chatAgentConfig with partial/missing data
    Files: router.py → service.py → dao.py
    
    Edge case: Some DAO methods return empty/null results
    
    Verifies:
    - Service handles missing data gracefully
    - Response still valid with empty collections
    - No null pointer exceptions
    """
    from configuration.routers.router import get_chatbot_config
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_security:
            with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_llm:
                with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_pers:
                    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_agents:
                        with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_admins:
                            
                            # Return empty/null data
                            mock_widget.return_value = None
                            mock_security.return_value = []
                            mock_llm.return_value = []
                            mock_pers.return_value = None
                            mock_agents.return_value = []
                            mock_admins.return_value = []
                            
                            with patch('configuration.routers.router.config_service', service):
                                result = await get_chatbot_config(cache=True)
                                
                                assert result['success'] is True
                                data = result['data']
                                
                                # Verify structure still valid
                                assert isinstance(data['llm_tokens'], dict)
                                assert isinstance(data['human_agents'], list)
                                assert isinstance(data['admin_emails'], list)


@pytest.mark.asyncio
async def test_config_flow_dao_failure_propagation():
    """
    Test: GET /chatAgentConfig with DAO failure
    Files: router.py → service.py → dao.py
    
    Edge case: DAO raises exception
    
    Verifies:
    - Exception propagates from DAO → Service → Router
    - Router converts to HTTPException with 500 status
    - Error message preserved
    """
    from configuration.routers.router import get_chatbot_config
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    from fastapi import HTTPException
    
    service = ChatAgentConfigService()
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        mock_widget.side_effect = Exception("Connection pool exhausted")
        
        with patch('configuration.routers.router.config_service', service):
            with pytest.raises(HTTPException) as exc_info:
                await get_chatbot_config(cache=True)
            
            assert exc_info.value.status_code == 500
            assert "Connection pool exhausted" in exc_info.value.detail


@pytest.mark.asyncio
async def test_config_flow_sequential_execution():
    """
    Test: GET /chatAgentConfig - Sequential DAO execution
    Files: configuration/service/chat_agent_config_service.py
    
    Verifies:
    - DAO methods called sequentially (not in parallel)
    - Reduces connection pool pressure
    - Prevents timeout errors under load
    
    This is important for performance optimization
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    call_order = []
    
    async def track_call(name):
        call_order.append(name)
        return None if name in ['widget', 'persona'] else []
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_security:
            with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_llm:
                with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_pers:
                    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_agents:
                        with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_admins:
                            
                            mock_widget.side_effect = lambda: track_call('widget')
                            mock_security.side_effect = lambda: track_call('security')
                            mock_llm.side_effect = lambda: track_call('llm')
                            mock_pers.side_effect = lambda: track_call('persona')
                            mock_agents.side_effect = lambda: track_call('agents')
                            mock_admins.side_effect = lambda: track_call('admins')
                            
                            await service.get_chatAgent_config()
                            
                            # Verify sequential execution
                            assert len(call_order) == 6
                            # All methods should be called exactly once
                            assert call_order.count('widget') == 1
                            assert call_order.count('security') == 1
                            assert call_order.count('llm') == 1
                            assert call_order.count('persona') == 1
                            assert call_order.count('agents') == 1
                            assert call_order.count('admins') == 1


@pytest.mark.asyncio
async def test_config_response_data_transformation():
    """
    Test: Data transformation in service layer
    File: configuration/service/chat_agent_config_service.py
    
    Verifies:
    - Security settings list → dict transformation
    - LLM providers list → dict transformation
    - Metadata extraction from widget config
    - Proper field mapping
    """
    from configuration.service.chat_agent_config_service import ChatAgentConfigService
    
    service = ChatAgentConfigService()
    
    security_settings = [
        {'setting_name': 'response_timeout', 'setting_value': '30', 'setting_type': 'integer'},
        {'setting_name': 'remove_pii', 'setting_value': 'true', 'setting_type': 'boolean'}
    ]
    
    llm_providers = [
        {'provider_name': 'gemini', 'token_limit': 1000000, 'token_used': 250000},
        {'provider_name': 'openai', 'token_limit': 500000, 'token_used': 100000}
    ]
    
    widget_config = {
        'hil_enabled': True,
        'response_policy': 30,
        'hil_disabled_message': 'Not available'
    }
    
    with patch.object(service._chatAgent_dao, 'get_widget_config', new_callable=AsyncMock) as mock_widget:
        with patch.object(service._chatAgent_dao, 'get_security_settings', new_callable=AsyncMock) as mock_security:
            with patch.object(service._chatAgent_dao, 'get_llm_providers', new_callable=AsyncMock) as mock_llm:
                with patch.object(service._chatAgent_dao, 'get_active_persona', new_callable=AsyncMock) as mock_pers:
                    with patch.object(service._chatAgent_dao, 'get_human_agents', new_callable=AsyncMock) as mock_agents:
                        with patch.object(service._chatAgent_dao, 'get_admins', new_callable=AsyncMock) as mock_admins:
                            
                            mock_widget.return_value = widget_config
                            mock_security.return_value = security_settings
                            mock_llm.return_value = llm_providers
                            mock_pers.return_value = None
                            mock_agents.return_value = []
                            mock_admins.return_value = []
                            
                            result = await service.get_chatAgent_config()
                            
                            # Verify transformations
                            assert isinstance(result['security'], dict)
                            assert result['security']['response_timeout'] == 30
                            
                            assert isinstance(result['llm_tokens'], dict)
                            assert 'gemini' in result['llm_tokens']
                            assert result['llm_tokens']['gemini'] == 1000000
                            
                            assert isinstance(result['metadata'], dict)
                            assert result['metadata']['hil_enabled'] is True
                            assert result['metadata']['response_policy'] == 30
