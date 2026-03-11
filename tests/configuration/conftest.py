"""
Pytest configuration and fixtures for configuration service tests
Provides mock database sessions, services, and DAOs for testing
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """Mock database session for DAO tests"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_security_settings() -> List[Dict[str, Any]]:
    """Mock security settings from database"""
    return [
        {
            'setting_name': 'response_timeout',
            'setting_value': '30',
            'setting_type': 'integer',
            'description': 'Response timeout in seconds'
        },
        {
            'setting_name': 'remove_pii',
            'setting_value': 'true',
            'setting_type': 'boolean',
            'description': 'Remove PII from responses'
        }
    ]


@pytest.fixture
def mock_llm_providers() -> List[Dict[str, Any]]:
    """Mock LLM providers from database"""
    return [
        {
            'provider_name': 'gemini',
            'token_limit': 1000000,
            'token_used': 250000
        },
        {
            'provider_name': 'openai',
            'token_limit': 500000,
            'token_used': 100000
        }
    ]


@pytest.fixture
def mock_persona() -> Dict[str, Any]:
    """Mock active persona from database"""
    return {
        'id': 1,
        'persona_name': 'helpful_assistant',
        'system_prompt': 'You are a helpful customer support assistant',
        'is_active': True,
        'created_at': '2024-01-01T00:00:00Z',
        'updated_at': '2024-01-01T00:00:00Z'
    }


@pytest.fixture
def mock_human_agents() -> List[str]:
    """Mock human agent emails"""
    return ['agent1@example.com', 'agent2@example.com', 'agent3@example.com']


@pytest.fixture
def mock_admin_emails() -> List[str]:
    """Mock admin emails"""
    return ['admin1@example.com', 'admin2@example.com']


@pytest.fixture
def mock_widget_config() -> Dict[str, Any]:
    """Mock widget configuration"""
    return {
        'hil_enabled': True,
        'response_policy': 30,
        'hil_disabled_message': 'Human agent not available',
        'widget_color': '#007bff',
        'widget_position': 'bottom-right'
    }


@pytest.fixture
def complete_config_response() -> Dict[str, Any]:
    """Complete mock configuration response"""
    return {
        'llm_tokens': {
            'gemini': 1000000,
            'openai': 500000
        },
        'security': {
            'response_timeout': 30,
            'remove_pii': True
        },
        'persona': {
            'id': 1,
            'persona_name': 'helpful_assistant',
            'system_prompt': 'You are a helpful customer support assistant',
            'is_active': True
        },
        'human_agents': ['agent1@example.com', 'agent2@example.com'],
        'admin_emails': ['admin1@example.com', 'admin2@example.com'],
        'metadata': {
            'hil_enabled': True,
            'response_policy': 30,
            'hil_disabled_message': 'Human agent not available'
        }
    }
