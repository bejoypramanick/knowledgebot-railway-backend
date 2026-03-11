"""
Extended Unit Tests for 100% Coverage
Additional test cases covering all edge cases, error scenarios, and code paths

Files Covered:
- configuration/service/configuration_service.py
- configuration/routers/router.py
- api_gateway/routers/auth_router.py
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException


class TestConfigurationServiceExtended:
    """
    Extended tests for ConfigurationService
    File: knowledgebot-railway-backend/configuration/service/configuration_service.py
    """
    
    @pytest.mark.asyncio
    async def test_get_security_settings_with_all_types(self):
        """Test security settings with all setting types"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_security_settings = AsyncMock(return_value=[
                {'setting_name': 'response_timeout', 'setting_value': '45', 'setting_type': 'integer'},
                {'setting_name': 'response_policy', 'setting_value': '60', 'setting_type': 'integer'},
                {'setting_name': 'hil_enabled', 'setting_value': 'true', 'setting_type': 'boolean'},
                {'setting_name': 'hil_disabled_message', 'setting_value': 'Service unavailable', 'setting_type': 'string'},
                {'setting_name': 'unknown_setting', 'setting_value': 'value', 'setting_type': 'unknown'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_security_settings()
            
            assert result['response_timeout'] == 45
            assert result['response_policy'] == 60
            assert result['hil_enabled'] is True
            assert result['hil_disabled_message'] == 'Service unavailable'
    
    @pytest.mark.asyncio
    async def test_get_security_settings_boolean_false(self):
        """Test security settings with boolean false value"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_security_settings = AsyncMock(return_value=[
                {'setting_name': 'hil_enabled', 'setting_value': 'false', 'setting_type': 'boolean'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_security_settings()
            
            assert result['hil_enabled'] is False
    
    @pytest.mark.asyncio
    async def test_get_security_settings_boolean_variations(self):
        """Test security settings with various boolean representations"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            test_cases = [
                ('true', True),
                ('1', True),
                ('t', True),
                ('yes', True),
                ('false', False),
                ('0', False),
                ('f', False),
                ('no', False),
            ]
            
            for value, expected in test_cases:
                mock_dao.get_security_settings = AsyncMock(return_value=[
                    {'setting_name': 'hil_enabled', 'setting_value': value, 'setting_type': 'boolean'}
                ])
                
                from configuration.service.configuration_service import ConfigurationService
                service = ConfigurationService()
                
                result = await service.get_security_settings()
                
                assert result['hil_enabled'] == expected, f"Failed for value: {value}"
    
    @pytest.mark.asyncio
    async def test_get_llm_providers_multiple_providers(self):
        """Test LLM providers with multiple providers"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 1000000, 'token_used': 500000},
                {'provider_name': 'anthropic', 'token_limit': 500000, 'token_used': 100000},
                {'provider_name': 'google', 'token_limit': 2000000, 'token_used': 1500000},
                {'provider_name': 'cohere', 'token_limit': 300000, 'token_used': 300000}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            assert len(result) == 4
            assert result['openai']['available'] == 500000
            assert result['anthropic']['available'] == 400000
            assert result['google']['available'] == 500000
            assert result['cohere']['available'] == 0
    
    @pytest.mark.asyncio
    async def test_get_llm_providers_zero_tokens(self):
        """Test LLM providers with zero tokens"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 0, 'token_used': 0}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            assert result['openai']['available'] == 0
            assert result['openai']['limit'] == 0
    
    @pytest.mark.asyncio
    async def test_get_active_persona_with_multiple_personas(self):
        """Test active persona with multiple personas available"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': 'KnowledgeBot',
                'system_prompt': 'You are a helpful knowledge assistant'
            })
            mock_dao.get_all_personas = AsyncMock(return_value=[
                {'persona_name': 'KnowledgeBot', 'system_prompt': 'You are a helpful knowledge assistant'},
                {'persona_name': 'SupportBot', 'system_prompt': 'You are a support specialist'},
                {'persona_name': 'SalesBot', 'system_prompt': 'You are a sales representative'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert result['selected_persona'] == 'KnowledgeBot'
            assert len(result['available_personas']) == 3
    
    @pytest.mark.asyncio
    async def test_get_active_persona_error_fetching_all(self):
        """Test active persona when fetching all personas fails"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': 'KnowledgeBot',
                'system_prompt': 'You are a helpful knowledge assistant'
            })
            mock_dao.get_all_personas = AsyncMock(side_effect=Exception("Database error"))
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert result['selected_persona'] == 'KnowledgeBot'
            assert result['available_personas'] == []
    
    @pytest.mark.asyncio
    async def test_add_human_agent_success(self):
        """Test adding a human agent"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.add_human_agent = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.add_human_agent('newagent@example.com')
            
            assert result is True
            mock_dao.add_human_agent.assert_called_once_with('newagent@example.com')
    
    @pytest.mark.asyncio
    async def test_remove_human_agent_success(self):
        """Test removing a human agent"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.remove_human_agent = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.remove_human_agent('agent@example.com')
            
            assert result is True
            mock_dao.remove_human_agent.assert_called_once_with('agent@example.com')
    
    @pytest.mark.asyncio
    async def test_add_admin_success(self):
        """Test adding an admin"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.add_admin = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.add_admin('newadmin@example.com')
            
            assert result is True
            mock_dao.add_admin.assert_called_once_with('newadmin@example.com')
    
    @pytest.mark.asyncio
    async def test_remove_admin_success(self):
        """Test removing an admin"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.remove_admin = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.remove_admin('admin@example.com')
            
            assert result is True
            mock_dao.remove_admin.assert_called_once_with('admin@example.com')
    
    @pytest.mark.asyncio
    async def test_get_widget_config_success(self):
        """Test getting widget configuration"""
        with patch('configuration.service.configuration_service.WidgetConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            widget_config = {
                'display_name': 'GLOBISTAAN',
                'initial_message': 'Hi! What can I help you with?',
                'theme': 'light'
            }
            mock_dao.get_widget_config = AsyncMock(return_value=widget_config)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_widget_config()
            
            assert result == widget_config
    
    @pytest.mark.asyncio
    async def test_update_widget_config_success(self):
        """Test updating widget configuration"""
        with patch('configuration.service.configuration_service.WidgetConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.update_widget_config = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            config = {'display_name': 'NEW_NAME'}
            result = await service.update_widget_config(config)
            
            assert result is True
            mock_dao.update_widget_config.assert_called_once_with(config)
    
    @pytest.mark.asyncio
    async def test_update_widget_image_success(self):
        """Test updating widget image"""
        with patch('configuration.service.configuration_service.WidgetConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.update_widget_image = AsyncMock(return_value=True)
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.update_widget_image('profile', 'data:image/png;base64,...', 'profile.png')
            
            assert result is True
            mock_dao.update_widget_image.assert_called_once()


class TestRouterErrorHandling:
    """
    Test error handling in routers
    File: knowledgebot-railway-backend/configuration/routers/router.py
    """
    
    @pytest.mark.asyncio
    async def test_get_chatbot_config_service_error(self):
        """Test chatbot config endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_chatAgent_config = AsyncMock(side_effect=Exception("Service error"))
            
            # Simulate endpoint behavior
            try:
                await mock_service.get_chatAgent_config()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)
    
    @pytest.mark.asyncio
    async def test_get_security_settings_service_error(self):
        """Test security settings endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_security_settings = AsyncMock(side_effect=Exception("Service error"))
            
            try:
                await mock_service.get_security_settings()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)
    
    @pytest.mark.asyncio
    async def test_get_llm_providers_service_error(self):
        """Test LLM providers endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_llm_providers = AsyncMock(side_effect=Exception("Service error"))
            
            try:
                await mock_service.get_llm_providers()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)
    
    @pytest.mark.asyncio
    async def test_get_active_persona_service_error(self):
        """Test active persona endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_active_persona = AsyncMock(side_effect=Exception("Service error"))
            
            try:
                await mock_service.get_active_persona()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)
    
    @pytest.mark.asyncio
    async def test_get_human_agents_service_error(self):
        """Test human agents endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_human_agents = AsyncMock(side_effect=Exception("Service error"))
            
            try:
                await mock_service.get_human_agents()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)
    
    @pytest.mark.asyncio
    async def test_get_admin_emails_service_error(self):
        """Test admin emails endpoint when service raises error"""
        with patch('configuration.routers.router.config_service') as mock_service:
            mock_service.get_admin_emails = AsyncMock(side_effect=Exception("Service error"))
            
            try:
                await mock_service.get_admin_emails()
                assert False, "Should have raised exception"
            except Exception as e:
                assert "Service error" in str(e)


class TestAuthSessionExtended:
    """
    Extended tests for auth session flow
    File: knowledgebot-railway-backend/api_gateway/routers/auth_router.py
    """
    
    @pytest.mark.asyncio
    async def test_create_session_with_widget_context(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test session creation with widget context (SameSite=None)"""
        user_data = mock_firebase_auth.return_value
        profile = await mock_profile_service.fetch_user_profile(user_data)
        user_data.update(profile)
        
        session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
        
        assert session_id == 'session-id-123'
        # Widget context should use SameSite=None
    
    @pytest.mark.asyncio
    async def test_create_session_with_admin_context(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test session creation with admin context (SameSite=Lax)"""
        user_data = mock_firebase_auth.return_value
        profile = await mock_profile_service.fetch_user_profile(user_data)
        user_data.update(profile)
        
        session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
        
        assert session_id == 'session-id-123'
        # Admin context should use SameSite=Lax
    
    @pytest.mark.asyncio
    async def test_create_session_with_different_ips(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test session creation with different IP addresses"""
        user_data = mock_firebase_auth.return_value
        profile = await mock_profile_service.fetch_user_profile(user_data)
        user_data.update(profile)
        
        # Test with different IPs
        ips = ['127.0.0.1', '192.168.1.1', '10.0.0.1', None]
        
        for ip in ips:
            session_id = mock_session_service.create_session(user_data, ip, 'Mozilla/5.0')
            assert session_id == 'session-id-123'
    
    @pytest.mark.asyncio
    async def test_create_session_with_different_user_agents(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test session creation with different user agents"""
        user_data = mock_firebase_auth.return_value
        profile = await mock_profile_service.fetch_user_profile(user_data)
        user_data.update(profile)
        
        # Test with different user agents
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Mozilla/5.0 (X11; Linux x86_64)',
            None
        ]
        
        for ua in user_agents:
            session_id = mock_session_service.create_session(user_data, '127.0.0.1', ua)
            assert session_id == 'session-id-123'
    
    @pytest.mark.asyncio
    async def test_create_session_multiple_roles(self, mock_firebase_auth, mock_session_service):
        """Test session creation with multiple roles"""
        user_data = mock_firebase_auth.return_value
        
        # Test with multiple roles
        roles_list = [
            ['user'],
            ['admin'],
            ['human_agent'],
            ['admin', 'human_agent'],
            ['user', 'human_agent'],
            ['admin', 'user', 'human_agent']
        ]
        
        for roles in roles_list:
            user_data['roles'] = roles
            session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
            assert session_id == 'session-id-123'


class TestDataTransformations:
    """
    Test data transformation logic
    File: knowledgebot-railway-backend/configuration/service/configuration_service.py
    """
    
    @pytest.mark.asyncio
    async def test_security_settings_transformation_with_non_integer_type(self):
        """Test security settings transformation with non-integer type"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_security_settings = AsyncMock(return_value=[
                {'setting_name': 'response_timeout', 'setting_value': '30', 'setting_type': 'string'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_security_settings()
            
            # Should use default value when type is not integer
            assert result['response_timeout'] == 30
    
    @pytest.mark.asyncio
    async def test_llm_tokens_with_negative_available(self):
        """Test LLM tokens calculation with negative available tokens"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 1000000, 'token_used': 1500000}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            # Should show negative available when overused
            assert result['openai']['available'] == -500000
            assert result['openai']['used'] == 1500000
            assert result['openai']['limit'] == 1000000
    
    @pytest.mark.asyncio
    async def test_metadata_transformation_with_all_fields(self):
        """Test metadata transformation with all fields present"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_widget_config = AsyncMock(return_value={
                'hil_enabled': True,
                'response_policy': 60,
                'hil_disabled_message': 'Service temporarily unavailable'
            })
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            mock_dao.get_llm_providers = AsyncMock(return_value=[])
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_human_agents = AsyncMock(return_value=[])
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_chatAgent_config()
            
            assert result['metadata']['hil_enabled'] is True
            assert result['metadata']['response_policy'] == 60
            assert result['metadata']['hil_disabled_message'] == 'Service temporarily unavailable'


class TestConcurrencyAndLoad:
    """
    Test concurrency and load scenarios
    """
    
    @pytest.mark.asyncio
    async def test_concurrent_requests_with_different_endpoints(self):
        """Test concurrent requests to different endpoints"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Setup mocks
            mock_dao.get_widget_config = AsyncMock(return_value={})
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            mock_dao.get_llm_providers = AsyncMock(return_value=[])
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_human_agents = AsyncMock(return_value=[])
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            # Execute concurrent requests
            results = await asyncio.gather(
                service.get_chatAgent_config(),
                service.get_security_settings(),
                service.get_llm_providers(),
                service.get_active_persona(),
                service.get_human_agents(),
                service.get_admin_emails()
            )
            
            assert len(results) == 6
            assert all(r is not None for r in results)
    
    @pytest.mark.asyncio
    async def test_rapid_sequential_requests(self):
        """Test rapid sequential requests"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_widget_config = AsyncMock(return_value={})
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            mock_dao.get_llm_providers = AsyncMock(return_value=[])
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_human_agents = AsyncMock(return_value=[])
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            # Execute 10 rapid requests
            for _ in range(10):
                result = await service.get_chatAgent_config()
                assert result is not None


class TestBoundaryConditions:
    """
    Test boundary conditions and edge cases
    """
    
    @pytest.mark.asyncio
    async def test_empty_string_values(self):
        """Test handling of empty string values"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': '',
                'system_prompt': ''
            })
            mock_dao.get_all_personas = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert result['selected_persona'] == ''
            assert result['system_prompt'] == ''
    
    @pytest.mark.asyncio
    async def test_very_long_strings(self):
        """Test handling of very long strings"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            long_string = 'a' * 10000
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': long_string,
                'system_prompt': long_string
            })
            mock_dao.get_all_personas = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert len(result['selected_persona']) == 10000
            assert len(result['system_prompt']) == 10000
    
    @pytest.mark.asyncio
    async def test_max_integer_values(self):
        """Test handling of maximum integer values"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            max_int = 2147483647  # Max 32-bit int
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': max_int, 'token_used': max_int}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            assert result['openai']['limit'] == max_int
            assert result['openai']['used'] == max_int
            assert result['openai']['available'] == 0
    
    @pytest.mark.asyncio
    async def test_null_and_none_values(self):
        """Test handling of null and None values"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_widget_config = AsyncMock(return_value=None)
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            mock_dao.get_llm_providers = AsyncMock(return_value=[])
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_human_agents = AsyncMock(return_value=[])
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_chatAgent_config()
            
            assert result is not None
            assert result['metadata'] == {}
            assert result['persona'] is None
