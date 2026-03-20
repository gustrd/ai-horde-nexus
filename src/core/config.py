import os
import yaml
from dataclasses import dataclass, field, asdict
from typing import List, Optional

@dataclass
class HordeConfig:
    api_key: str = "0000000000"
    url: str = "https://aihorde.net"
    
    def __post_init__(self):
        self.url = self.url.rstrip("/")

@dataclass
class WorkerConfig:
    name: str = "ScribeWorker"
    max_threads: int = 1
    max_length: int = 512
    max_context_length: int = 8192
    models_to_serve: List[str] = field(default_factory=lambda: ["*"])
    priority_usernames: List[str] = field(default_factory=list)
    nsfw: bool = True
    blacklist: List[str] = field(default_factory=list)
    require_upfront_kudos: bool = False
    webui_enabled: bool = True
    webui_port: int = 8082

@dataclass
class BackendConfig:
    url: str = "http://localhost:5001"
    api_key: Optional[str] = None
    model_name_override: Optional[str] = None
    timeout: int = 300
    
    def __post_init__(self):
        self.url = self.url.rstrip("/")

@dataclass
class ResilienceConfig:
    backend_timeout: int = 300
    backend_health_interval: int = 30
    horde_heartbeat_interval: int = 300

@dataclass
class AppConfig:
    horde: HordeConfig = field(default_factory=HordeConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)
    log_level: str = "INFO"

    def __post_init__(self):
        self.log_level = self.log_level.upper()

    def validate(self):
        if self.worker.max_threads < 1:
            raise ValueError("max_threads must be at least 1")
        if self.worker.max_length > self.worker.max_context_length:
            raise ValueError("max_length cannot be greater than max_context_length")
        if not self.horde.api_key:
            raise ValueError("Horde API key cannot be empty")
        # Add more validation if needed

    def to_display_dict(self):
        d = asdict(self)
        # Mask API key
        key = d["horde"]["api_key"]
        if len(key) > 8:
            d["horde"]["api_key"] = f"{key[:4]}...{key[-4:]}"
        else:
            d["horde"]["api_key"] = "****"
            
        if d["backend"]["api_key"]:
            d["backend"]["api_key"] = "****"
            
        return d

def load_config(config_path: Optional[str] = None) -> AppConfig:
    config = AppConfig()
    
    # Load from YAML if provided
    if config_path and os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
            if data:
                if "horde" in data:
                    config.horde = HordeConfig(**data["horde"])
                if "worker" in data:
                    config.worker = WorkerConfig(**data["worker"])
                if "backend" in data:
                    config.backend = BackendConfig(**data["backend"])
                if "resilience" in data:
                    config.resilience = ResilienceConfig(**data["resilience"])
                if "log_level" in data:
                    config.log_level = data["log_level"]

    # Manual Env Overrides (as per spec, without over-engineering)
    def env_str(key: str, default: str) -> str:
        return os.environ.get(key, default)
    
    def env_int(key: str, default: int) -> int:
        val = os.environ.get(key)
        return int(val) if val is not None else default
    
    def env_bool(key: str, default: bool) -> bool:
        val = os.environ.get(key)
        if val is None: return default
        return val.lower() in ("true", "1", "yes")

    def env_list(key: str, default: List[str]) -> List[str]:
        val = os.environ.get(key)
        if val is None: return default
        return [x.strip() for x in val.split(",") if x.strip()]

    config.horde.api_key = env_str("HORDE_API_KEY", config.horde.api_key)
    config.horde.url = env_str("HORDE_URL", config.horde.url)
    
    config.worker.name = env_str("HORDE_WORKER_NAME", config.worker.name)
    config.worker.max_threads = env_int("HORDE_MAX_THREADS", config.worker.max_threads)
    config.worker.max_length = env_int("HORDE_MAX_LENGTH", config.worker.max_length)
    config.worker.max_context_length = env_int("HORDE_MAX_CONTEXT_LENGTH", config.worker.max_context_length)
    config.worker.models_to_serve = env_list("HORDE_MODELS_TO_SERVE", config.worker.models_to_serve)
    config.worker.priority_usernames = env_list("HORDE_PRIORITY_USERNAMES", config.worker.priority_usernames)
    config.worker.nsfw = env_bool("HORDE_NSFW", config.worker.nsfw)
    config.worker.blacklist = env_list("HORDE_BLACKLIST", config.worker.blacklist)
    config.worker.require_upfront_kudos = env_bool("HORDE_REQUIRE_KUDOS", config.worker.require_upfront_kudos)
    config.worker.webui_enabled = env_bool("HORDE_WEBUI_ENABLED", config.worker.webui_enabled)
    config.worker.webui_port = env_int("HORDE_WEBUI_PORT", config.worker.webui_port)
    
    config.backend.url = env_str("HORDE_BACKEND_URL", config.backend.url)
    config.backend.api_key = env_str("HORDE_BACKEND_API_KEY", config.backend.api_key or "")
    config.backend.model_name_override = env_str("HORDE_BACKEND_MODEL_OVERRIDE", config.backend.model_name_override or "") or None
    config.backend.timeout = env_int("HORDE_BACKEND_TIMEOUT", config.backend.timeout)
    
    config.log_level = env_str("LOG_LEVEL", config.log_level)
    
    # Re-normalize/re-run post_init after env overrides
    config.horde.__post_init__()
    config.worker.__post_init__ = lambda: None # type: ignore
    config.backend.__post_init__()
    config.__post_init__()
    
    config.validate()
    
    return config
