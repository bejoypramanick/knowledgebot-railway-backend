"""
Pytest fixtures for authentication and session tests.
Provides mock data, database sessions, and service dependencies.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import json


# ============================================================================
# MOCK DATA FIXTURES
# ============================================================================

@pytest.fixture
def mock_firebase_user():
    """Mock Firebase user data from token verification"""
    return {
        "uid": "firebase-uid-12345",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://example.com/avatar.jpg",
        "email_verified": True,
        "iss": "https://securetoken.google.com/project-id",
        "aud": "project-id",
        "auth_time": int(datetime.now().timestamp()),
        "user_id": "firebase-uid-12345",
        "sub": "firebase-uid-12345",
        "iat": int(datetime.now().timestamp()),
        "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        "firebase": {
            "identities": {},
            "sign_in_provider": "custom"
        }
    }


@pytest.fixture
def mock_user_profile():
    """Mock user profile from configuration service"""
    return {
        "uid": "firebase-uid-12345",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://example.com/avatar.jpg",
        "role": "admin",
        "roles": ["admin", "user"],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }


@pytest.fixture
def mock_admin_user():
    """Mock admin user data"""
    return {
        "uid": "admin-uid-12345",
        "email": "admin@example.com",
        "name": "Admin User",
        "picture": "https://example.com/admin.jpg",
        "role": "admin",
        "roles": ["admin", "user"]
    }


@pytest.fixture
def mock_human_agent_user():
    """Mock human agent user data"""
    return {
        "uid": "agent-uid-12345",
        "email": "agent@example.com",
        "name": "Human Agent",
        "picture": "https://example.com/agent.jpg",
        "role": "human_agent",
        "roles": ["human_agent", "user"]
    }


@pytest.fixture
def mock_regular_user():
    """Mock regular user data"""
    return {
        "uid": "user-uid-12345",
        "email": "customer@example.com",
        "name": "Regular User",
        "picture": "https://example.com/user.jpg",
        "role": "user",
        "roles": ["user"]
    }


@pytest.fixture
def mock_security_settings():
    """Mock security settings from database"""
    return {
        "setting_id": 1,
        "setting_key": "max_login_attempts",
        "setting_value": "5",
        "description": "Maximum login attempts before lockout",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }


@pytest.fixture
def mock_llm_providers():
    """Mock LLM providers configuration"""
    return {
        "providers": [
            {
                "provider_id": 1,
                "provider_name": "OpenAI",
                "model": "gpt-4",
                "token_limit": 8000,
                "tokens_used": 2500,
                "tokens_remaining": 5500,
                "reset_date": (datetime.now() + timedelta(days=30)).isoformat()
            },
            {
                "provider_id": 2,
                "provider_name": "Anthropic",
                "model": "claude-3",
                "token_limit": 10000,
                "tokens_used": 1000,
                "tokens_remaining": 9000,
                "reset_date": (datetime.now() + timedelta(days=30)).isoformat()
            }
        ]
    }


@pytest.fixture
def mock_active_persona():
    """Mock active persona configuration"""
    return {
        "persona_id": 1,
        "persona_name": "Helpful Assistant",
        "system_prompt": "You are a helpful assistant...",
        "description": "A friendly and helpful chatbot persona",
        "is_active": True,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }


@pytest.fixture
def mock_human_agents_list():
    """Mock list of human agents"""
    return {
        "agents": [
            {
                "agent_id": 1,
                "email": "agent1@example.com",
                "name": "Agent One",
                "status": "available",
                "current_sessions": 2
            },
            {
                "agent_id": 2,
                "email": "agent2@example.com",
                "name": "Agent Two",
                "status": "busy",
                "current_sessions": 5
            }
        ]
    }


@pytest.fixture
def mock_admin_emails_list():
    """Mock list of admin emails"""
    return {
        "admins": [
            {
                "admin_id": 1,
                "email": "admin1@example.com",
                "name": "Admin One",
                "created_at": datetime.now().isoformat()
            },
            {
                "admin_id": 2,
                "email": "admin2@example.com",
                "name": "Admin Two",
                "created_at": datetime.now().isoformat()
            }
        ]
    }


# ============================================================================
# SERVICE MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_session_service():
    """Mock SessionService"""
    service = AsyncMock()
    service.create_session = AsyncMock(return_value="session-id-12345")
    service.get_session = AsyncMock(return_value={
        "uid": "firebase-uid-12345",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://example.com/avatar.jpg"
    })
    service.delete_session = AsyncMock(return_value=True)
    service.refresh_session = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_profile_service():
    """Mock ProfileService"""
    service = AsyncMock()
    service.fetch_user_profile = AsyncMock(return_value={
        "role": "admin",
        "roles": ["admin", "user"]
    })
    return service


@pytest.fixture
def mock_configuration_service():
    """Mock ConfigurationService"""
    service = AsyncMock()
    service.get_security_settings = AsyncMock(return_value={
        "setting_key": "max_login_attempts",
        "setting_value": "5"
    })
    service.get_llm_providers = AsyncMock(return_value={
        "providers": [
            {
                "provider_name": "OpenAI",
                "model": "gpt-4",
                "token_limit": 8000
            }
        ]
    })
    service.get_active_persona = AsyncMock(return_value={
        "persona_name": "Helpful Assistant",
        "system_prompt": "You are a helpful assistant..."
    })
    service.get_human_agents = AsyncMock(return_value={
        "agents": [
            {
                "email": "agent@example.com",
                "name": "Agent",
                "status": "available"
            }
        ]
    })
    service.get_admin_emails = AsyncMock(return_value={
        "admins": [
            {
                "email": "admin@example.com",
                "name": "Admin"
            }
        ]
    })
    return service


@pytest.fixture
def mock_auth_dao():
    """Mock AuthDAO"""
    dao = AsyncMock()
    dao.check_user_exists = AsyncMock(return_value={
        "user_id": 1,
        "email": "user@example.com",
        "name": "Test User"
    })
    dao.check_user_has_role = AsyncMock(return_value={
        "user_id": 1,
        "role_id": 1,
        "role_name": "admin"
    })
    dao.get_user_roles = AsyncMock(return_value=[
        {"role_id": 1, "role_name": "admin"},
        {"role_id": 2, "role_name": "user"}
    ])
    dao.get_admins = AsyncMock(return_value=[
        {"email": "admin1@example.com", "name": "Admin One"},
        {"email": "admin2@example.com", "name": "Admin Two"}
    ])
    dao.get_human_agents = AsyncMock(return_value=[
        {"email": "agent1@example.com", "name": "Agent One"},
        {"email": "agent2@example.com", "name": "Agent Two"}
    ])
    return dao


# ============================================================================
# REQUEST/RESPONSE FIXTURES
# ============================================================================

@pytest.fixture
def create_session_request():
    """Mock CreateSessionRequest"""
    return {
        "idToken": "firebase-id-token-12345",
        "context": "admin"
    }


@pytest.fixture
def create_session_request_widget():
    """Mock CreateSessionRequest for widget context"""
    return {
        "idToken": "firebase-id-token-12345",
        "context": "widget"
    }


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object"""
    request = MagicMock()
    request.headers = {
        "origin": "https://example.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    request.client.host = "192.168.1.1"
    request.cookies = {}
    return request


@pytest.fixture
def mock_response():
    """Mock FastAPI Response object"""
    response = MagicMock()
    response.set_cookie = MagicMock()
    response.delete_cookie = MagicMock()
    return response


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Mock database session"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_db_connection():
    """Mock database connection"""
    connection = AsyncMock()
    connection.execute = AsyncMock()
    connection.close = AsyncMock()
    return connection


# ============================================================================
# SETTINGS FIXTURES
# ============================================================================

@pytest.fixture
def mock_settings():
    """Mock application settings"""
    settings = MagicMock()
    settings.session_cookie_name = "session_id"
    settings.session_max_age = 86400  # 24 hours
    settings.session_domain = ".example.com"
    settings.allowed_origins = [
        "https://example.com",
        "https://app.example.com",
        "http://localhost:3000"
    ]
    settings.firebase_project_id = "test-project"
    settings.configuration_service_url = "http://localhost:8001"
    return settings


# ============================================================================
# CONTEXT MANAGERS
# ============================================================================

@pytest.fixture
def mock_firebase_auth_context(mock_firebase_user):
    """Mock Firebase authentication context"""
    with patch('api_gateway.core.firebase_auth.verify_firebase_token') as mock_verify:
        mock_verify.return_value = mock_firebase_user
        yield mock_verify


@pytest.fixture
def mock_settings_context(mock_settings):
    """Mock settings context"""
    with patch('api_gateway.core.config.get_settings') as mock_get_settings:
        mock_get_settings.return_value = mock_settings
        yield mock_get_settings


# ============================================================================
# PARAMETRIZED FIXTURES
# ============================================================================

@pytest.fixture(params=[
    {"role": "admin", "roles": ["admin", "user"]},
    {"role": "human_agent", "roles": ["human_agent", "user"]},
    {"role": "user", "roles": ["user"]}
])
def user_roles(request):
    """Parametrized fixture for different user roles"""
    return request.param


@pytest.fixture(params=[
    "admin",
    "widget"
])
def session_contexts(request):
    """Parametrized fixture for session contexts"""
    return request.param
