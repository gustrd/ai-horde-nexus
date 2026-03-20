import asyncio
import logging
import aiohttp
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

logger = logging.getLogger("horde.api")

@dataclass
class HordeJob:
    id: str
    prompt: str
    params: Dict[str, Any]
    model: str
    softprompt: Optional[str] = None
    skipped: Dict[str, int] = field(default_factory=dict)

class HordeAPI:
    def __init__(self, api_key: str, url: str, worker_name: str, version: str = "0.1.0"):
        self.api_key = api_key
        self.url = url
        self.worker_name = worker_name
        self.version = version
        self.session: Optional[aiohttp.ClientSession] = None
        
        # User agent / bridge agent string
        # name:version:url
        repo_url = "https://github.com/gustrd/ai-horde-nexus"
        self.bridge_agent = f"horde-scribe-worker:{self.version}:{repo_url}"
        
    async def start(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={
                    "apikey": self.api_key,
                    "User-Agent": self.bridge_agent,
                    "Client-Agent": self.bridge_agent
                }
            )

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def pop_job(self, config: Any) -> Optional[HordeJob]:
        if not self.session:
            await self.start()
            
        pop_url = f"{self.url}/api/v2/generate/text/pop"
        payload = {
            "name": self.worker_name,
            "models": config.worker.models_to_serve,
            "max_length": config.worker.max_length,
            "max_context_length": config.worker.max_context_length,
            "priority_usernames": config.worker.priority_usernames,
            "nsfw": config.worker.nsfw,
            "require_upfront_kudos": config.worker.require_upfront_kudos,
            "threads": 1,
            "bridge_agent": self.bridge_agent,
            "blacklist": config.worker.blacklist,
        }
        
        try:
            async with self.session.post(pop_url, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if not data or "id" not in data or not data["id"]:
                        if "skipped" in data and any(data["skipped"].values()):
                            logger.debug(f"Pops empty, skipped jobs: {data['skipped']}")
                        return None
                        
                    return HordeJob(
                        id=data["id"],
                        prompt=data["payload"]["prompt"],
                        params=data["payload"],
                        model=data.get("model", "unknown"),
                        softprompt=data.get("softprompt"),
                        skipped=data.get("skipped", {})
                    )
                elif resp.status == 400:
                    body = await resp.text()
                    logger.warning(f"Horde Pop failed with 400 Bad Request: {body}")
                    return None
                elif resp.status == 403:
                    logger.error("Horde API 403 Forbidden - Invalid API key?")
                    return None
                elif resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    logger.warning(f"Rate limited by Horde. Waiting {retry_after}s...")
                    await asyncio.sleep(retry_after)
                    return None
                else:
                    logger.warning(f"Horde Pop failed with status {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Error during Horde Pop: {e}")
            return None

    async def submit_job(self, job_id: str, text: str, seed: Optional[int] = None, token_count: Optional[int] = None) -> Optional[float]:
        if not self.session:
            await self.start()
            
        submit_url = f"{self.url}/api/v2/generate/text/submit"
        payload = {
            "id": job_id,
            "generation": text,
            "state": "ok",
            "gen_metadata": []
        }
        if seed is not None:
            payload["seed"] = seed
            
        # Optional metadata can be added to gen_metadata if needed
            
        try:
            async with self.session.post(submit_url, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"Submit response: {data}")
                    # Scribe API returns 'reward' for kudos earned
                    reward = data.get("reward", data.get("kudos", 0.0))
                    return float(reward)
                elif resp.status == 404:
                    logger.warning(f"Job {job_id} expired or was deleted from Horde (404).")
                    return None
                else:
                    logger.warning(f"Horde Submit failed with status {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Error during Horde Submit: {e}")
            return None

    async def submit_error(self, job_id: str, error_msg: str):
        if not self.session:
            await self.start()
            
        submit_url = f"{self.url}/api/v2/generate/text/submit"
        payload = {
            "id": job_id,
            "generation": "",
            "state": "faulted",
            "gen_metadata": [
                {
                    "type": "generation", 
                    "value": "faulted",
                    "ref": error_msg[:256] # Limit message size
                }
            ]
        }
        
        try:
            async with self.session.post(submit_url, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    logger.info(f"Reported job {job_id} as faulted.")
                else:
                    logger.warning(f"Failed to report error for job {job_id}: status {resp.status}")
        except Exception as e:
            logger.error(f"Error reporting fault for {job_id}: {e}")

    async def check_heartbeat(self) -> bool:
        """Simple health check of the Horde API."""
        if not self.session:
            await self.start()
            
        # Using status as heart-beat
        url = f"{self.url}/api/v2/status/heartbeat"
        try:
            async with self.session.get(url, timeout=10) as resp:
                return resp.status == 200
        except:
            return False
