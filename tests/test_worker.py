import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.worker import WorkerThread, WorkerStats
from src.core.horde_api import HordeJob

@pytest.fixture
def mock_horde():
    h = MagicMock()
    h.pop_job = AsyncMock()
    h.submit_job = AsyncMock()
    h.submit_error = AsyncMock()
    return h

@pytest.fixture
def mock_backend():
    b = MagicMock()
    b.generate = AsyncMock()
    b.supports_format_flags = False
    return b

@pytest.fixture
def mock_health():
    h = MagicMock()
    h.backend_healthy = asyncio.Event()
    h.backend_healthy.set()
    return h

@pytest.fixture
def mock_config():
    c = MagicMock()
    c.worker.max_threads = 1
    c.worker.max_length = 512
    c.worker.max_context_length = 2048
    c.worker.blacklist = []
    c.resilience.backend_timeout = 30
    return c

@pytest.mark.asyncio
async def test_worker_stats():
    stats = WorkerStats()
    stats.add_job(tokens=10, kudos=20.0, duration=1.0)
    assert stats.jobs_count == 1
    assert stats.total_tokens == 10
    assert stats.total_kudos == 20.0
    assert stats.avg_generation_time == 1.0
    
    stats.add_job(tokens=10, kudos=20.0, duration=2.0)
    # Rolling average: 1.0 * 0.9 + 2.0 * 0.1 = 0.9 + 0.2 = 1.1
    assert stats.avg_generation_time == pytest.approx(1.1)

@pytest.mark.asyncio
async def test_worker_thread_single_job(mock_horde, mock_backend, mock_health, mock_config):
    stats = WorkerStats()
    shutdown = asyncio.Event()
    
    worker = WorkerThread(0, mock_horde, mock_backend, mock_config, stats, mock_health, shutdown)
    
    # 1. Provide a job
    job = HordeJob("job1", "Hello", params={}, model="model1")
    mock_horde.pop_job.side_effect = [job, None] # One job then empty
    
    # 2. Provide a generation result
    mock_backend.generate.return_value = MagicMock(text="World", token_count=5)
    mock_horde.submit_job.return_value = 10.0
    
    # Run the loop until next pop attempt
    task = asyncio.create_task(worker.run())
    
    # Wait until one job is processed
    while stats.jobs_count < 1:
        await asyncio.sleep(0.1)
    
    # Stop the worker
    shutdown.set()
    await task
    
    assert stats.jobs_count == 1
    mock_horde.submit_job.assert_called_with(
        job_id="job1", text="World", seed=None, token_count=5
    )

@pytest.mark.asyncio
async def test_worker_thread_skip_job(mock_horde, mock_backend, mock_health, mock_config):
    stats = WorkerStats()
    shutdown = asyncio.Event()
    mock_config.worker.blacklist = ["skipme"]
    
    worker = WorkerThread(0, mock_horde, mock_backend, mock_config, stats, mock_health, shutdown)
    
    # 1. Provide a job that should be skipped
    job = HordeJob("job1", "Please skipme", params={}, model="model1")
    mock_horde.pop_job.side_effect = [job, None]
    
    # Run loop
    task = asyncio.create_task(worker.run())
    
    # Wait for the pop attempt
    await asyncio.sleep(0.5)
    
    shutdown.set()
    await task
    
    # Should be skipped, no generation, no submission
    assert stats.jobs_count == 0
    mock_backend.generate.assert_not_called()
    mock_horde.submit_job.assert_not_called()

@pytest.mark.asyncio
async def test_worker_thread_error_reporting(mock_horde, mock_backend, mock_health, mock_config):
    stats = WorkerStats()
    shutdown = asyncio.Event()
    
    worker = WorkerThread(0, mock_horde, mock_backend, mock_config, stats, mock_health, shutdown)
    
    # 1. Provide a job
    job = HordeJob("job1", "Prompt", params={}, model="model1")
    mock_horde.pop_job.side_effect = [job, None]
    
    # 2. Force a generation error
    mock_backend.generate.side_effect = Exception("Backend crash")
    
    # Run loop
    task = asyncio.create_task(worker.run())
    
    # Wait for the error to occur
    while stats.errors_count < 1:
        await asyncio.sleep(0.1)
        
    shutdown.set()
    await task
    
    assert stats.errors_count == 1
    mock_horde.submit_error.assert_called_with("job1", "Worker error: Backend crash")
