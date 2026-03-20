import logging
from typing import Optional, Any
from .horde_api import HordeJob

logger = logging.getLogger("horde.filters")

def should_skip_job(job: HordeJob, config: Any) -> Optional[str]:
    """
    Evaluates whether the job should be skipped locally as safety defense.
    Returns the reason for skip if any, otherwise None.
    """
    
    # 1. Blacklist check
    if hasattr(config.worker, "blacklist") and config.worker.blacklist:
        prompt_lower = job.prompt.lower()
        for word in config.worker.blacklist:
            if word.lower() in prompt_lower:
                return f"Prompt contains blacklisted word: '{word}'"
                
    # 2. Context limits (Horde should handle this, but defense in depth)
    job_context = job.params.get("max_context_length", config.worker.max_context_length)
    if job_context > config.worker.max_context_length:
        return f"Job context ({job_context}) exceeds worker limit ({config.worker.max_context_length})"
        
    return None
