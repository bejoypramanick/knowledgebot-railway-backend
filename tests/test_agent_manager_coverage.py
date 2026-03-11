"""
Comprehensive test coverage for AgentManager changes:
- System prompt caching
- Custom prompt injection
- Configuration fetching
- Agent creation and caching
"""

import pytest
import asyncio
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, Optional

from chatbot_orchestration.service.agent_manager import AgentManager
from chatbot_orchestration.agent.prompt import get_system_prompt


class TestAgentManagerInit:
    """Test AgentManager initialization"""
    
    def test_init_creates_agent_cache(self):
        """Test that __init__ creates agent_cache dict"""
        manager = AgentManager()
        assert hasattr(manager, 'agent_cache')
        assert isinstance(manager.agent_cache, dict)
        assert len(manager.agent_cache) == 0
    
    def test_init_creates_system_prompt_cache(self):
        """Test that __init__ creates system_prompt_cache dict"""
        manager = AgentManager()
        assert hasattr(manager, 'system_prompt_cache')
        assert isinstance(manager.system_prompt_cache, dict)
        assert len(manager.system_prompt_cache) == 0
    
    def test_init_sets_genai_client_to_none(self):
        """Test that __init__ sets genai_client to None"""
        manager = AgentManager()
        assert hasattr(manager, 'genai_client')
        assert manager.genai_client is None


class TestAgentManagerInitialize:
    """Test AgentManager.initialize method"""
    
    @pytest.mark.asyncio
    async def test_initialize_calls_get_genai_client(self):
        """Test that initialize calls get_genai_client"""
        manager = AgentManager()
        
        with patch('chatbot_orchestration.service.agent_manager.get_genai_client') as mock_get_client:
            mock_get_client.return_value = MagicMock()
            await manager.initialize()
            mock_get_client.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_sets_genai_client(self):
        """Test that initialize sets genai_client"""
        manager = AgentManager()
        mock_client = MagicMock()
        
        with patch('chatbot_orchestration.service.agent_manager.get_genai_client') as mock_get_client:
            mock_get_client.return_value = mock_client
            await manager.initialize()
            assert manager.genai_client == mock_client
    
    @pytest.mark.asyncio
    async def test_initialize_idempotent(self):
        """Test that initialize is idempotent"""
        manager = AgentManager()
        mock_client = MagicMock()
        
        with patch('chatbot_orchestration.service.agent_manager.get_genai_client') as mock_get_client:
            mock_get_client.return_value = mock_client
            await manager.initialize()
            first_client = manager.genai_client
            
            # Call again
            await manager.initialize()
            # Should not call get_genai_client again
            assert mock_get_client.call_count == 1
            assert manager.genai_client == first_client


class TestFetchPersonaConfig:
    """Test _fetch_persona_config method"""
    
    @pytest.mark.asyncio
    async def test_fetch_persona_config_uses_env_variable(self):
        """Test that _fetch_persona_config uses CONFIGURATION_SERVICE_URL env var"""
        manager = AgentManager()
        
        with patch('os.getenv') as mock_getenv:
            mock_getenv.return_value = 'http://test-config-service:8080'
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'data': {
                        'persona': {
                            'system_prompt': 'Test prompt',
                            'selected_persona': 'TestBot'
                        }
                    }
                }
                
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
                
                result = await manager._fetch_persona_config()
                
                # Verify os.getenv was called with correct key
                mock_getenv.assert_called_with('CONFIGURATION_SERVICE_URL', 'http://configuration.railway.internal:8080')
    
    @pytest.mark.asyncio
    async def test_fetch_persona_config_fallback_url(self):
        """Test that _fetch_persona_config uses fallback URL when env var not set"""
        manager = AgentManager()
        
        with patch('os.getenv') as mock_getenv:
            # Simulate env var not set
            mock_getenv.return_value = 'http://configuration.railway.internal:8080'
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'data': {
                        'persona': {
                            'system_prompt': 'Test prompt',
                            'selected_persona': 'TestBot'
                        }
                    }
                }
                
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
                
                result = await manager._fetch_persona_config()
                
                # Should use fallback URL
                assert result['persona_name'] == 'TestBot'
    
    @pytest.mark.asyncio
    async def test_fetch_persona_config_success(self):
        """Test successful persona config fetch"""
        manager = AgentManager()
        
        with patch('os.getenv') as mock_getenv:
            mock_getenv.return_value = 'http://test-config:8080'
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'data': {
                        'persona': {
                            'system_prompt': 'Custom system prompt',
                            'selected_persona': 'CustomBot'
                        }
                    }
                }
                
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
                
                result = await manager._fetch_persona_config()
                
                assert result['persona_name'] == 'CustomBot'
                assert result['system_instructions'] == 'Custom system prompt'
    
    @pytest.mark.asyncio
    async def test_fetch_persona_config_error_returns_default(self):
        """Test that fetch error returns default persona config"""
        manager = AgentManager()
        
        with patch('os.getenv') as mock_getenv:
            mock_getenv.return_value = 'http://test-config:8080'
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.side_effect = Exception("Connection error")
                
                result = await manager._fetch_persona_config()
                
                # Should return default config
                assert result['persona_name'] == 'Knowledge Bot'
                assert 'system_instructions' in result


