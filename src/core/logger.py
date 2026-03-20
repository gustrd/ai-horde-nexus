import logging
import json
import time
from typing import Any, Dict

class PlainFormatter(logging.Formatter):
    def format(self, record):
        thread_id = getattr(record, "thread_id", None)
        thread_str = f"thread.{thread_id:<2}" if thread_id is not None else "main      "
        record.thread_info = thread_str
        
        # Simple format
        fmt = "%(asctime)s [%(levelname)-7s] %(thread_info)s │ %(message)s"
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        data: Dict[str, Any] = {
            "timestamp": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if available
        thread_id = getattr(record, "thread_id", None)
        if thread_id is not None:
            data["thread_id"] = thread_id
            
        job_id = getattr(record, "job_id", None)
        if job_id:
            data["job_id"] = job_id
            
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(data)

def setup_logging(level: str = "INFO", structured: bool = False):
    handler = logging.StreamHandler()
    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(PlainFormatter())
    
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    
    # Silence third-party logs
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

def get_thread_logger(thread_id: int) -> logging.LoggerAdapter:
    logger = logging.getLogger(f"horde.thread.{thread_id}")
    return logging.LoggerAdapter(logger, {"thread_id": thread_id})
