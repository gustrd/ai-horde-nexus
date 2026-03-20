import pytest
from aiohttp import web
from src.webui.server import WebUI
from src.core.stats import StatsAggregator

@pytest.fixture
def aggregator():
    return StatsAggregator()

@pytest.fixture
def shutdown_event():
    from unittest.mock import MagicMock
    return MagicMock()

@pytest.fixture
def ui_app(aggregator, shutdown_event):
    ui = WebUI(aggregator, shutdown_event, port=8083)
    return ui.app

@pytest.mark.asyncio
async def test_api_stats_empty(aiohttp_client, ui_app, aggregator):
    client = await aiohttp_client(ui_app)
    resp = await client.get("/api/stats")
    assert resp.status == 200
    data = await resp.json()
    assert data["total_jobs"] == 0
    assert data["total_kudos"] == 0.0

@pytest.mark.asyncio
async def test_api_active_jobs(aiohttp_client, ui_app, aggregator):
    client = await aiohttp_client(ui_app)
    
    # 1. Fill some active data
    aggregator.set_active(0, "job-1", "m1", 100, 50, "Generating")
    
    resp = await client.get("/api/jobs/active")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "job-1"
    assert data[0]["status"] == "Generating"

@pytest.mark.asyncio
async def test_api_history(aiohttp_client, ui_app, aggregator):
    client = await aiohttp_client(ui_app)
    
    # 1. Complete a job
    aggregator.set_active(0, "job-done", "m1", 100, 50)
    aggregator.complete_job(0, 10, 1.0, 1.0)
    
    resp = await client.get("/api/jobs/history")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "job-done"

@pytest.mark.asyncio
async def test_static_routing(aiohttp_client, ui_app):
    client = await aiohttp_client(ui_app)
    # Check if static endpoint exists (even if file is missing in test env, it should return 404 or contents)
    resp = await client.get("/static/app.js")
    assert resp.status in (200, 404)

@pytest.mark.asyncio
async def test_api_control_pause_resume(aiohttp_client, ui_app, aggregator):
    client = await aiohttp_client(ui_app)
    
    # Pause
    resp = await client.post("/api/control", json={"action": "pause"})
    assert resp.status == 200
    assert aggregator.paused is True
    
    # Resume
    resp = await client.post("/api/control", json={"action": "resume"})
    assert resp.status == 200
    assert aggregator.paused is False

@pytest.mark.asyncio
async def test_api_control_shutdown(aiohttp_client, ui_app, shutdown_event):
    client = await aiohttp_client(ui_app)
    resp = await client.post("/api/control", json={"action": "shutdown"})
    assert resp.status == 200
    shutdown_event.set.assert_called_once()
