"""
Unit tests for token tracking functionality
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the functions we want to test
from shared.token_tracker import (TokenUsageData, get_token_service, log_async,
                                  track_gemini_usage,
                                  track_gemini_usage_detailed,
                                  track_gemini_usage_from_response,
                                  track_gemini_usage_with_db,
                                  track_token_usage)


class TestTokenTracker:
    """Test suite for token tracking functions"""
    
    @pytest.fixture
    def mock_token_service(self):
        """Mock TokenUsageService for testing"""
        service = Mock()
        service.track_token_usage = AsyncMock()
        return service
    
    @pytest.fixture
    def sample_usage_data(self):
        """Sample token usage data for testing"""
        return TokenUsageData(
            session_id="test-session-123",
            message_id="test-message-456",
            provider="gemini",
            model="gemini-2.5-flash-lite",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cache_read_tokens=10,
            cache_write_tokens=5,
            api_call_type="rag"
        )
    
    @pytest.mark.asyncio
    async def test_track_token_usage_success(self, mock_token_service):
        """Test successful token tracking"""
        with patch('shared.token_tracker.get_token_service', return_value=mock_token_service):
            result = await track_token_usage(
                session_id="test-session",
                message_id="test-message",
                provider="gemini",
                model="gemini-2.5-flash-lite",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                api_call_type="rag"
            )
            
            assert result is True
            mock_token_service.track_token_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_track_token_usage_invalid_input(self):
        """Test token tracking with invalid input"""
        result = await track_token_usage(
            session_id="test-session",
            message_id="test-message",
            provider="gemini",
            model="gemini-2.5-flash-lite",
            prompt_tokens=-1,  # Invalid negative tokens
            completion_tokens=50,
            total_tokens=150,
            api_call_type="rag"
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_success(self):
        """Test Gemini usage tracking"""
        with patch('shared.token_tracker.track_gemini_usage_detailed', return_value=True) as mock_detailed:
            result = await track_gemini_usage(
                prompt_tokens=100,
                candidates_tokens=50,
                session_id="test-session",
                message_id="test-message"
            )
            
            assert result is True
            mock_detailed.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_detailed_success(self, mock_token_service):
        """Test detailed Gemini usage tracking"""
        with patch('shared.token_tracker.get_token_service', return_value=mock_token_service):
            result = await track_gemini_usage_detailed(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cache_read_tokens=10,
                cache_write_tokens=5,
                session_id="test-session",
                message_id="test-message"
            )
            
            assert result is True
            mock_token_service.track_token_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_detailed_no_tokens(self):
        """Test detailed tracking with zero tokens"""
        result = await track_gemini_usage_detailed(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            session_id="test-session"
        )
        
        assert result is True  # Should return True, not False (nothing to track is not an error)
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_from_response_success(self, mock_token_service):
        """Test tracking from Gemini response object"""
        # Mock usage object
        mock_usage = Mock()
        mock_usage.promptTokenCount = 100
        mock_usage.candidatesTokenCount = 50
        mock_usage.totalTokenCount = 150
        
        with patch('shared.token_tracker.get_token_service', return_value=mock_token_service):
            result = await track_gemini_usage_from_response(
                usage_obj=mock_usage,
                session_id="test-session",
                message_id="test-message"
            )
            
            assert result is True
            mock_token_service.track_token_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_from_response_none_object(self):
        """Test tracking with None usage object"""
        result = await track_gemini_usage_from_response(
            usage_obj=None,
            session_id="test-session"
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_track_gemini_usage_with_db_success(self, mock_token_service):
        """Test tracking with database connection"""
        mock_run_usage = Mock()
        mock_run_usage.input_tokens = 100
        mock_run_usage.output_tokens = 50
        mock_run_usage.details = {
            'accepted_prediction_tokens': 10,
            'rejected_prediction_tokens': 5
        }
        
        with patch('shared.token_tracker.get_token_service', return_value=mock_token_service):
            result = await track_gemini_usage_with_db(
                run_usage=mock_run_usage,
                session_id="test-session",
                message_id="test-message"
            )
            
            assert result is True
            mock_token_service.track_token_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_log_async_info(self):
        """Test async info logging"""
        with patch('shared.token_tracker.logger') as mock_logger:
            await log_async("Test info message", "info")
            mock_logger.info.assert_called_once_with("Test info message")
    
    @pytest.mark_asyncio
    async def test_log_async_error(self):
        """Test async error logging"""
        with patch('shared.token_tracker.logger') as mock_logger:
            await log_async("Test error message", "error")
            mock_logger.error.assert_called_once_with("Test error message")
    
    @pytest.mark.asyncio
    async def test_log_async_failure_handling(self):
        """Test that logging failures don't break main function"""
        with patch('shared.token_tracker.logger', side_effect=Exception("Logging failed")):
            # Should not raise an exception
            await log_async("Test message", "info")
    
    def test_get_token_service_singleton(self):
        """Test that get_token_service returns singleton instance"""
        service1 = get_token_service()
        service2 = get_token_service()
        
        # Should be the same instance
        assert service1 is service2
    
    def test_token_usage_data_dataclass(self, sample_usage_data):
        """Test TokenUsageData dataclass functionality"""
        assert sample_usage_data.session_id == "test-session-123"
        assert sample_usage_data.prompt_tokens == 100
        assert sample_usage_data.total_tokens == 150
        
        # Test default values
        default_data = TokenUsageData()
        assert default_data.provider == "gemini"
        assert default_data.model == "gemini-2.5-flash-lite"
        assert default_data.prompt_tokens == 0


class TestTokenTrackerIntegration:
    """Integration tests for token tracking"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_token_tracking(self):
        """Test complete token tracking flow"""
        # This would test the actual integration with real services
        # For now, we'll mock the service layer
        with patch('shared.token_tracker.get_token_service') as mock_get_service:
            mock_service = Mock()
            mock_service.track_token_usage = AsyncMock()
            mock_get_service.return_value = mock_service
            
            # Track usage through different methods
            result1 = await track_token_usage(
                session_id="session-1",
                message_id="message-1",
                provider="gemini",
                model="gemini-2.5-flash-lite",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                api_call_type="rag"
            )
            
            result2 = await track_gemini_usage(
                prompt_tokens=200,
                candidates_tokens=100,
                session_id="session-2",
                message_id="message-2"
            )
            
            assert result1 is True
            assert result2 is True
            assert mock_service.track_token_usage.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__])
