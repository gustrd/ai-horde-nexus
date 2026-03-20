import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("horde.health")

class HealthMonitor:
    def __init__(self, backend: Any, horde: Any, config: Any, stats: Any):
        self.backend = backend
        self.horde = horde
        self.config = config
        self.stats = stats
        
        self.backend_healthy = asyncio.Event()
        self.backend_healthy.set() # Start healthy
        
        self.stop_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await self.task

    async def run(self):
        logger.info("Health monitor started.")
        
        last_horde_check = 0.0
        last_stats_log = time.time()
        
        while not self.stop_event.is_set():
            now = time.time()
            
            # 1. Backend Health Check
            try:
                is_healthy = await self.backend.health_check()
                if is_healthy:
                    if not self.backend_healthy.is_set():
                        logger.info("Backend is back ONLINE. Resuming work.")
                        self.backend_healthy.set()
                else:
                    if self.backend_healthy.is_set():
                        logger.warning("Backend is OFFLINE. Pausing worker threads.")
                        self.backend_healthy.clear()
            except Exception as e:
                logger.error(f"Backend health check error: {e}")
                if self.backend_healthy.is_set():
                    self.backend_healthy.clear()
            
            # 2. Horde Heartbeat (less frequent)
            if now - last_horde_check >= self.config.resilience.horde_heartbeat_interval:
                is_horde_up = await self.horde.check_heartbeat()
                if not is_horde_up:
                    logger.warning("Could not reach AI Horde API heartbeat endpoint.")
                last_horde_check = now
                
            # 3. Stats Logging (every 10 minutes by default, but maybe less for logs)
            if now - last_stats_log >= 600: # 10 mins
                summary = self.stats.to_summary_str()
                logger.info(f"Health Summary: {summary}")
                last_stats_log = now
            
            # Wait for next interval or stop signal
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), 
                    timeout=self.config.resilience.backend_health_interval
                )
            except asyncio.TimeoutError:
                pass
                
        logger.info("Health monitor stopped.")
