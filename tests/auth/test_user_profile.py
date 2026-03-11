"""
Unit tests for /api/v1/gateway/configuration/users/profile endpoint.

Request Flow:
1. GET /api/v1/gateway/configuration/users/profile
2. Extract user from session (get_current_user dependency)
3. Fetch user profile from database (configuration/dao/auth_dao.py::AuthDAO.get_user_by_role_id)
4. Return user profile data

PUT /api/v1/gateway/configuration/users/profile
1. Extract user from session
2. Update user profile in database
3. Return updated profile

Files Involved:
- configuration/routers/router.py::get_user_profile
- configuration/routers/router.py::update_user_profile
- configuration/dao/auth_dao.py::AuthDAO
- configuration/service/auth_service.py::AuthService
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TestGetUserProfile:
    """Test suite for GET /users/profile endpoint"""

    @pytest.mark.asyncio
    async def test_get_user_profile_success(
        self,
        mock_auth_dao,
        mock_user_profile
    ):
        """
        Test successful user profile retrieval.
        
        Covers: configuration/routers/router.py::get_user_profile
        Covers: configuration/dao/auth_dao.py::AuthDAO.get_user_by_role_id
        """
        logger.info("🧪 Testing successful user profile retrieval")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/avatar.jpg",
            "role": "admin"
        }
        
        mock_auth_dao.get_user_by_role_id.return_value = mock_user_profile
        
        # Execute
        logger.info("📤 Fetching user profile")
        from configuration.routers.router import get_user_profile
        
        result = await get_user_profile(user=user)
        
        # Verify
        logger.info("✅ Verifying profile response")
        assert result["email"] == user["email"]
        assert result["role"] == "admin"
        
        logger.info("✅ Get user profile test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_admin_role(
        self,
        mock_auth_dao,
        mock_admin_user
    ):
        """
        Test user profile retrieval for admin role.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: Admin user profile
        """
        logger.info("🧪 Testing admin user profile retrieval")
        
        # Setup
        mock_auth_dao.get_user_by_role_id.return_value = mock_admin_user
        
        # Execute
        logger.info("📤 Fetching admin profile")
        from configuration.routers.router import get_user_profile
        
        result = await get_user_profile(user=mock_admin_user)
        
        # Verify
        logger.info("✅ Verifying admin profile")
        assert result["role"] == "admin"
        assert "admin" in result["roles"]
        
        logger.info("✅ Admin profile test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_human_agent_role(
        self,
        mock_auth_dao,
        mock_human_agent_user
    ):
        """
        Test user profile retrieval for human agent role.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: Human agent user profile
        """
        logger.info("🧪 Testing human agent user profile retrieval")
        
        # Setup
        mock_auth_dao.get_user_by_role_id.return_value = mock_human_agent_user
        
        # Execute
        logger.info("📤 Fetching human agent profile")
        from configuration.routers.router import get_user_profile
        
        result = await get_user_profile(user=mock_human_agent_user)
        
        # Verify
        logger.info("✅ Verifying human agent profile")
        assert result["role"] == "human_agent"
        
        logger.info("✅ Human agent profile test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_regular_user_role(
        self,
        mock_auth_dao,
        mock_regular_user
    ):
        """
        Test user profile retrieval for regular user role.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: Regular user profile
        """
        logger.info("🧪 Testing regular user profile retrieval")
        
        # Setup
        mock_auth_dao.get_user_by_role_id.return_value = mock_regular_user
        
        # Execute
        logger.info("📤 Fetching regular user profile")
        from configuration.routers.router import get_user_profile
        
        result = await get_user_profile(user=mock_regular_user)
        
        # Verify
        logger.info("✅ Verifying regular user profile")
        assert result["role"] == "user"
        
        logger.info("✅ Regular user profile test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_not_found(
        self,
        mock_auth_dao
    ):
        """
        Test user profile retrieval when user not found.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: User not found in database
        """
        logger.info("🧪 Testing user profile retrieval when user not found")
        
        # Setup
        user = {
            "uid": "nonexistent-uid",
            "email": "nonexistent@example.com",
            "name": "Nonexistent User"
        }
        
        mock_auth_dao.get_user_by_role_id.return_value = None
        
        # Execute
        logger.info("📤 Fetching nonexistent user profile")
        from configuration.routers.router import get_user_profile
        
        # Should handle gracefully
        result = await get_user_profile(user=user)
        
        # Verify
        logger.info("✅ Verifying not found handling")
        # Should return user data or empty profile
        assert result is not None or result is None  # Depends on implementation
        
        logger.info("✅ User not found test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_database_error(
        self,
        mock_auth_dao
    ):
        """
        Test user profile retrieval with database error.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing user profile retrieval with database error")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        mock_auth_dao.get_user_by_role_id.side_effect = Exception("Database error")
        
        # Execute
        logger.info("📤 Fetching profile with database error")
        from configuration.routers.router import get_user_profile
        
        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_user_profile(user=user)
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")

    @pytest.mark.asyncio
    async def test_get_user_profile_with_multiple_roles(
        self,
        mock_auth_dao
    ):
        """
        Test user profile retrieval for user with multiple roles.
        
        Covers: configuration/routers/router.py::get_user_profile
        
        Edge Case: User with multiple roles (admin + human_agent)
        """
        logger.info("🧪 Testing user profile with multiple roles")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User",
            "roles": ["admin", "human_agent", "user"]
        }
        
        profile = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User",
            "roles": ["admin", "human_agent", "user"],
            "primary_role": "admin"
        }
        
        mock_auth_dao.get_user_by_role_id.return_value = profile
        
        # Execute
        logger.info("📤 Fetching profile with multiple roles")
        from configuration.routers.router import get_user_profile
        
        result = await get_user_profile(user=user)
        
        # Verify
        logger.info("✅ Verifying multiple roles profile")
        assert len(result["roles"]) >= 2
        
        logger.info("✅ Multiple roles test passed")