class TestGetDefaultPersonaConfig:
    """Test _get_default_persona_config method"""
    
    def test_get_default_persona_config_returns_dict(self):
        """Test that _get_default_persona_config returns a dict"""
        manager = AgentManager()
        result = manager._get_default_persona_config()
        
        assert isinstance(result, dict)
    
    def test_get_default_persona_config_has_required_keys(self):
        """Test that default config has required keys"""
        manager = AgentManager()
        result = manager._get_default_persona_config()
        
        assert 'persona_name' in result
        assert 'persona_description' in result
        assert 'system_instructions' in result
    
    def test_get_default_persona_config_values(self):
        """Test that default config has correct values"""
        manager = AgentManager()
        result = manager._get_default_persona_config()
        
        assert result['persona_name'] == 'Knowledge Bot'
        assert 'helpful AI assistant' in result['persona_description']
        assert 'HTML tags' in result['system_instructions']


class TestBuildSystemPrompt:
    """Test _build_system_prompt method"""
    
    @pytest.mark.asyncio
    async def test_build_system_prompt_with_custom_prompt(self):
        """Test that _build_system_prompt includes custom prompt"""
        manager = AgentManager()
        
        persona_config = {
            'persona_name': 'TestBot',
            'persona_description': 'Test description',
            'system_instructions': 'Custom instruction: Always be helpful'
        }
        
        with patch('chatbot_orchestration.service.agent_manager.get_system_prompt') as mock_get_prompt:
            mock_get_prompt.return_value = 'Base prompt with custom instruction: Always be helpful'
            
            result = await manager._build_system_prompt(persona_config)
            
            # Should call get_system_prompt with custom_prompt
            mock_get_prompt.assert_called_once()
            call_args = mock_get_prompt.call_args
            assert call_args[1]['custom_prompt'] == 'Custom instruction: Always be helpful'
    
    @pytest.mark.asyncio
    async def test_build_system_prompt_returns_string(self):
        """Test that _build_system_prompt returns a string"""
        manager = AgentManager()
        
        persona_config = {
            'persona_name': 'TestBot',
            'persona_description': 'Test description',
            'system_instructions': 'Test instruction'
        }
        
        with patch('chatbot_orchestration.service.agent_manager.get_system_prompt') as mock_get_prompt:
            mock_get_prompt.return_value = 'Test system prompt'
            
            result = await manager._build_system_prompt(persona_config)
            
            assert isinstance(result, str)
            assert len(result) > 0
    
    @pytest.mark.asyncio
    async def test_build_system_prompt_error_returns_fallback(self):
        """Test that build error returns fallback prompt"""
        manager = AgentManager()
        
        persona_config = {
            'persona_name': 'TestBot',
            'persona_description': 'Test description',
            'system_instructions': 'Test instruction'
        }
        
        with patch('chatbot_orchestration.service.agent_manager.get_system_prompt') as mock_get_prompt:
            mock_get_prompt.side_effect = Exception("Build error")
            
            result = await manager._build_system_prompt(persona_config)
            
            # Should return fallback prompt
            assert isinstance(result, str)
            assert 'TestBot' in result or 'helpful' in result


class TestGetCachedAgent:
    """Test get_cached_agent method"""
    
    def test_get_cached_agent_returns_none_when_not_cached(self):
        """Test that get_cached_agent returns None for uncached session"""
        manager = AgentManager()
        result = manager.get_cached_agent('nonexistent_session')
        assert result is None
    
    def test_get_cached_agent_returns_cached_agent(self):
        """Test that get_cached_agent returns cached agent"""
        manager = AgentManager()
        mock_agent = MagicMock()
        manager.agent_cache['test_session'] = mock_agent
        
        result = manager.get_cached_agent('test_session')
        assert result == mock_agent


