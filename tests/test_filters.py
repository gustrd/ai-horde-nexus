import pytest
from src.core.filters import should_skip_job
from src.core.horde_api import HordeJob

class MockWorkerConfig:
    def __init__(self, blacklist=None, max_context_length=8192):
        self.blacklist = blacklist or []
        self.max_context_length = max_context_length

class MockConfig:
    def __init__(self, blacklist=None, max_context_length=8192):
        self.worker = MockWorkerConfig(blacklist, max_context_length)

def test_should_skip_job_blacklist():
    config = MockConfig(blacklist=["badword", "secret"])
    
    # 1. Safe prompt
    job = HordeJob(id="1", prompt="This is a safe prompt", params={}, model="test")
    assert should_skip_job(job, config) is None
    
    # 2. Blacklisted word
    job = HordeJob(id="2", prompt="This is a badword prompt", params={}, model="test")
    assert "badword" in should_skip_job(job, config)
    
    # 3. Case insensitive
    job = HordeJob(id="3", prompt="This contains SECRET stuff", params={}, model="test")
    assert "SECRET" in should_skip_job(job, config).upper()

def test_should_skip_job_context_limit():
    config = MockConfig(max_context_length=2048)
    
    # 1. Within limit
    job = HordeJob(id="1", prompt="...", params={"max_context_length": 1024}, model="test")
    assert should_skip_job(job, config) is None
    
    # 2. Exceeds limit
    job = HordeJob(id="2", prompt="...", params={"max_context_length": 4096}, model="test")
    assert "exceeds worker limit" in should_skip_job(job, config)

def test_should_skip_job_no_blacklist():
    config = MockConfig(blacklist=[])
    job = HordeJob(id="1", prompt="Anything goes", params={}, model="test")
    assert should_skip_job(job, config) is None
