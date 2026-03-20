import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Dict
from .core.horde_api import HordeAPI, HordeJob
from .core.filters import should_skip_job
from .core.params import apply_format_flags
from .backends.adapters import BackendAdapter, GenerationResult

logger = logging.getLogger("horde.worker")

@dataclass
class WorkerStats:
    jobs_count: int = 0
    total_tokens: int = 0
    total_kudos: float = 0.0
    start_time: float = field(default_factory=time.time)
    avg_generation_time: float = 0.0
    last_job_at: Optional[float] = None
    errors_count: int = 0

    def add_job(self, tokens: int, kudos: float, duration: float):
        self.jobs_count += 1
        self.total_tokens += tokens
        self.total_kudos += kudos
        self.last_job_at = time.time()
        
        # Simple rolling average
        if self.jobs_count == 1:
            self.avg_generation_time = duration
        else:
            self.avg_generation_time = (self.avg_generation_time * 0.9) + (duration * 0.1)

    def add_error(self):
        self.errors_count += 1

    def to_summary_str(self) -> str:
        uptime_h = (time.time() - self.start_time) / 3600
        return (f"Jobs: {self.jobs_count} | Tokens: {self.total_tokens} | "
                f"Kudos: {self.total_kudos:.1f} | Errors: {self.errors_count} | "
                f"Uptime: {uptime_h:.1f}h | Avg: {self.avg_generation_time:.1f}s")

class WorkerThread:
    def __init__(self, 
                 thread_id: int, 
                 horde: HordeAPI, 
                 backend: BackendAdapter, 
                 config: Any, 
                 stats: WorkerStats,
                 health_monitor: Any,
                 shutdown_event: asyncio.Event):
        self.thread_id = thread_id
        self.horde = horde
        self.backend = backend
        self.config = config
        self.stats = stats
        self.health_monitor = health_monitor
        self.shutdown_event = shutdown_event
        self.logger = logging.getLogger(f"horde.thread.{thread_id}")

    async def run(self):
        self.logger.info(f"Thread {self.thread_id} started.")
        
        consecutive_pops_empty = 0
        backoff_timer = 0
        
        while not self.shutdown_event.is_set():
            # 1. Wait for backend to be healthy
            if not self.health_monitor.backend_healthy.is_set():
                await self.health_monitor.backend_healthy.wait()
                if self.shutdown_event.is_set(): break
            
            # 2. Pop a job from Horde
            self.logger.debug("Polling for job...")
            job = await self.horde.pop_job(self.config)
            
            if not job:
                # Calculate backoff
                consecutive_pops_empty += 1
                backoff_timer = min(30, max(2, consecutive_pops_empty // 2))
                self.logger.debug(f"Pops empty, sleeping for {backoff_timer}s...")
                
                # Use wait_for on shutdown_event to sleep interruptibly
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=backoff_timer)
                except asyncio.TimeoutError:
                    pass
                continue

            # Reset backoff on successful pop
            consecutive_pops_empty = 0
            self.logger.info(f"Received Job {job.id[:12]}: Model {job.model}")
            
            # 3. Process the Job
            await self._process_job(job)
            
        self.logger.info(f"Thread {self.thread_id} stopped.")

    async def _process_job(self, job: HordeJob):
        skip_reason = should_skip_job(job, self.config)
        if skip_reason:
            self.logger.warning(f"Skipping Job {job.id[:12]}: {skip_reason}")
            # Do NOT report error, just let it expire/timeout in Horde side
            # as per SPEC defensive approach or potentially submit error?
            # Spec says: "descartar o job sem submeter nada"
            return
            
        start_time = time.time()
        
        # Max length logic: min(job_request, worker_config)
        max_length = min(job.params.get("max_length", self.config.worker.max_length), 
                         self.config.worker.max_length)
        
        try:
            # 4. Generate
            # Timeboxed generation
            result: GenerationResult = await asyncio.wait_for(
                self.backend.generate(job.prompt, job.params, max_length, job.model),
                timeout=self.config.resilience.backend_timeout
            )
            
            generation_time = time.time() - start_time
            
            # 5. Format Postprocessing (if needed)
            text = result.text
            if not self.backend.supports_format_flags:
                text = apply_format_flags(text, job.params)
                
            # 6. Submit back to Horde
            self.logger.info(f"Submitting Job {job.id[:12]}: {len(text)} chars / {result.token_count} tokens")
            kudos = await self.horde.submit_job(
                job_id=job.id, 
                text=text, 
                seed=job.params.get("seed"), 
                token_count=result.token_count
            )
            
            if kudos is not None:
                self.stats.add_job(result.token_count or (len(text) // 4), kudos, generation_time)
                self.logger.info(f"Job {job.id[:12]} SUCCEEDED. Kudos earned: {kudos:.1f}")
            else:
                self.logger.warning(f"Job {job.id[:12]} submitted but no kudos received.")
                self.stats.add_error()
                
        except asyncio.TimeoutError:
            self.logger.error(f"Generation TIMEOUT for Job {job.id[:12]}")
            await self.horde.submit_error(job.id, "Generation timeout")
            self.stats.add_error()
        except Exception as e:
            self.logger.error(f"Error processing Job {job.id[:12]}: {e}")
            await self.horde.submit_error(job.id, f"Worker error: {str(e)}")
            self.stats.add_error()
            # Optional additional sleep after real error to avoid spamming faulties
            await asyncio.sleep(2)
