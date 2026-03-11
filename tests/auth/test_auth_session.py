"""
Unit tests for /api/v1/gateway/auth/session endpoint.

Request Flow:
1. POST /api/v1/gateway/auth/session
2. Verify Firebase ID token (api_gateway/core/firebase_auth.py::verify_firebase_token)
3. Fetch user profile (api_gateway/services/profile_service.py::ProfileService.fetch_user_profile)
4. Create session (api_gateway/services/session_service.py::SessionService.create_session)
5. Set secure cookie with context-appropriate SameSite policy
6. Return user data

Files Involved:
- api_gateway/routers/auth_router.py::create_session_endpoint
- api_gateway/services/profile_service.py::ProfileService
- api_gateway/services/session_service.py::SessionService
- api_gateway/core/firebase_auth.py::verify_firebase_token
- configuration/dao/auth_dao.py::AuthDAO
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TestAuthSessionCreation:
    """Test suite for session creation endpoint"""

    @pytest.mark.asyncio
    async def test_create_session_success_admin_context(
        self,
        mock_firebase_user,
        mock_user_profile,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test successful session creation for admin context.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        Covers: api_gateway/services/profile_service.py::ProfileService.fetch_user_profile
        Covers: api_gateway/services/session_service.py::SessionService.create_session
        
        Edge Case: Admin context with SameSite=Lax
        """
        logger.info("🧪 Testing successful session creation (admin context)")
        
        # Setup
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = mock_user_profile
        mock_session_service.create_session.return_value = "session-id-12345"
        
        # Import after mocking
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute
        logger.info("📤 Sending session creation request")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify
        logger.info("✅ Verifying session creation response")
        assert result["success"] is True
        assert result["user"]["email"] == mock_firebase_user["email"]
        assert result["user"]["uid"] == mock_firebase_user["uid"]
        
        # Verify cookie was set with correct SameSite policy
        mock_response.set_cookie.assert_called_once()
        call_kwargs = mock_response.set_cookie.call_args[1]
        assert call_kwargs["samesite"] == "lax"
        assert call_kwargs["httponly"] is True
        assert call_kwargs["secure"] is True
        
        logger.info("✅ Session creation test passed")

    @pytest.mark.asyncio
    async def test_create_session_success_widget_context(
        self,
        mock_firebase_user,
        mock_user_profile,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test successful session creation for widget context.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        
        Edge Case: Widget context with SameSite=None (cross-origin)
        """
        logger.info("🧪 Testing successful session creation (widget context)")
        
        # Setup
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = mock_user_profile
        mock_session_service.create_session.return_value = "session-id-12345"
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "widget"
        }
        
        # Execute
        logger.info("📤 Sending widget session creation request")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify
        logger.info("✅ Verifying widget session response")
        assert result["success"] is True
        
        # Verify cookie was set with SameSite=None for cross-origin
        call_kwargs = mock_response.set_cookie.call_args[1]
        assert call_kwargs["samesite"] == "none"
        
        logger.info("✅ Widget session creation test passed")

    @pytest.mark.asyncio
    async def test_create_session_invalid_firebase_token(
        self,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test session creation with invalid Firebase token.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        
        Edge Case: Invalid/expired Firebase token
        """
        logger.info("🧪 Testing session creation with invalid Firebase token")
        
        # Setup - Firebase verification fails
        mock_firebase_auth_context.return_value = None
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "invalid-token",
            "context": "admin"
        }
        
        # Execute & Verify
        logger.info("📤 Sending request with invalid token")
        with pytest.raises(HTTPException) as exc_info:
            await create_session_endpoint(
                request=request_data,
                response=mock_response,
                req=mock_request,
                session_service=mock_session_service,
                profile_service=mock_profile_service
            )
        
        assert exc_info.value.status_code == 401
        logger.info("✅ Invalid token test passed")

    @pytest.mark.asyncio
    async def test_create_session_profile_fetch_failure_fallback(
        self,
        mock_firebase_user,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test session creation when profile fetch fails (fallback to default role).
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        Covers: api_gateway/services/profile_service.py::ProfileService.fetch_user_profile
        
        Edge Case: Profile service unavailable - should use fallback role
        """
        logger.info("🧪 Testing session creation with profile fetch failure")
        
        # Setup
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.side_effect = Exception("Service unavailable")
        mock_session_service.create_session.return_value = "session-id-12345"
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute
        logger.info("📤 Sending request with profile service failure")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify - should still succeed with fallback role
        logger.info("✅ Verifying fallback behavior")
        assert result["success"] is True
        assert result["user"]["email"] == mock_firebase_user["email"]
        
        logger.info("✅ Profile fetch failure fallback test passed")

    @pytest.mark.asyncio
    async def test_create_session_csrf_protection_invalid_origin(
        self,
        mock_firebase_user,
        mock_session_service,
        mock_profile_service,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test CSRF protection - reject invalid origin.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        
        Edge Case: CSRF attack with invalid origin
        """
        logger.info("🧪 Testing CSRF protection with invalid origin")
        
        # Setup - invalid origin
        mock_request = MagicMock()
        mock_request.headers = {
            "origin": "https://malicious.com",
            "user-agent": "Mozilla/5.0"
        }
        mock_request.client.host = "192.168.1.1"
        
        mock_firebase_auth_context.return_value = mock_firebase_user
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute & Verify
        logger.info("📤 Sending request from malicious origin")
        with pytest.raises(HTTPException) as exc_info:
            await create_session_endpoint(
                request=request_data,
                response=mock_response,
                req=mock_request,
                session_service=mock_session_service,
                profile_service=mock_profile_service
            )
        
        assert exc_info.value.status_code == 403
        logger.info("✅ CSRF protection test passed")

    @pytest.mark.asyncio
    async def test_create_session_security_binding(
        self,
        mock_firebase_user,
        mock_user_profile,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test session security binding (IP and User-Agent).
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        Covers: api_gateway/services/session_service.py::SessionService.create_session
        
        Edge Case: Session binding to IP and User-Agent for hijacking detection
        """
        logger.info("🧪 Testing session security binding")
        
        # Setup
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = mock_user_profile
        mock_session_service.create_session.return_value = "session-id-12345"
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute
        logger.info("📤 Sending session creation request")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify - session service should be called with IP and User-Agent
        logger.info("✅ Verifying security binding parameters")
        mock_session_service.create_session.assert_called_once()
        call_args = mock_session_service.create_session.call_args
        
        # Check that IP and User-Agent were passed
        assert call_args[0][1] == mock_request.client.host  # IP
        assert call_args[0][2] == mock_request.headers.get("user-agent")  # User-Agent
        
        logger.info("✅ Security binding test passed")

    @pytest.mark.asyncio
    async def test_create_session_with_different_user_roles(
        self,
        mock_firebase_user,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context,
        user_roles
    ):
        """
        Test session creation with different user roles.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        
        Edge Cases: Admin, Human Agent, Regular User roles
        """
        logger.info(f"🧪 Testing session creation with role: {user_roles['role']}")
        
        # Setup
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = user_roles
        mock_session_service.create_session.return_value = "session-id-12345"
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute
        logger.info(f"📤 Sending session creation request for {user_roles['role']}")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify
        logger.info(f"✅ Verifying session creation for {user_roles['role']}")
        assert result["success"] is True
        
        logger.info(f"✅ Session creation test passed for role: {user_roles['role']}")

    @pytest.mark.asyncio
    async def test_create_session_missing_ip_address(
        self,
        mock_firebase_user,
        mock_user_profile,
        mock_session_service,
        mock_profile_service,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test session creation when client IP is not available.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        
        Edge Case: Request without client IP (None)
        """
        logger.info("🧪 Testing session creation without client IP")
        
        # Setup - no client IP
        mock_request = MagicMock()
        mock_request.headers = {
            "origin": "https://example.com",
            "user-agent": "Mozilla/5.0"
        }
        mock_request.client = None  # No client info
        
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = mock_user_profile
        mock_session_service.create_session.return_value = "session-id-12345"
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute
        logger.info("📤 Sending request without client IP")
        result = await create_session_endpoint(
            request=request_data,
            response=mock_response,
            req=mock_request,
            session_service=mock_session_service,
            profile_service=mock_profile_service
        )
        
        # Verify - should still succeed
        logger.info("✅ Verifying session creation without IP")
        assert result["success"] is True
        
        logger.info("✅ Missing IP test passed")

    @pytest.mark.asyncio
    async def test_create_session_service_error(
        self,
        mock_firebase_user,
        mock_user_profile,
        mock_session_service,
        mock_profile_service,
        mock_request,
        mock_response,
        mock_settings_context,
        mock_firebase_auth_context
    ):
        """
        Test session creation when session service fails.
        
        Covers: api_gateway/routers/auth_router.py::create_session_endpoint
        Covers: api_gateway/services/session_service.py::SessionService.create_session
        
        Edge Case: Session service error
        """
        logger.info("🧪 Testing session creation with service error")
        
        # Setup - session service fails
        mock_firebase_auth_context.return_value = mock_firebase_user
        mock_profile_service.fetch_user_profile.return_value = mock_user_profile
        mock_session_service.create_session.side_effect = Exception("Database error")
        
        from api_gateway.routers.auth_router import create_session_endpoint
        
        request_data = {
            "idToken": "firebase-id-token-12345",
            "context": "admin"
        }
        
        # Execute & Verify
        logger.info("📤 Sending request with service error")
        with pytest.raises(HTTPException) as exc_info:
            await create_session_endpoint(
                request=request_data,
                response=mock_response,
                req=mock_request,
                session_service=mock_session_service,
                profile_service=mock_profile_service
            )
        
        assert exc_info.value.status_code == 500
        logger.info("✅ Service error test passed")


class TestAuthSessionLogout:
    """Test suite for logout endpoint"""

    @pytest.mark.asyncio
    async def test_logout_success(
        self,
        mock_session_service,
        mock_request,
        mock_response,
        mock_settings_context
    ):
        """
        Test successful logout.
        
        Covers: api_gateway/routers/auth_router.py::logout
        Covers: api_gateway/services/session_service.py::SessionService.delete_session
        """
        logger.info("🧪 Testing successful logout")
        
        # Setup
        mock_request.cookies = {"session_id": "session-id-12345"}
        mock_session_service.delete_session.return_value = True
        
        from api_gateway.routers.auth_router import logout
        
        # Execute
        logger.info("📤 Sending logout request")
        result = await logout(
            request=mock_request,
            response=mock_response,
            session_service=mock_session_service
        )
        
        # Verify
        logger.info("✅ Verifying logout response")
        assert result["success"] is True
        mock_response.delete_cookie.assert_called_once()
        
        logger.info("✅ Logout test passed")

    @pytest.mark.asyncio
    async def test_logout_no_session_cookie(
        self,
        mock_session_service,
        mock_response,
        mock_settings_context
    ):
        """
        Test logout when no session cookie exists.
        
        Covers: api_gateway/routers/auth_router.py::logout
        
        Edge Case: Logout without active session
        """
        logger.info("🧪 Testing logout without session cookie")
        
        # Setup - no session cookie
        mock_request = MagicMock()
        mock_request.cookies = {}
        
        from api_gateway.routers.auth_router import logout
        
        # Execute
        logger.info("📤 Sending logout request without session")
        result = await logout(
            request=mock_request,
            response=mock_response,
            session_service=mock_session_service
        )
        
        # Verify - should still succeed
        logger.info("✅ Verifying logout without session")
        assert result["success"] is True
        mock_response.delete_cookie.assert_called_once()
        
        logger.info("✅ Logout without session test passed")


class TestAuthSessionRefresh:
    """Test suite for session refresh endpoint"""

    @pytest.mark.asyncio
    async def test_refresh_session_success(
        self,
        mock_session_service,
        mock_request,
        mock_response,
        mock_settings_context
    ):
        """
        Test successful session refresh.
        
        Covers: api_gateway/routers/auth_router.py::refresh_session
        Covers: api_gateway/services/session_service.py::SessionService.refresh_session
        """
        logger.info("🧪 Testing successful session refresh")
        
        # Setup
        mock_request.cookies = {"session_id": "session-id-12345"}
        mock_session_service.refresh_session.return_value = True
        
        from api_gateway.routers.auth_router import refresh_session
        
        # Execute
        logger.info("📤 Sending session refresh request")
        result = await refresh_session(
            request=mock_request,
            response=mock_response,
            session_service=mock_session_service
        )
        
        # Verify
        logger.info("✅ Verifying refresh response")
        assert result["success"] is True
        mock_response.set_cookie.assert_called_once()
        
        logger.info("✅ Session refresh test passed")

    @pytest.mark.asyncio
    async def test_refresh_session_invalid_session(
        self,
        mock_session_service,
        mock_request,
        mock_response,
        mock_settings_context
    ):
        """
        Test session refresh with invalid session.
        
        Covers: api_gateway/routers/auth_router.py::refresh_session
        
        Edge Case: Invalid or expired session
        """
        logger.info("🧪 Testing session refresh with invalid session")
        
        # Setup
        mock_request.cookies = {"session_id": "invalid-session"}
        mock_session_service.refresh_session.return_value = False
        
        from api_gateway.routers.auth_router import refresh_session
        
        # Execute & Verify
        logger.info("📤 Sending refresh request with invalid session")
        with pytest.raises(HTTPException) as exc_info:
            await refresh_session(
                request=mock_request,
                response=mock_response,
                session_service=mock_session_service
            )
        
        assert exc_info.value.status_code == 401
        logger.info("✅ Invalid session refresh test passed")


class TestAuthGetCurrentUser:
    """Test suite for get current user endpoint"""

    @pytest.mark.asyncio
    async def test_get_current_user_success(
        self,
        mock_session_service,
        mock_request,
        mock_settings_context
    ):
        """
        Test successful get current user.
        
        Covers: api_gateway/routers/auth_router.py::get_current_user
        Covers: api_gateway/services/session_service.py::SessionService.get_session
        """
        logger.info("🧪 Testing get current user success")
        
        # Setup
        mock_request.cookies = {"session_id": "session-id-12345"}
        mock_request.client.host = "192.168.1.1"
        mock_request.headers = {"user-agent": "Mozilla/5.0"}
        
        mock_session_service.get_session.return_value = {
            "uid": "firebase-uid-12345",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/avatar.jpg"
        }
        
        from api_gateway.routers.auth_router import get_current_user
        
        # Execute
        logger.info("📤 Sending get current user request")
        result = await get_current_user(
            request=mock_request,
            session_service=mock_session_service
        )
        
        # Verify
        logger.info("✅ Verifying current user response")
        assert result["success"] is True
        assert result["user"]["email"] == "user@example.com"
        
        logger.info("✅ Get current user test passed")

    @pytest.mark.asyncio
    async def test_get_current_user_not_authenticated(
        self,
        mock_session_service,
        mock_settings_context
    ):
        """
        Test get current user when not authenticated.
        
        Covers: api_gateway/routers/auth_router.py::get_current_user
        
        Edge Case: No session cookie
        """
        logger.info("🧪 Testing get current user without authentication")
        
        # Setup - no session cookie
        mock_request = MagicMock()
        mock_request.cookies = {}
        
        from api_gateway.routers.auth_router import get_current_user
        
        # Execute & Verify
        logger.info("📤 Sending request without session")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                session_service=mock_session_service
            )
        
        assert exc_info.value.status_code == 401
        logger.info("✅ Not authenticated test passed")

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_session(
        self,
        mock_session_service,
        mock_request,
        mock_settings_context
    ):
        """
        Test get current user with invalid session.
        
        Covers: api_gateway/routers/auth_router.py::get_current_user
        
        Edge Case: Invalid or expired session
        """
        logger.info("🧪 Testing get current user with invalid session")
        
        # Setup
        mock_request.cookies = {"session_id": "invalid-session"}
        mock_session_service.get_session.return_value = None
        
        from api_gateway.routers.auth_router import get_current_user
        
        # Execute & Verify
        logger.info("📤 Sending request with invalid session")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=mock_request,
                session_service=mock_session_service
            )
        
        assert exc_info.value.status_code == 401
        logger.info("✅ Invalid session test passed")
