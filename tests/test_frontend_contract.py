import pytest
from src.core.stats import StatsAggregator

def test_payload_for_app_js():
    """Ensures the JSON response contains all fields app.js expects to avoid UI breakage."""
    agg = StatsAggregator()
    agg.set_active(0, "job1", "model1", 100, 50, "Generating")
    
    active_list = agg.get_active_list()
    # Checks for fields used in updateActive() table rows
    assert "thread_id" in active_list[0]
    assert "job_id" in active_list[0]
    assert "model" in active_list[0]
    assert "status" in active_list[0]
    assert "duration" in active_list[0]
    assert "context_len" in active_list[0]
    assert "requested_tokens" in active_list[0]

    agg.complete_job(0, 50, 5.0, 5.0)
    summary = agg.get_summary()
    # Checks for fields used in updateStats() in app.js
    assert "uptime_seconds" in summary
    assert "total_jobs" in summary
    assert "total_tokens" in summary
    assert "total_kudos" in summary
    assert "kudos_per_hour" in summary
    assert "session_history" in summary # Fixed activity over time
    assert "paused" in summary # Pause toggle
    assert "max_active_threads" in summary # Peak threads stat
    assert "active_jobs_count" in summary
    
    history_list = agg.get_history_list()
    # Checks for fields used in updateHistory() table rows and speed chart
    assert "job_id" in history_list[0]
    assert "model" in history_list[0]
    assert "tokens" in history_list[0]
    assert "kudos" in history_list[0]
    assert "duration" in history_list[0]
    assert "timestamp" in history_list[0]
    assert "status" in history_list[0]
    assert "context_len" in history_list[0]
    assert "requested_tokens" in history_list[0]
