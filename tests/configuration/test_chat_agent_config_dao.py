"""
Unit tests for ChatAgentConfigDAO
Tests database access layer for chat agent configuration

Files covered:
- knowledgebot-railway-backend/configuration/dao/chat_agent_config_dao.py

Functions tested:
- ChatAgentConfigDAO.get_security_settings()
- ChatAgentConfigDAO.get_llm_providers()
- ChatAgentConfigDAO.get_active_persona()
- ChatAgentConfigDAO.get_human_agents()
- ChatAgentConfigDAO.get_admins()
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import text


@pytest.mark.asyncio
async def test_get_security_settings_success(mock_security_settings):
    """
    Test: ChatAgentConfigDAO.get_security_settings() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_security_settings()
    
    Verifies that security settings are correctly fetched from database
    and returned as list of dictionaries
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    # Mock the database session and query execution
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        # Create mock row objects with _mapping attribute
        mock_rows = []
        for setting in mock_security_settings:
            mock_row = MagicMock()
            mock_row._mapping = setting
            mock_rows.append(mock_row)
        
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        # Execute
        result = await dao.get_security_settings()
        
        # Assert
        assert result == mock_security_settings
        assert len(result) == 2
        assert result[0]['setting_name'] == 'response_timeout'
        assert result[0]['setting_value'] == '30'
        assert result[1]['setting_name'] == 'remove_pii'


@pytest.mark.asyncio
async def test_get_security_settings_empty():
    """
    Test: ChatAgentConfigDAO.get_security_settings() - Empty result
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_security_settings()
    
    Edge case: No security settings in database
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_security_settings()
        
        assert result == []


@pytest.mark.asyncio
async def test_get_security_settings_database_error():
    """
    Test: ChatAgentConfigDAO.get_security_settings() - Database error
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_security_settings()
    
    Edge case: Database connection fails
    Verifies exception is raised (not silently caught)
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database connection failed")
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        with pytest.raises(Exception) as exc_info:
            await dao.get_security_settings()
        
        assert "Database connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_llm_providers_success(mock_llm_providers):
    """
    Test: ChatAgentConfigDAO.get_llm_providers() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_llm_providers()
    
    Verifies LLM providers are correctly fetched with token limits
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_rows = []
        for provider in mock_llm_providers:
            mock_row = MagicMock()
            mock_row._mapping = provider
            mock_rows.append(mock_row)
        
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_llm_providers()
        
        assert result == mock_llm_providers
        assert len(result) == 2
        assert result[0]['provider_name'] == 'gemini'
        assert result[0]['token_limit'] == 1000000


@pytest.mark.asyncio
async def test_get_active_persona_success(mock_persona):
    """
    Test: ChatAgentConfigDAO.get_active_persona() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_active_persona()
    
    Verifies active persona is correctly fetched
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_row = MagicMock()
        mock_row._mapping = mock_persona
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_active_persona()
        
        assert result == mock_persona
        assert result['persona_name'] == 'helpful_assistant'
        assert result['is_active'] is True


@pytest.mark.asyncio
async def test_get_active_persona_none():
    """
    Test: ChatAgentConfigDAO.get_active_persona() - No active persona
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_active_persona()
    
    Edge case: No active persona in database
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_active_persona()
        
        assert result is None


@pytest.mark.asyncio
async def test_get_human_agents_success(mock_human_agents):
    """
    Test: ChatAgentConfigDAO.get_human_agents() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_human_agents()
    
    Verifies human agent emails are correctly fetched from user_role_mapping
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_rows = []
        for email in mock_human_agents:
            mock_row = MagicMock()
            mock_row._mapping = {'email': email}
            mock_rows.append(mock_row)
        
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_human_agents()
        
        assert result == mock_human_agents
        assert len(result) == 3
        assert 'agent1@example.com' in result


@pytest.mark.asyncio
async def test_get_human_agents_empty():
    """
    Test: ChatAgentConfigDAO.get_human_agents() - No agents
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_human_agents()
    
    Edge case: No human agents assigned
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_human_agents()
        
        assert result == []


@pytest.mark.asyncio
async def test_get_admins_success(mock_admin_emails):
    """
    Test: ChatAgentConfigDAO.get_admins() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_admins()
    
    Verifies admin emails are correctly fetched from user_role_mapping
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_rows = []
        for email in mock_admin_emails:
            mock_row = MagicMock()
            mock_row._mapping = {'email': email}
            mock_rows.append(mock_row)
        
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_admins()
        
        assert result == mock_admin_emails
        assert len(result) == 2
        assert 'admin1@example.com' in result


@pytest.mark.asyncio
async def test_get_admins_empty():
    """
    Test: ChatAgentConfigDAO.get_admins() - No admins
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_admins()
    
    Edge case: No admins in system
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_admins()
        
        assert result == []
