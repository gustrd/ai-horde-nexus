import pytest
from aioresponses import aioresponses
from src.core.horde_api import HordeAPI, HordeJob
from src.core.config import AppConfig

@pytest.fixture
def mock_aioresponse():
    with aioresponses() as m:
        yield m

@pytest.fixture
def horde_api():
    return HordeAPI(api_key="0000000000", url="https://aihorde.net", worker_name="TestWorker")

@pytest.mark.asyncio
async def test_pop_job_success(mock_aioresponse, horde_api):
    config = AppConfig()
    url = f"https://aihorde.net/api/v2/generate/text/pop"
    
    mock_payload = {
        "id": "job123",
        "payload": {
            "prompt": "Say hello",
            "temperature": 0.7
        },
        "model": "pygmalion",
        "skipped": {}
    }
    
    mock_aioresponse.post(url, payload=mock_payload, status=200)
    
    job = await horde_api.pop_job(config)
    assert job is not None
    assert job.id == "job123"
    assert job.prompt == "Say hello"
    assert job.params["temperature"] == 0.7

@pytest.mark.asyncio
async def test_pop_job_empty(mock_aioresponse, horde_api):
    config = AppConfig()
    url = f"https://aihorde.net/api/v2/generate/text/pop"
    
    mock_aioresponse.post(url, payload={"id": None}, status=200)
    
    job = await horde_api.pop_job(config)
    assert job is None

@pytest.mark.asyncio
async def test_submit_job_success(mock_aioresponse, horde_api):
    url = f"https://aihorde.net/api/v2/generate/text/submit"
    mock_aioresponse.post(url, payload={"reward": 10.5}, status=200)
    
    reward = await horde_api.submit_job("job123", "Generated text")
    assert reward == 10.5

@pytest.mark.asyncio
async def test_submit_job_expired(mock_aioresponse, horde_api):
    url = f"https://aihorde.net/api/v2/generate/text/submit"
    mock_aioresponse.post(url, status=404)
    
    kudos = await horde_api.submit_job("job123", "Generated text")
    assert kudos is None