class TestGetCachedSystemPrompt:
    """Test get_cached_system_prompt method"""
    
    def test_get_cached_system_prompt_returns_none_when_not_cached(self):
        """Test that get_cached_system_prompt returns None for uncached session"""
        manager = AgentManager()
        result = manager.get_cached_system_prompt('nonexistent_session')
        assert result is None
    
    def test_get_cached_system_prompt_returns_cached_prompt(self):
        """Test that get_cached_system_prompt returns cached prompt"""
        manager = AgentManager()
        test_prompt = 'This is a test system prompt'
        manager.system_prompt_cache['test_session'] = test_prompt
        
        result = manager.get_cached_system_prompt('test_session')
        assert result == test_prompt


class TestClearAgentCache:
    """Test clear_agent_cache method"""
    
    def test_clear_agent_cache_single_session(self):
        """Test clearing cache for a single session"""
        manager = AgentManager()
        manager.agent_cache['session1'] = MagicMock()
        manager.agent_cache['session2'] = MagicMock()
        manager.system_prompt_cache['session1'] = 'prompt1'
        manager.system_prompt_cache['session2'] = 'prompt2'
        
        manager.clear_agent_cache('session1')
        
        assert 'session1' not in manager.agent_cache
        assert 'session2' in manager.agent_cache
        assert 'session1' not in manager.system_prompt_cache
        assert 'session2' in manager.system_prompt_cache
    
    def test_clear_agent_cache_all_sessions(self):
        """Test clearing cache for all sessions"""
        manager = AgentManager()
        manager.agent_cache['session1'] = MagicMock()
        manager.agent_cache['session2'] = MagicMock()
        manager.system_prompt_cache['session1'] = 'prompt1'
        manager.system_prompt_cache['session2'] = 'prompt2'
        
        manager.clear_agent_cache()
        
        assert len(manager.agent_cache) == 0
        assert len(manager.system_prompt_cache) == 0
    
    def test_clear_agent_cache_nonexistent_session(self):
        """Test clearing cache for nonexistent session doesn't error"""
        manager = AgentManager()
        manager.agent_cache['session1'] = MagicMock()
        
        # Should not raise error
        manager.clear_agent_cache('nonexistent_session')
        
        assert 'session1' in manager.agent_cache


