import aiohttp
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from ..core.params import map_params_to_koboldai, map_params_to_openai

logger = logging.getLogger("horde.backends")

@dataclass
class GenerationResult:
    text: str
    token_count: Optional[int] = None
    seed: Optional[int] = None
    finish_reason: Optional[str] = None

class BackendAdapter:
    def __init__(self, name: str, url: str, api_style: str = "koboldai"):
        self.name = name
        self.url = url
        self.api_style = api_style
        self.session: Optional[aiohttp.ClientSession] = None
        self.supports_format_flags = False # False for OpenAI, True for KoboldAI
        self.timeout = 300

    async def start(self, api_key: Optional[str] = None):
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            # Some platforms use x-api-key, will handle in subclasses
            headers["x-api-key"] = api_key
            
        if not self.session:
            self.session = aiohttp.ClientSession(
                base_url=self.url,
                headers=headers
            )

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def health_check(self) -> bool:
        raise NotImplementedError()
        
    async def get_current_model(self) -> Optional[str]:
        """Returns the name of the currently loaded model on the backend."""
        return None

    async def generate(self, prompt: str, params: Dict[str, Any], max_length: int, model_name: str) -> GenerationResult:
        raise NotImplementedError()

class KoboldAIBackend(BackendAdapter):
    def __init__(self, url: str):
        super().__init__(name="KoboldCpp", url=url, api_style="koboldai")
        self.supports_format_flags = True

    async def health_check(self) -> bool:
        if not self.session: await self.start()
        try:
            # Check model endpoint
            async with self.session.get("/api/v1/model", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return "result" in data
                return False
        except:
            return False

    async def get_current_model(self) -> Optional[str]:
        if not self.session: await self.start()
        try:
            async with self.session.get("/api/v1/model", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result")
        except:
            pass
        return None

    async def generate(self, prompt: str, params: Dict[str, Any], max_length: int, model_name: str) -> GenerationResult:
        if not self.session: await self.start()
        
        mapped_params = map_params_to_koboldai(params)
        mapped_params["prompt"] = prompt
        mapped_params["max_length"] = max_length
        # Extra KoboldAI fields
        mapped_params["n"] = 1
        
        async with self.session.post("/api/v1/generate", json=mapped_params, timeout=self.timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                result = data["results"][0]
                text = result["text"]
                # KoboldCpp uses field "token_count" if enabled, but not standard in v1
                return GenerationResult(
                    text=text,
                    token_count=len(text) // 4 # Basic estimation fallback
                )
            elif resp.status == 503:
                logger.warning("KoboldCpp returned 503 Busy - all slots full.")
                raise RuntimeError("Backend 503: Busy")
            else:
                raise RuntimeError(f"Backend error: status {resp.status}")

class OpenAIBackend(BackendAdapter):
    def __init__(self, url: str, name: str = "OpenAI-Compatible"):
        super().__init__(name=name, url=url, api_style="openai")

    async def health_check(self) -> bool:
        if not self.session: await self.start()
        try:
            async with self.session.get("/v1/models", timeout=10) as resp:
                return resp.status == 200
        except:
            return False

    async def get_current_model(self) -> Optional[str]:
        if not self.session: await self.start()
        try:
            async with self.session.get("/v1/models", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    if models:
                        return models[0].get("id")
        except:
            pass
        return None

    async def generate(self, prompt: str, params: Dict[str, Any], max_length: int, model_name: str) -> GenerationResult:
        if not self.session: await self.start()
        
        mapped_params = map_params_to_openai(params, backend_name=self.name.lower())
        mapped_params["prompt"] = prompt
        # OpenAI style
        mapped_params["model"] = model_name
        mapped_params["max_tokens"] = max_length
        
        async with self.session.post("/v1/completions", json=mapped_params, timeout=self.timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                choice = data["choices"][0]
                usage = data.get("usage", {})
                return GenerationResult(
                    text=choice["text"],
                    token_count=usage.get("completion_tokens"),
                    finish_reason=choice.get("finish_reason")
                )
            elif resp.status == 503:
                raise RuntimeError("Backend 503: Busy")
            else:
                body = await resp.text()
                raise RuntimeError(f"Backend error: status {resp.status} - {body[:100]}")

async def detect_backend(url: str, timeout: int = 10) -> BackendAdapter:
    """Probes the URL to determine the backend type."""
    logger.info(f"Probing backend at {url}...")
    
    async with aiohttp.ClientSession() as session:
        # 1. KoboldAI Probe
        try:
            async with session.get(f"{url}/api/v1/model", timeout=timeout) as resp:
                if resp.status == 200:
                    logger.info("Found: KoboldAI/KoboldCpp Backend")
                    return KoboldAIBackend(url)
        except: pass
        
        # 2. OpenAI-style Probe
        try:
            async with session.get(f"{url}/v1/models", timeout=timeout) as resp:
                if resp.status == 200:
                    logger.info("Found: OpenAI-compatible Backend")
                    return OpenAIBackend(url)
        except: pass
        
    # Default to KoboldAI or raise error
    logger.warning("Could not clearly detect backend. Defaulting to KoboldAI adapter.")
    return KoboldAIBackend(url)
