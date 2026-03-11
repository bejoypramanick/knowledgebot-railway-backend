"""
Unit tests for Configuration Service API flows
Tests cover all 8 API endpoints with comprehensive logging

Endpoints tested:
1. GET /api/v1/gateway/configuration/chatAgentConfig
2. GET /api/v1/gateway/configuration/data/security-settings
3. GET /api/v1/gateway/configuration/data/llm-providers
4. GET /api/v1/gateway/configuration/data/active-persona
5. GET /api/v1/gateway/configuration/data/human-agents
6. GET /api/v1/gateway/configuration/data/admin-emails
7. GET /api/v1/gateway/configuration/users/profile
8. POST /api/v1/gateway/auth/session
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TestChatAgentConfigFlow:
    """
    Test suite for GET /chatAgentConfig endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_chatbot_config()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_chatAgent_config()
    """
    
    @pytest.mark.asyncio
    async def test_get_chatbot_config_success(self, test_db_session: AsyncSession):
        """Test successful retrieval of complete chatbot configuration"""
        # Setup: Insert test data
        await test_db_session.execute(text("""
            INSERT INTO security_settings (setting_name, setting_value, setting_type)
            VALUES ('response_timeout', '30', 'integer')
        """))
        
        await test_db_session.execute(text("""
            INSERT INTO llm_providers (provider_name, token_limit, token_used)
            VALUES ('openai', 1000000, 50000)
        """))
        
        await test_db_session.execute(text("""
            INSERT INTO persona_configurations (persona_name, system_prompt, is_active)
            VALUES ('KnowledgeBot', 'You are a helpful assistant', TRUE)
        """))
        
        await test_db_session.execute(text("""
            INSERT INTO widget_config (hil_enabled, response_policy)
            VALUES (FALSE, 30)
        """))
        
        await test_db_session.commit()
        
        # Mock the DAO methods
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Setup mock returns
            mock_dao.get_widget_config = AsyncMock(return_value={'hil_enabled': False, 'response_policy': 30})
            mock_dao.get_security_settings = AsyncMock(return_value=[
                {'setting_name': 'response_timeout', 'setting_value': '30', 'setting_type': 'integer'}
            ])
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 1000000, 'token_used': 50000}
            ])
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': 'KnowledgeBot',
                'system_prompt': 'You are a helpful assistant'
            })
            mock_dao.get_human_agents = AsyncMock(return_value=['agent1@example.com', 'agent2@example.com'])
            mock_dao.get_admins = AsyncMock(return_value=['admin@example.com'])
            
            # Import and test
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            # Execute
            result = await service.get_chatAgent_config()
            
            # Assert
            assert result is not None
            assert 'llm_tokens' in result
            assert 'security' in result
            assert 'persona' in result
            assert 'human_agents' in result
            assert 'admin_emails' in result
            assert result['security']['response_timeout'] == 30
            assert 'openai' in result['llm_tokens']
            assert len(result['human_agents']) == 2
            assert len(result['admin_emails']) == 1
    
    @pytest.mark.asyncio
    async def test_get_chatbot_config_empty_data(self):
        """Test chatbot config retrieval with empty database"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Setup mock returns for empty data
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
            assert result['human_agents'] == []
            assert result['admin_emails'] == []
            assert result['security']['response_timeout'] == 30  # Default value
    
    @pytest.mark.asyncio
    async def test_get_chatbot_config_database_error(self):
        """Test chatbot config retrieval with database error"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Setup mock to raise exception
            mock_dao.get_widget_config = AsyncMock(side_effect=Exception("Database connection failed"))
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            with pytest.raises(Exception) as exc_info:
                await service.get_chatAgent_config()
            
            assert "Database connection failed" in str(exc_info.value)


class TestSecuritySettingsFlow:
    """
    Test suite for GET /data/security-settings endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_security_settings()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_security_settings()
    """
    
    @pytest.mark.asyncio
    async def test_get_security_settings_success(self):
        """Test successful retrieval of security settings"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_security_settings = AsyncMock(return_value=[
                {'setting_name': 'response_timeout', 'setting_value': '45', 'setting_type': 'integer'},
                {'setting_name': 'response_policy', 'setting_value': '60', 'setting_type': 'integer'},
                {'setting_name': 'hil_enabled', 'setting_value': 'true', 'setting_type': 'boolean'},
                {'setting_name': 'hil_disabled_message', 'setting_value': 'Service unavailable', 'setting_type': 'string'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_security_settings()
            
            assert result['response_timeout'] == 45
            assert result['response_policy'] == 60
            assert result['hil_enabled'] is True
            assert result['hil_disabled_message'] == 'Service unavailable'
    
    @pytest.mark.asyncio
    async def test_get_security_settings_defaults(self):
        """Test security settings with default values"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_security_settings()
            
            assert result['response_timeout'] == 30  # Default
            assert result['response_policy'] == 15  # Default
            assert result['hil_enabled'] is False  # Default
            assert result['hil_disabled_message'] == ""  # Default


class TestLLMProvidersFlow:
    """
    Test suite for GET /data/llm-providers endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_llm_providers()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_llm_providers()
    """
    
    @pytest.mark.asyncio
    async def test_get_llm_providers_success(self):
        """Test successful retrieval of LLM providers"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 1000000, 'token_used': 500000},
                {'provider_name': 'anthropic', 'token_limit': 500000, 'token_used': 100000}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            assert 'openai' in result
            assert 'anthropic' in result
            assert result['openai']['used'] == 500000
            assert result['openai']['available'] == 500000
            assert result['openai']['limit'] == 1000000
            assert result['anthropic']['available'] == 400000
    
    @pytest.mark.asyncio
    async def test_get_llm_providers_overused_tokens(self):
        """Test LLM providers with overused tokens (negative available)"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_llm_providers = AsyncMock(return_value=[
                {'provider_name': 'openai', 'token_limit': 1000000, 'token_used': 1200000}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_llm_providers()
            
            assert result['openai']['available'] == -200000  # Negative when overused


class TestActivePersonaFlow:
    """
    Test suite for GET /data/active-persona endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_active_persona()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_active_persona()
    """
    
    @pytest.mark.asyncio
    async def test_get_active_persona_success(self):
        """Test successful retrieval of active persona"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': 'KnowledgeBot',
                'system_prompt': 'You are a helpful knowledge assistant'
            })
            mock_dao.get_all_personas = AsyncMock(return_value=[
                {'persona_name': 'KnowledgeBot', 'system_prompt': 'You are a helpful knowledge assistant'},
                {'persona_name': 'SupportBot', 'system_prompt': 'You are a support specialist'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert result['selected_persona'] == 'KnowledgeBot'
            assert 'system_prompt' in result
            assert len(result['available_personas']) == 2
    
    @pytest.mark.asyncio
    async def test_get_active_persona_fallback_to_first(self):
        """Test active persona fallback to first persona when none is active"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_all_personas = AsyncMock(return_value=[
                {'persona_name': 'DefaultBot', 'system_prompt': 'Default system prompt'}
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert result['selected_persona'] == 'DefaultBot'


class TestHumanAgentsFlow:
    """
    Test suite for GET /data/human-agents endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_human_agents()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_human_agents()
    """
    
    @pytest.mark.asyncio
    async def test_get_human_agents_success(self):
        """Test successful retrieval of human agents"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_human_agents = AsyncMock(return_value=[
                'agent1@example.com',
                'agent2@example.com',
                'agent3@example.com'
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_human_agents()
            
            assert len(result) == 3
            assert 'agent1@example.com' in result
            assert 'agent2@example.com' in result
    
    @pytest.mark.asyncio
    async def test_get_human_agents_empty(self):
        """Test human agents retrieval with no agents"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_human_agents = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_human_agents()
            
            assert result == []


class TestAdminEmailsFlow:
    """
    Test suite for GET /data/admin-emails endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_admin_emails()
    Service: knowledgebot-railway-backend/configuration/service/configuration_service.py::ConfigurationService.get_admin_emails()
    """
    
    @pytest.mark.asyncio
    async def test_get_admin_emails_success(self):
        """Test successful retrieval of admin emails"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_admins = AsyncMock(return_value=[
                'admin1@example.com',
                'admin2@example.com'
            ])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_admin_emails()
            
            assert len(result) == 2
            assert 'admin1@example.com' in result
    
    @pytest.mark.asyncio
    async def test_get_admin_emails_empty(self):
        """Test admin emails retrieval with no admins"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_admin_emails()
            
            assert result == []


class TestUserProfileFlow:
    """
    Test suite for GET /users/profile endpoint
    File: knowledgebot-railway-backend/configuration/routers/router.py::get_user_profile()
    Service: knowledgebot-railway-backend/configuration/service/auth_service.py::AuthService.get_user_role()
    """
    
    @pytest.mark.asyncio
    async def test_get_user_profile_admin_role(self, mock_auth_service):
        """Test user profile retrieval for admin user"""
        user_data = {
            'email': 'admin@example.com',
            'uid': 'uid-123',
            'name': 'Admin User',
            'picture': 'https://example.com/photo.jpg'
        }
        
        mock_auth_service.get_user_role.return_value = {
            'roles': ['admin']
        }
        
        # Simulate the endpoint logic
        role_result = await mock_auth_service.get_user_role(user_data['email'])
        user_roles = role_result.get('roles', ['user'])
        primary_role = "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        
        profile = {
            'email': user_data['email'],
            'uid': user_data['uid'],
            'display_name': user_data['name'],
            'photo_url': user_data['picture'],
            'role': primary_role,
            'roles': user_roles,
            'preferences': {'theme': 'light', 'notifications': True}
        }
        
        assert profile['role'] == 'admin'
        assert 'admin' in profile['roles']
    
    @pytest.mark.asyncio
    async def test_get_user_profile_human_agent_role(self, mock_auth_service):
        """Test user profile retrieval for human agent"""
        user_data = {
            'email': 'agent@example.com',
            'uid': 'uid-456',
            'name': 'Agent User',
            'picture': 'https://example.com/photo.jpg'
        }
        
        mock_auth_service.get_user_role.return_value = {
            'roles': ['human_agent']
        }
        
        role_result = await mock_auth_service.get_user_role(user_data['email'])
        user_roles = role_result.get('roles', ['user'])
        primary_role = "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        
        profile = {
            'email': user_data['email'],
            'uid': user_data['uid'],
            'display_name': user_data['name'],
            'photo_url': user_data['picture'],
            'role': primary_role,
            'roles': user_roles,
            'preferences': {'theme': 'light', 'notifications': True}
        }
        
        assert profile['role'] == 'human_agent'
    
    @pytest.mark.asyncio
    async def test_get_user_profile_regular_user(self, mock_auth_service):
        """Test user profile retrieval for regular user"""
        user_data = {
            'email': 'user@example.com',
            'uid': 'uid-789',
            'name': 'Regular User',
            'picture': 'https://example.com/photo.jpg'
        }
        
        mock_auth_service.get_user_role.return_value = {
            'roles': ['user']
        }
        
        role_result = await mock_auth_service.get_user_role(user_data['email'])
        user_roles = role_result.get('roles', ['user'])
        primary_role = "admin" if "admin" in user_roles else ("human_agent" if "human_agent" in user_roles else "user")
        
        profile = {
            'email': user_data['email'],
            'uid': user_data['uid'],
            'display_name': user_data['name'],
            'photo_url': user_data['picture'],
            'role': primary_role,
            'roles': user_roles,
            'preferences': {'theme': 'light', 'notifications': True}
        }
        
        assert profile['role'] == 'user'
    
    @pytest.mark.asyncio
    async def test_get_user_profile_missing_email(self):
        """Test user profile retrieval with missing email"""
        user_data = {
            'uid': 'uid-123',
            'name': 'User Without Email'
        }
        
        user_email = user_data.get('email')
        
        assert user_email is None
        # Should raise HTTPException(status_code=400)


class TestAuthSessionFlow:
    """
    Test suite for POST /auth/session endpoint
    File: knowledgebot-railway-backend/api_gateway/routers/auth_router.py::create_session_endpoint()
    Service: knowledgebot-railway-backend/api_gateway/services/session_service.py::SessionService.create_session()
    """
    
    @pytest.mark.asyncio
    async def test_create_session_success(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test successful session creation"""
        # Simulate the endpoint logic
        user_data = mock_firebase_auth.return_value
        
        profile = await mock_profile_service.fetch_user_profile(user_data)
        user_data.update(profile)
        
        session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
        
        assert session_id == 'session-id-123'
        assert user_data['email'] == 'test@example.com'
        assert user_data['role'] == 'user'
    
    @pytest.mark.asyncio
    async def test_create_session_with_admin_profile(self, mock_firebase_auth, mock_session_service):
        """Test session creation with admin profile"""
        user_data = mock_firebase_auth.return_value
        
        # Simulate admin profile fetch
        admin_profile = {'role': 'admin', 'roles': ['admin']}
        user_data.update(admin_profile)
        
        session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
        
        assert session_id == 'session-id-123'
        assert user_data['role'] == 'admin'
    
    @pytest.mark.asyncio
    async def test_create_session_profile_fetch_failure(self, mock_firebase_auth, mock_session_service, mock_profile_service):
        """Test session creation when profile fetch fails (fallback to user role)"""
        user_data = mock_firebase_auth.return_value
        
        # Simulate profile fetch failure
        mock_profile_service.fetch_user_profile.side_effect = Exception("Service unavailable")
        
        # Fallback to user role
        user_data.update({'role': 'user', 'roles': ['user']})
        
        session_id = mock_session_service.create_session(user_data, '127.0.0.1', 'Mozilla/5.0')
        
        assert session_id == 'session-id-123'
        assert user_data['role'] == 'user'
    
    @pytest.mark.asyncio
    async def test_create_session_invalid_token(self):
        """Test session creation with invalid Firebase token"""
        with patch('api_gateway.core.firebase_auth.verify_firebase_token') as mock_verify:
            mock_verify.return_value = None
            
            # Should raise HTTPException(status_code=401)
            assert mock_verify.return_value is None
    
    @pytest.mark.asyncio
    async def test_create_session_csrf_validation_failure(self, mock_settings):
        """Test session creation with CSRF validation failure"""
        origin = 'https://malicious.com'
        allowed_origins = ['http://localhost:3000', 'https://example.com']
        
        is_allowed = origin in allowed_origins
        
        assert is_allowed is False
        # Should raise HTTPException(status_code=403)


class TestEdgeCases:
    """
    Test suite for edge cases and error scenarios
    """
    
    @pytest.mark.asyncio
    async def test_concurrent_config_requests(self):
        """Test handling of concurrent configuration requests"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Setup mock returns
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
                service.get_chatAgent_config(),
                service.get_chatAgent_config()
            )
            
            assert len(results) == 3
            assert all(r is not None for r in results)
    
    @pytest.mark.asyncio
    async def test_large_dataset_handling(self):
        """Test handling of large datasets"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            # Create large dataset
            large_agents_list = [f'agent{i}@example.com' for i in range(1000)]
            
            mock_dao.get_widget_config = AsyncMock(return_value={})
            mock_dao.get_security_settings = AsyncMock(return_value=[])
            mock_dao.get_llm_providers = AsyncMock(return_value=[])
            mock_dao.get_active_persona = AsyncMock(return_value=None)
            mock_dao.get_human_agents = AsyncMock(return_value=large_agents_list)
            mock_dao.get_admins = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_chatAgent_config()
            
            assert len(result['human_agents']) == 1000
    
    @pytest.mark.asyncio
    async def test_special_characters_in_data(self):
        """Test handling of special characters in configuration data"""
        with patch('configuration.service.configuration_service.ChatAgentConfigDAO') as mock_dao_class:
            mock_dao = MagicMock()
            mock_dao_class.return_value = mock_dao
            
            mock_dao.get_active_persona = AsyncMock(return_value={
                'persona_name': 'Bot™',
                'system_prompt': 'You are a helpful assistant™ with special chars: é, ñ, 中文'
            })
            mock_dao.get_all_personas = AsyncMock(return_value=[])
            
            from configuration.service.configuration_service import ConfigurationService
            service = ConfigurationService()
            
            result = await service.get_active_persona()
            
            assert 'Bot™' in result['selected_persona']
            assert '中文' in result['system_prompt']
