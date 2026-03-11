"""
Extended unit tests for ChatAgentConfigDAO - Additional coverage for 100%
Tests additional DAO methods and edge cases

Files covered:
- knowledgebot-railway-backend/configuration/dao/chat_agent_config_dao.py

Functions tested:
- ChatAgentConfigDAO.upsert_security_setting()
- ChatAgentConfigDAO.sync_admin_emails()
- ChatAgentConfigDAO.sync_human_agent_emails()
- ChatAgentConfigDAO.update_llm_provider_tokens()
- ChatAgentConfigDAO.add_human_agent()
- ChatAgentConfigDAO.remove_human_agent()
- ChatAgentConfigDAO.add_admin()
- ChatAgentConfigDAO.remove_admin()
- ChatAgentConfigDAO.get_all_personas()
- ChatAgentConfigDAO.update_persona()
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_upsert_security_setting_success():
    """
    Test: ChatAgentConfigDAO.upsert_security_setting() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: upsert_security_setting()
    
    Verifies security setting is upserted (inserted or updated)
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        await dao.upsert_security_setting('response_timeout', '60', 'integer')
        
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_security_setting_error():
    """
    Test: ChatAgentConfigDAO.upsert_security_setting() - Database error
    File: configuration/dao/chat_agent_config_dao.py
    Function: upsert_security_setting()
    
    Edge case: Database error during upsert
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        with pytest.raises(Exception) as exc_info:
            await dao.upsert_security_setting('response_timeout', '60', 'integer')
        
        assert "Database error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_add_human_agent_success():
    """
    Test: ChatAgentConfigDAO.add_human_agent() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: add_human_agent()
    
    Verifies human agent is added successfully
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.add_human_agent('agent@example.com')
        
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_add_human_agent_error():
    """
    Test: ChatAgentConfigDAO.add_human_agent() - Error case
    File: configuration/dao/chat_agent_config_dao.py
    Function: add_human_agent()
    
    Edge case: Error adding human agent
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Add failed")
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        with pytest.raises(Exception):
            await dao.add_human_agent('agent@example.com')


@pytest.mark.asyncio
async def test_remove_human_agent_success():
    """
    Test: ChatAgentConfigDAO.remove_human_agent() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: remove_human_agent()
    
    Verifies human agent is removed successfully
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.remove_human_agent('agent@example.com')
        
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_add_admin_success():
    """
    Test: ChatAgentConfigDAO.add_admin() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: add_admin()
    
    Verifies admin is added successfully
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.add_admin('admin@example.com')
        
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_remove_admin_success():
    """
    Test: ChatAgentConfigDAO.remove_admin() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: remove_admin()
    
    Verifies admin is removed successfully
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.remove_admin('admin@example.com')
        
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_sync_admin_emails_success():
    """
    Test: ChatAgentConfigDAO.sync_admin_emails() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: sync_admin_emails()
    
    Verifies admin emails are synced
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        await dao.sync_admin_emails(['admin1@example.com', 'admin2@example.com'])
        
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_sync_human_agent_emails_success():
    """
    Test: ChatAgentConfigDAO.sync_human_agent_emails() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: sync_human_agent_emails()
    
    Verifies human agent emails are synced
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        await dao.sync_human_agent_emails(['agent1@example.com', 'agent2@example.com'])
        
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_update_llm_provider_tokens_success():
    """
    Test: ChatAgentConfigDAO.update_llm_provider_tokens() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: update_llm_provider_tokens()
    
    Verifies LLM provider tokens are updated
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.update_llm_provider_tokens('gemini', 1000000, 250000)
        
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_get_all_personas_success(mock_persona):
    """
    Test: ChatAgentConfigDAO.get_all_personas() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_all_personas()
    
    Verifies all personas are fetched
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_rows = []
        mock_row = MagicMock()
        mock_row._mapping = mock_persona
        mock_rows.append(mock_row)
        
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_all_personas()
        
        assert len(result) == 1
        assert result[0] == mock_persona


@pytest.mark.asyncio
async def test_update_persona_success():
    """
    Test: ChatAgentConfigDAO.update_persona() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: update_persona()
    
    Verifies persona is updated
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        await dao.update_persona('helpful_assistant', 'Updated prompt', True)
        
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()


@pytest.mark.asyncio
async def test_get_widget_config_success(mock_widget_config):
    """
    Test: ChatAgentConfigDAO.get_widget_config() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_widget_config()
    
    Verifies widget config is fetched
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        
        mock_row = MagicMock()
        mock_row._mapping = mock_widget_config
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        result = await dao.get_widget_config()
        
        assert result == mock_widget_config


@pytest.mark.asyncio
async def test_get_widget_config_none():
    """
    Test: ChatAgentConfigDAO.get_widget_config() - No config
    File: configuration/dao/chat_agent_config_dao.py
    Function: get_widget_config()
    
    Edge case: No widget config in database
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
        
        result = await dao.get_widget_config()
        
        assert result is None


@pytest.mark.asyncio
async def test_save_chat_agent_config_success():
    """
    Test: ChatAgentConfigDAO.save_chat_agent_config() - Success case
    File: configuration/dao/chat_agent_config_dao.py
    Function: save_chat_agent_config()
    
    Verifies complete config is saved
    """
    from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
    
    dao = ChatAgentConfigDAO()
    
    with patch('configuration.dao.chat_agent_config_dao.get_db_session') as mock_get_session:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_get_session.return_value = mock_session
        
        await dao.save_chat_agent_config(
            admin_emails=['admin@example.com'],
            human_agents=['agent@example.com'],
            security_settings={'response_timeout': 30},
            llm_tokens={'gemini': 1000000},
            persona_name='helpful_assistant',
            system_prompt='Test prompt'
        )
        
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()
