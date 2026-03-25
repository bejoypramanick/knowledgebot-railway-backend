import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
from shared.kreuzberg_integration import process_with_kreuzberg

@pytest.fixture
def mock_httpx_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"content": "# Extracted Markdown", "metadata": {"pages": 1}}
    return response

@pytest.mark.asyncio
async def test_process_with_kreuzberg_success(mock_httpx_response):
    with patch("shared.kreuzberg_integration.download_file_from_s3", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = b"fake pdf bytes"
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_httpx_response
            
            markdown, metadata = await process_with_kreuzberg(
                "http://fake-s3-url.com/doc.pdf", 
                "doc.pdf", 
                "application/pdf"
            )
            
            assert markdown == "# Extracted Markdown"
            assert metadata["content_format"] == "markdown_kv"
            assert metadata["kreuzberg_metadata"] == {"pages": 1}

@pytest.mark.asyncio
async def test_process_with_kreuzberg_api_error():
    error_response = MagicMock()
    error_response.status_code = 500
    error_response.text = "Internal Server Error"
    
    with patch("shared.kreuzberg_integration.download_file_from_s3", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = b"fake pdf bytes"
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = error_response
            
            markdown, metadata = await process_with_kreuzberg(
                "http://error-url.com/doc.pdf", 
                "doc.pdf", 
                "application/pdf"
            )
            
            assert markdown is None
            assert "error" in metadata
            assert "API Error 500" in metadata["error"]

@pytest.mark.asyncio
async def test_process_with_kreuzberg_total_connection_failure():
    with patch("shared.kreuzberg_integration.download_file_from_s3", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = b"fake pdf bytes"
        
        # Mock perform_request which is local to process_with_kreuzberg is hard to patch directly.
        # Instead, patch httpx.AsyncClient.post to raise a connection error.
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused", request=MagicMock())) as mock_post:
            # We also need to prevent the decorator from retrying forever by mocking max_retries or similar if possible.
            # But here we just want to see if it reaches the AttributeError or not.
            # The decorator is @retry_on_connection_error(max_retries=10, delay=3.0)
            # This would take a while. Let's patch the decorator for this test if possible,
            # or just patch 'perform_request' by patching its definition? No.
            
            # Actually, let's just patch the decorator's 'max_retries' if we can? 
            # It's hard in Python without patching the module before import.
            
            # Better approach: verify that a single call to process_with_kreuzberg (without decorator) 
            # handles the None response.
            
            # I will patch the 'retry_on_connection_error' to be a no-op for this test.
            with patch("shared.kreuzberg_integration.retry_on_connection_error", lambda max_retries, delay: (lambda f: f)):
                # We need to re-import or reload? No, let's just verify the logic.
                
                # I'll just run it as is and check for the returned error.
                # To speed up, I'll patch the 'asyncio.sleep' to be zero.
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    markdown, metadata = await process_with_kreuzberg(
                        "http://invalid-url.com/doc.pdf", 
                        "doc.pdf", 
                        "application/pdf"
                    )
                    
                    assert markdown is None
                    assert "error" in metadata
                    assert "Connection refused" in metadata["error"]
                    
                    # If it didn't raise AttributeError, it passed the bug point.
                    assert mock_post.called

