import time
import pytest
from src.core.stats import StatsAggregator

def test_aggregator_initialization():
    agg = StatsAggregator(history_limit=10)
    summary = agg.get_summary()
    assert summary["total_jobs"] == 0
    assert summary["total_kudos"] == 0.0
    assert summary["uptime_seconds"] >= 0

def test_active_job_tracking():
    agg = StatsAggregator()
    agg.set_active(0, "job-1", "model-a", 100, 50, "Generating")
    
    active = agg.get_active_list()
    assert len(active) == 1
    assert active[0]["thread_id"] == 0
    assert active[0]["status"] == "Generating"
    
    agg.update_status(0, "Submitting")
    active = agg.get_active_list()
    assert active[0]["status"] == "Submitting"

def test_job_completion():
    agg = StatsAggregator()
    agg.set_active(0, "job-1", "model-a", 100, 50)
    agg.complete_job(0, tokens=100, kudos=5.5, duration=2.5)
    
    summary = agg.get_summary()
    assert summary["total_jobs"] == 1
    assert summary["total_tokens"] == 100
    assert summary["total_kudos"] == 5.5
    assert len(agg.active_jobs) == 0
    
    history = agg.get_history_list()
    assert len(history) == 1
    assert history[0]["job_id"] == "job-1"

def test_job_failure():
    agg = StatsAggregator()
    agg.set_active(1, "job-fail", "model-b", 100, 50)
    agg.fail_job(1, "connection timeout")
    
    summary = agg.get_summary()
    assert summary["total_errors"] == 1
    assert summary["total_jobs"] == 0
    
    history = agg.get_history_list()
    assert "error: connection timeout" in history[0]["status"]

def test_history_limit():
    agg = StatsAggregator(history_limit=2)
    agg.set_active(0, "j1", "m", 10, 5)
    agg.complete_job(0, 1, 1.0, 1.0)
    agg.set_active(0, "j2", "m", 10, 5)
    agg.complete_job(0, 1, 1.0, 1.0)
    agg.set_active(0, "j3", "m", 10, 5)
    agg.complete_job(0, 1, 1.0, 1.0)
    
    history = agg.get_history_list()
    assert len(history) == 2
    assert history[0]["job_id"] == "j3" # Latest first

def test_session_snapshots():
    agg = StatsAggregator()
    agg.total_jobs = 5
    agg.take_snapshot()
    
    summary = agg.get_summary()
    assert len(summary["session_history"]) == 1
    assert summary["session_history"][0]["total_jobs"] == 5

def test_max_active_threads():
    agg = StatsAggregator()
    agg.set_active(0, "j1", "m", 1, 1)
    agg.set_active(1, "j2", "m", 1, 1)
    assert agg.max_active_threads == 2
    
    agg.complete_job(0, 1, 1, 1)
    # Max should remain 2
    assert agg.max_active_threads == 2
    
def test_pause_toggle():
    agg = StatsAggregator()
    assert agg.paused is False
    agg.paused = True
    summary = agg.get_summary()
    assert summary["paused"] is True