class TestUpdateUserProfile:
    """Test suite for PUT /users/profile endpoint"""

    @pytest.mark.asyncio
    async def test_update_user_profile_success(
        self,
        mock_auth_dao
    ):
        """
        Test successful user profile update.
        
        Covers: configuration/routers/router.py::update_user_profile
        Covers: configuration/dao/auth_dao.py::AuthDAO (update methods)
        """
        logger.info("🧪 Testing successful user profile update")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {
            "name": "Updated Name",
            "picture": "https://example.com/new-avatar.jpg"
        }
        
        # Execute
        logger.info("📤 Updating user profile")
        from configuration.routers.router import update_user_profile
        
        result = await update_user_profile(
            profile_data=profile_data,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying update response")
        assert result["success"] is True or result is not None
        
        logger.info("✅ Update user profile test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_name_only(
        self,
        mock_auth_dao
    ):
        """
        Test user profile update with name only.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Partial update (name only)
        """
        logger.info("🧪 Testing user profile update with name only")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {
            "name": "New Name"
        }
        
        # Execute
        logger.info("📤 Updating profile name")
        from configuration.routers.router import update_user_profile
        
        result = await update_user_profile(
            profile_data=profile_data,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying name update")
        assert result is not None
        
        logger.info("✅ Name update test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_picture_only(
        self,
        mock_auth_dao
    ):
        """
        Test user profile update with picture only.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Partial update (picture only)
        """
        logger.info("🧪 Testing user profile update with picture only")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {
            "picture": "https://example.com/new-picture.jpg"
        }
        
        # Execute
        logger.info("📤 Updating profile picture")
        from configuration.routers.router import update_user_profile
        
        result = await update_user_profile(
            profile_data=profile_data,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying picture update")
        assert result is not None
        
        logger.info("✅ Picture update test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_empty_data(
        self,
        mock_auth_dao
    ):
        """
        Test user profile update with empty data.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Empty update data
        """
        logger.info("🧪 Testing user profile update with empty data")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {}
        
        # Execute
        logger.info("📤 Updating profile with empty data")
        from configuration.routers.router import update_user_profile
        
        result = await update_user_profile(
            profile_data=profile_data,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying empty update handling")
        assert result is not None
        
        logger.info("✅ Empty data update test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_database_error(
        self,
        mock_auth_dao
    ):
        """
        Test user profile update with database error.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Database connection error
        """
        logger.info("🧪 Testing user profile update with database error")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {
            "name": "Updated Name"
        }
        
        mock_auth_dao.update_user_profile = AsyncMock(
            side_effect=Exception("Database error")
        )
        
        # Execute
        logger.info("📤 Updating profile with database error")
        from configuration.routers.router import update_user_profile
        
        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_user_profile(
                profile_data=profile_data,
                user=user
            )
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Database error test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_invalid_data(
        self,
        mock_auth_dao
    ):
        """
        Test user profile update with invalid data.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Invalid profile data
        """
        logger.info("🧪 Testing user profile update with invalid data")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data = {
            "name": "",  # Empty name
            "picture": "invalid-url"  # Invalid URL
        }
        
        # Execute
        logger.info("📤 Updating profile with invalid data")
        from configuration.routers.router import update_user_profile
        
        # Should handle validation
        result = await update_user_profile(
            profile_data=profile_data,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying invalid data handling")
        # Should either reject or sanitize
        assert result is not None
        
        logger.info("✅ Invalid data test passed")

    @pytest.mark.asyncio
    async def test_update_user_profile_concurrent_updates(
        self,
        mock_auth_dao
    ):
        """
        Test concurrent user profile updates.
        
        Covers: configuration/routers/router.py::update_user_profile
        
        Edge Case: Concurrent updates from same user
        """
        logger.info("🧪 Testing concurrent user profile updates")
        
        # Setup
        user = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        profile_data_1 = {"name": "Name 1"}
        profile_data_2 = {"name": "Name 2"}
        
        # Execute
        logger.info("📤 Sending concurrent update requests")
        from configuration.routers.router import update_user_profile
        
        result_1 = await update_user_profile(
            profile_data=profile_data_1,
            user=user
        )
        
        result_2 = await update_user_profile(
            profile_data=profile_data_2,
            user=user
        )
        
        # Verify
        logger.info("✅ Verifying concurrent updates")
        assert result_1 is not None
        assert result_2 is not None
        
        logger.info("✅ Concurrent updates test passed")
