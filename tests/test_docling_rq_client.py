"""Unit tests for docling_rq_client."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from shared.docling_rq_client import DoclingRQClient


@pytest.fixture
def mock_redis():
    """Mock Redis connection."""
    with patch('shared.docling_rq_client.Redis') as mock:
        yield mock


@pytest.fixture
def mock_queue():
    """Mock RQ Queue."""
    with patch('shared.docling_rq_client.Queue') as mock:
        yield mock


@pytest.mark.asyncio
async def test_enqueue_document(mock_redis, mock_queue):
    """Test job enqueuing to Redis Queue."""
    # Setup mocks
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    mock_queue_instance = Mock()
    mock_job = Mock()
    mock_job.id = "test-job-123"
    mock_queue_instance.enqueue.return_value = mock_job
    mock_queue.return_value = mock_queue_instance

    # Create client
    client = DoclingRQClient("redis://localhost:6379/0")

    # Test enqueue
    job_id = await client.enqueue_document(
        "https://s3.example.com/file.pdf",
        "test.pdf",
        "application/pdf"
    )

    assert job_id == "test-job-123"
    mock_queue_instance.enqueue.assert_called_once()
    call_args = mock_queue_instance.enqueue.call_args
    assert call_args[1]["job_timeout"] == "30m"
    assert call_args[1]["result_ttl"] == 14400


@pytest.mark.asyncio
async def test_enqueue_document_failure(mock_redis, mock_queue):
    """Test enqueue failure handling."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    mock_queue_instance = Mock()
    mock_queue_instance.enqueue.side_effect = Exception("Redis error")
    mock_queue.return_value = mock_queue_instance

    client = DoclingRQClient("redis://localhost:6379/0")

    with pytest.raises(Exception, match="Redis error"):
        await client.enqueue_document(
            "https://s3.example.com/file.pdf",
            "test.pdf",
            "application/pdf"
        )


@pytest.mark.asyncio
async def test_poll_job_success(mock_redis):
    """Test polling for successful job completion."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    # Mock successful job
    mock_job = Mock()
    mock_job.is_finished = True
    mock_job.is_failed = False
    mock_job.result = {
        "markdown": "# Test Document\nContent here",
        "metadata": {
            "processing_time_ms": 5000,
            "images_extracted": 2,
            "content_format": "markdown"
        }
    }

    with patch('shared.docling_rq_client.Job.fetch', return_value=mock_job):
        client = DoclingRQClient("redis://localhost:6379/0")
        markdown, metadata = await client.poll_job_result("test-job-123", timeout=10)

        assert markdown == "# Test Document\nContent here"
        assert metadata["processing_time_ms"] == 5000
        assert metadata["images_extracted"] == 2


@pytest.mark.asyncio
async def test_poll_job_failed(mock_redis):
    """Test polling for failed job."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    # Mock failed job
    mock_job = Mock()
    mock_job.is_finished = False
    mock_job.is_failed = True
    mock_job.exc_info = "Processing error: Invalid PDF format"

    with patch('shared.docling_rq_client.Job.fetch', return_value=mock_job):
        client = DoclingRQClient("redis://localhost:6379/0")

        with pytest.raises(Exception, match="Processing error"):
            await client.poll_job_result("test-job-123", timeout=10)


@pytest.mark.asyncio
async def test_poll_job_timeout(mock_redis):
    """Test timeout handling during polling."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    # Mock job that never completes
    mock_job = Mock()
    mock_job.is_finished = False
    mock_job.is_failed = False

    with patch('shared.docling_rq_client.Job.fetch', return_value=mock_job):
        client = DoclingRQClient("redis://localhost:6379/0")

        with pytest.raises(TimeoutError, match="timeout after 1s"):
            await client.poll_job_result("test-job-123", timeout=1, poll_interval_initial=0.1)


@pytest.mark.asyncio
async def test_process_document_async_success(mock_redis, mock_queue):
    """Test end-to-end document processing."""
    # Setup mock Redis and Queue
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    mock_queue_instance = Mock()
    mock_job = Mock()
    mock_job.id = "test-job-456"
    mock_queue_instance.enqueue.return_value = mock_job
    mock_queue.return_value = mock_queue_instance

    # Mock successful job completion
    mock_completed_job = Mock()
    mock_completed_job.is_finished = True
    mock_completed_job.is_failed = False
    mock_completed_job.result = {
        "markdown": "# Processed Document",
        "metadata": {"processing_time_ms": 3000}
    }

    with patch('shared.docling_rq_client.Job.fetch', return_value=mock_completed_job):
        client = DoclingRQClient("redis://localhost:6379/0")
        markdown, metadata = await client.process_document_async(
            "https://s3.example.com/file.pdf",
            "test.pdf",
            "application/pdf",
            timeout_seconds=30
        )

        assert markdown == "# Processed Document"
        assert metadata["processing_time_ms"] == 3000


@pytest.mark.asyncio
async def test_process_document_async_error(mock_redis, mock_queue):
    """Test error handling in end-to-end flow."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    mock_queue_instance = Mock()
    mock_queue_instance.enqueue.side_effect = Exception("Enqueue failed")
    mock_queue.return_value = mock_queue_instance

    client = DoclingRQClient("redis://localhost:6379/0")

    with pytest.raises(Exception, match="Enqueue failed"):
        await client.process_document_async(
            "https://s3.example.com/file.pdf",
            "test.pdf",
            "application/pdf"
        )


@pytest.mark.asyncio
async def test_poll_job_exponential_backoff(mock_redis):
    """Test exponential backoff in polling."""
    mock_redis_instance = Mock()
    mock_redis.from_url.return_value = mock_redis_instance

    # First call - job still processing
    # Second call - job still processing
    # Third call - job finished
    mock_job_processing = Mock()
    mock_job_processing.is_finished = False
    mock_job_processing.is_failed = False

    mock_job_finished = Mock()
    mock_job_finished.is_finished = True
    mock_job_finished.is_failed = False
    mock_job_finished.result = {"markdown": "Done", "metadata": {}}

    call_count = 0
    def fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return mock_job_processing
        return mock_job_finished

    with patch('shared.docling_rq_client.Job.fetch', side_effect=fetch_side_effect):
        client = DoclingRQClient("redis://localhost:6379/0")
        markdown, metadata = await client.poll_job_result(
            "test-job-123",
            timeout=60,
            poll_interval_initial=0.1,
            poll_interval_max=0.5
        )

        assert markdown == "Done"
        assert call_count == 3
