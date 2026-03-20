import os
import pytest
from src.core.config import load_config, AppConfig

def test_default_config():
    config = load_config()
    assert isinstance(config, AppConfig)
    assert config.worker.max_threads == 1
    assert config.horde.url == "https://aihorde.net"

def test_env_override(monkeypatch):
    monkeypatch.setenv("HORDE_API_KEY", "testkey123")
    monkeypatch.setenv("HORDE_WORKER_NAME", "CustomWorker")
    monkeypatch.setenv("HORDE_MAX_THREADS", "5")
    
    config = load_config()
    assert config.horde.api_key == "testkey123"
    assert config.worker.name == "CustomWorker"
    assert config.worker.max_threads == 5

def test_validation():
    config = load_config()
    config.worker.max_threads = 0
    with pytest.raises(ValueError, match="max_threads"):
        config.validate()
        
    config.worker.max_threads = 1
    config.worker.max_length = 2000
    config.worker.max_context_length = 1000
    with pytest.raises(ValueError, match="max_length"):
        config.validate()

def test_display_masking():
    config = load_config()
    config.horde.api_key = "very-long-secret-key-12345"
    d = config.to_display_dict()
    assert "very" in d["horde"]["api_key"]
    assert "..." in d["horde"]["api_key"]
    assert "2345" in d["horde"]["api_key"]
    assert "secret" not in d["horde"]["api_key"]

def test_model_name_override_default_is_none():
    """model_name_override must default to None when unset."""
    config = load_config()
    assert config.backend.model_name_override is None

def test_model_name_override_via_env(monkeypatch):
    """model_name_override must be set by env var."""
    monkeypatch.setenv("HORDE_BACKEND_MODEL_OVERRIDE", "koboldcpp/my-special-model")
    config = load_config()
    assert config.backend.model_name_override == "koboldcpp/my-special-model"

def test_model_name_override_empty_env_stays_none(monkeypatch):
    """Empty string env var must not override to empty string; must stay None."""
    monkeypatch.setenv("HORDE_BACKEND_MODEL_OVERRIDE", "")
    config = load_config()
    assert config.backend.model_name_override is None
