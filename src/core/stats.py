import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from collections import deque

@dataclass
class JobHistoryEntry:
    job_id: str
    model: str
    context_len: int
    requested_tokens: int
    tokens: int
    kudos: float
    duration: float
    timestamp: float = field(default_factory=time.time)
    status: str = "success" # or "error"

@dataclass
class ActiveJob:
    job_id: str
    model: str
    context_len: int
    requested_tokens: int
    status: str
    start_time: float
    thread_id: int

class StatsAggregator:
    def __init__(self, history_limit: int = 100):
        self.history = deque(maxlen=history_limit)
        self.active_jobs: Dict[int, ActiveJob] = {}
        self.total_jobs = 0
        self.total_tokens = 0
        self.total_kudos = 0.0
        self.total_errors = 0
        self.max_active_threads = 0
        self.paused = False
        self.session_history = deque(maxlen=1000) # Keep snapshots for a long time
        self.start_time = time.time()
        
    def take_snapshot(self):
        """Records a snapshot of current metrics for the activity chart."""
        self.session_history.append({
            "timestamp": time.time(),
            "total_jobs": self.total_jobs,
            "active_jobs_count": len(self.active_jobs)
        })
        
    def set_active(self, thread_id: int, job_id: str, model: str, context_len: int, requested_tokens: int, status: str = "processing"):
        self.active_jobs[thread_id] = ActiveJob(
            job_id=job_id,
            model=model,
            context_len=context_len,
            requested_tokens=requested_tokens,
            status=status,
            start_time=time.time(),
            thread_id=thread_id
        )
        if len(self.active_jobs) > self.max_active_threads:
            self.max_active_threads = len(self.active_jobs)
        
    def update_status(self, thread_id: int, status: str):
        if thread_id in self.active_jobs:
            self.active_jobs[thread_id].status = status
            
    def complete_job(self, thread_id: int, tokens: int, kudos: float, duration: float):
        if thread_id in self.active_jobs:
            job = self.active_jobs.pop(thread_id)
            entry = JobHistoryEntry(
                job_id=job.job_id,
                model=job.model,
                context_len=job.context_len,
                requested_tokens=job.requested_tokens,
                tokens=tokens,
                kudos=kudos,
                duration=duration,
                status="success"
            )
            self.history.append(entry)
            self.total_jobs += 1
            self.total_tokens += tokens
            self.total_kudos += kudos
            
    def fail_job(self, thread_id: int, reason: str = "error"):
        if thread_id in self.active_jobs:
            job = self.active_jobs.pop(thread_id)
            entry = JobHistoryEntry(
                job_id=job.job_id,
                model=job.model,
                context_len=job.context_len,
                requested_tokens=job.requested_tokens,
                tokens=0,
                kudos=0.0,
                duration=time.time() - job.start_time,
                status=f"error: {reason}"
            )
            self.history.append(entry)
            self.total_errors += 1

    def get_summary(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        return {
            "uptime_seconds": int(uptime),
            "total_jobs": self.total_jobs,
            "total_tokens": self.total_tokens,
            "total_kudos": round(self.total_kudos, 2),
            "total_errors": self.total_errors,
            "max_active_threads": self.max_active_threads,
            "paused": self.paused,
            "active_jobs_count": len(self.active_jobs),
            "kudos_per_hour": round((self.total_kudos / (uptime / 3600)), 2) if uptime > 0 else 0,
            "session_history": list(self.session_history)
        }

    def get_active_list(self) -> List[Dict[str, Any]]:
        now = time.time()
        return [
            {
                "thread_id": j.thread_id,
                "job_id": j.job_id,
                "model": j.model,
                "context_len": j.context_len,
                "requested_tokens": j.requested_tokens,
                "status": j.status,
                "duration": round(now - j.start_time, 1)
            }
            for j in self.active_jobs.values()
        ]

    def get_history_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "job_id": e.job_id,
                "model": e.model,
                "context_len": e.context_len,
                "requested_tokens": e.requested_tokens,
                "tokens": e.tokens,
                "kudos": e.kudos,
                "duration": round(e.duration, 1),
                "timestamp": e.timestamp,
                "status": e.status
            }
            for e in reversed(self.history)
        ]
