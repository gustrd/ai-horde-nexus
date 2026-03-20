import pytest
from aioresponses import aioresponses
from src.backends.adapters import KoboldAIBackend, OpenAIBackend, detect_backend

@pytest.fixture
def mock_aioresponse():
    with aioresponses() as m:
        yield m

@pytest.mark.asyncio
async def test_kobold_health_check(mock_aioresponse):
    url = "http://localhost:5001"
    adapter = KoboldAIBackend(url)
    
    # 1. Healthy
    mock_aioresponse.get(f"{url}/api/v1/model", payload={"result": "test-model"}, status=200)
    assert await adapter.health_check() is True
    
    # 2. Unhealthy
    mock_aioresponse.get(f"{url}/api/v1/model", status=500)
    assert await adapter.health_check() is False

@pytest.mark.asyncio
async def test_kobold_get_model(mock_aioresponse):
    url = "http://localhost:5001"
    adapter = KoboldAIBackend(url)
    mock_aioresponse.get(f"{url}/api/v1/model", payload={"result": "my-llama"}, status=200)
    assert await adapter.get_current_model() == "my-llama"

@pytest.mark.asyncio
async def test_openai_health_check(mock_aioresponse):
    url = "http://localhost:8080"
    adapter = OpenAIBackend(url)
    
    # 1. Healthy
    mock_aioresponse.get(f"{url}/v1/models", status=200)
    assert await adapter.health_check() is True
    
    # 2. Unhealthy
    mock_aioresponse.get(f"{url}/v1/models", status=404)
    assert await adapter.health_check() is False

@pytest.mark.asyncio
async def test_openai_get_model(mock_aioresponse):
    url = "http://localhost:8080"
    adapter = OpenAIBackend(url)
    mock_aioresponse.get(f"{url}/v1/models", payload={"data": [{"id": "gpt-test"}]}, status=200)
    assert await adapter.get_current_model() == "gpt-test"

@pytest.mark.asyncio
async def test_detect_backend_kobold(mock_aioresponse):
    url = "http://localhost:5001"
    mock_aioresponse.get(f"{url}/api/v1/model", payload={"result": "test-model"}, status=200)
    
    adapter = await detect_backend(url)
    assert isinstance(adapter, KoboldAIBackend)

@pytest.mark.asyncio
async def test_detect_backend_openai(mock_aioresponse):
    url = "http://localhost:8080"
    # Rejects Kobold prompt, accepts OpenAI
    mock_aioresponse.get(f"{url}/api/v1/model", status=404)
    mock_aioresponse.get(f"{url}/v1/models", status=200)
    
    adapter = await detect_backend(url)
    assert isinstance(adapter, OpenAIBackend)

@pytest.mark.asyncio
async def test_kobold_generate(mock_aioresponse):
    url = "http://localhost:5001"
    adapter = KoboldAIBackend(url)
    mock_aioresponse.post(f"{url}/api/v1/generate", payload={"results": [{"text": "Hello response"}]}, status=200)
    
    result = await adapter.generate("Hello", {}, 256, "model-test")
    assert result.text == "Hello response"
    assert result.token_count > 0

@pytest.mark.asyncio
async def test_openai_generate(mock_aioresponse):
    url = "http://localhost:8080"
    adapter = OpenAIBackend(url)
    mock_payload = {
        "choices": [{"text": "Hello response", "finish_reason": "stop"}],
        "usage": {"completion_tokens": 5}
    }
    mock_aioresponse.post(f"{url}/v1/completions", payload=mock_payload, status=200)
    
    result = await adapter.generate("Hello", {}, 256, "model-test")
    assert result.text == "Hello response"
    assert result.token_count == 5
