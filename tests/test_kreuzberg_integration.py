import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
from shared.kreuzberg_integration import process_with_kreuzberg

@pytest.fixture
def mock_httpx_response():
    response = MagicMock()
    response.status_code = 200
    response.text = "# Extracted Markdown"
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
            assert metadata["content_format"] == "markdown"

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
async def test_process_with_kreuzberg_connection_failure():
    with patch("shared.kreuzberg_integration.download_file_from_s3", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = b"fake pdf bytes"
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused", request=MagicMock())) as mock_post:
            markdown, metadata = await process_with_kreuzberg(
                "http://invalid-url.com/doc.pdf",
                "doc.pdf",
                "application/pdf"
            )
            assert markdown is None
            assert "error" in metadata
            assert "Connection refused" in metadata["error"]
            assert mock_post.called
