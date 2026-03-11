"""
Pytest configuration and fixtures for API tests
Provides database setup, async test support, and mock services
"""
import pytest
import asyncio
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create test database session"""
    # Use in-memory SQLite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    # Create tables
    async with engine.begin() as conn:
        # Create minimal schema for testing
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS security_settings (
                id INTEGER PRIMARY KEY,
                setting_name TEXT UNIQUE,
                setting_value TEXT,
                setting_type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_providers (
                id INTEGER PRIMARY KEY,
                provider_name TEXT UNIQUE,
                token_limit INTEGER,
                token_used INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS persona_configurations (
                id INTEGER PRIMARY KEY,
                persona_name TEXT UNIQUE,
                persona_description TEXT,
                system_prompt TEXT,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY,
                role_name TEXT UNIQUE
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_role_mapping (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                role_id INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (role_id) REFERENCES roles(id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS widget_config (
                id INTEGER PRIMARY KEY,
                hil_enabled BOOLEAN DEFAULT FALSE,
                response_policy INTEGER DEFAULT 30,
                hil_disabled_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    async with async_session() as session:
        yield session
    
    await engine.dispose()


@pytest.fixture
def mock_logger():
    """Create mock logger"""
    return MagicMock()


@pytest.fixture
def mock_otel_logger():
    """Create mock OTEL logger"""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.error = MagicMock()
    logger.warning = MagicMock()
    logger.debug = MagicMock()
    return logger


@pytest.fixture
def mock_firebase_auth():
    """Mock Firebase authentication"""
    with patch('api_gateway.core.firebase_auth.verify_firebase_token') as mock:
        mock.return_value = {
            'uid': 'test-uid-123',
            'email': 'test@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/photo.jpg'
        }
        yield mock


@pytest.fixture
def mock_session_service():
    """Mock session service"""
    service = AsyncMock()
    service.create_session = MagicMock(return_value='session-id-123')
    service.get_session = AsyncMock(return_value={
        'uid': 'test-uid-123',
        'email': 'test@example.com',
        'name': 'Test User',
        'picture': 'https://example.com/photo.jpg'
    })
    service.delete_session = AsyncMock(return_value=True)
    service.refresh_session = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_profile_service():
    """Mock profile service"""
    service = AsyncMock()
    service.fetch_user_profile = AsyncMock(return_value={
        'role': 'user',
        'roles': ['user']
    })
    return service


@pytest.fixture
def mock_auth_service():
    """Mock auth service"""
    service = AsyncMock()
    service.get_user_role = AsyncMock(return_value={
        'roles': ['user']
    })
    return service


@pytest.fixture
def mock_settings():
    """Mock application settings"""
    settings = MagicMock()
    settings.session_cookie_name = 'session_id'
    settings.session_max_age = 86400
    settings.session_domain = 'localhost'
    settings.allowed_origins = ['http://localhost:3000', 'https://example.com']
    return settings