class TestCreateAgent:
    """Test create_agent method"""
    
    @pytest.mark.asyncio
    async def test_create_agent_returns_agent(self):
        """Test that create_agent returns an Agent instance"""
        manager = AgentManager()
        
        with patch.object(manager, 'initialize', new_callable=AsyncMock):
            with patch.object(manager, '_fetch_persona_config', new_callable=AsyncMock) as mock_fetch:
                with patch.object(manager, '_build_system_prompt', new_callable=AsyncMock) as mock_build:
                    with patch('chatbot_orchestration.service.agent_manager.GoogleModel'):
                        with patch('chatbot_orchestration.service.agent_manager.Agent') as mock_agent_class:
                            mock_fetch.return_value = {
                                'persona_name': 'TestBot',
                                'persona_description': 'Test',
                                'system_instructions': 'Test'
                            }
                            mock_build.return_value = 'Test system prompt'
                            mock_agent = MagicMock()
                            mock_agent_class.return_value = mock_agent
                            
                            result = await manager.create_agent('test_session')
                            
                            assert result == mock_agent
    
    @pytest.mark.asyncio
    async def test_create_agent_caches_agent(self):
        """Test that create_agent caches the agent"""
        manager = AgentManager()
        
        with patch.object(manager, 'initialize', new_callable=AsyncMock):
            with patch.object(manager, '_fetch_persona_config', new_callable=AsyncMock) as mock_fetch:
                with patch.object(manager, '_build_system_prompt', new_callable=AsyncMock) as mock_build:
                    with patch('chatbot_orchestration.service.agent_manager.GoogleModel'):
                        with patch('chatbot_orchestration.service.agent_manager.Agent') as mock_agent_class:
                            mock_fetch.return_value = {
                                'persona_name': 'TestBot',
                                'persona_description': 'Test',
                                'system_instructions': 'Test'
                            }
                            mock_build.return_value = 'Test system prompt'
                            mock_agent = MagicMock()
                            mock_agent_class.return_value = mock_agent
                            
                            await manager.create_agent('test_session')
                            
                            assert 'test_session' in manager.agent_cache
                            assert manager.agent_cache['test_session'] == mock_agent
    
    @pytest.mark.asyncio
    async def test_create_agent_caches_system_prompt(self):
        """Test that create_agent caches the system prompt"""
        manager = AgentManager()
        
        with patch.object(manager, 'initialize', new_callable=AsyncMock):
            with patch.object(manager, '_fetch_persona_config', new_callable=AsyncMock) as mock_fetch:
                with patch.object(manager, '_build_system_prompt', new_callable=AsyncMock) as mock_build:
                    with patch('chatbot_orchestration.service.agent_manager.GoogleModel'):
                        with patch('chatbot_orchestration.service.agent_manager.Agent') as mock_agent_class:
                            mock_fetch.return_value = {
                                'persona_name': 'TestBot',
                                'persona_description': 'Test',
                                'system_instructions': 'Test'
                            }
                            test_prompt = 'Test system prompt with custom instructions'
                            mock_build.return_value = test_prompt
                            mock_agent = MagicMock()
                            mock_agent_class.return_value = mock_agent
                            
                            await manager.create_agent('test_session')
                            
                            assert 'test_session' in manager.system_prompt_cache
                            assert manager.system_prompt_cache['test_session'] == test_prompt
    
    @pytest.mark.asyncio
    async def test_create_agent_uses_cached_agent(self):
        """Test that create_agent uses cached agent when available"""
        manager = AgentManager()
        mock_agent = MagicMock()
        manager.agent_cache['test_session'] = mock_agent
        
        with patch.object(manager, 'initialize', new_callable=AsyncMock) as mock_init:
            result = await manager.create_agent('test_session')
            
            # Should not call initialize since agent is cached
            mock_init.assert_not_called()
            assert result == mock_agent
    
    @pytest.mark.asyncio
    async def test_create_agent_force_new_ignores_cache(self):
        """Test that create_agent with force_new=True ignores cache"""
        manager = AgentManager()
        old_agent = MagicMock()
        manager.agent_cache['test_session'] = old_agent
        
        with patch.object(manager, 'initialize', new_callable=AsyncMock):
            with patch.object(manager, '_fetch_persona_config', new_callable=AsyncMock) as mock_fetch:
                with patch.object(manager, '_build_system_prompt', new_callable=AsyncMock) as mock_build:
                    with patch('chatbot_orchestration.service.agent_manager.GoogleModel'):
                        with patch('chatbot_orchestration.service.agent_manager.Agent') as mock_agent_class:
                            mock_fetch.return_value = {
                                'persona_name': 'TestBot',
                                'persona_description': 'Test',
                                'system_instructions': 'Test'
                            }
                            mock_build.return_value = 'Test system prompt'
                            new_agent = MagicMock()
                            mock_agent_class.return_value = new_agent
                            
                            result = await manager.create_agent('test_session', force_new=True)
                            
                            # Should return new agent, not old one
                            assert result == new_agent
                            assert result != old_agent


class TestGetSystemPromptCustomPromptInjection:
    """Test custom prompt injection in get_system_prompt"""
    
    def test_get_system_prompt_injects_custom_prompt(self):
        """Test that custom prompt is injected at the top"""
        custom_prompt = 'Always respond in JSON format'
        result = get_system_prompt(custom_prompt=custom_prompt)
        
        assert 'CUSTOM INSTRUCTIONS' in result
        assert custom_prompt in result
        
        # Custom prompt should come before base rules
        custom_idx = result.find(custom_prompt)
        rule0_idx = result.find('RULE 0:')
        assert custom_idx < rule0_idx
    
    def test_get_system_prompt_without_custom_prompt(self):
        """Test that system prompt works without custom prompt"""
        result = get_system_prompt(custom_prompt=None)
        
        assert 'CUSTOM INSTRUCTIONS' not in result
        assert 'RULE 0:' in result
    
    def test_get_system_prompt_with_empty_custom_prompt(self):
        """Test that empty custom prompt is ignored"""
        result = get_system_prompt(custom_prompt='')
        
        assert 'CUSTOM INSTRUCTIONS' not in result
        assert 'RULE 0:' in result
    
    def test_get_system_prompt_with_whitespace_custom_prompt(self):
        """Test that whitespace-only custom prompt is ignored"""
        result = get_system_prompt(custom_prompt='   \n\t  ')
        
        assert 'CUSTOM INSTRUCTIONS' not in result
        assert 'RULE 0:' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
