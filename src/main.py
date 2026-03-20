import asyncio
import logging
import signal
import sys
import time
from .core.config import load_config
from .core.logger import setup_logging
from .core.horde_api import HordeAPI
from .core.health import HealthMonitor
from .backends.adapters import detect_backend
from .worker import WorkerThread, WorkerStats

# Version
VERSION = "0.1.0"

logger = logging.getLogger("horde.main")

def print_banner(config):
    banner = f"""
    ╔════════════════════════════════════════════════════════╗
    ║  Horde Scribe Worker v{VERSION:<26}  ║
    ║  Worker: {config.worker.name[:38]:<39} ║
    ║  Backend: {config.backend.url[:37]:<38} ║
    ║  Threads: {config.worker.max_threads:<39} ║
    ║  Context: {config.worker.max_context_length:<4} | Max Length: {config.worker.max_length:<16}  ║
    ╚════════════════════════════════════════════════════════╝
    """
    print(banner)

async def main():
    # 1. Load Config
    config_path = "configs/config.yaml"
    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"FAILED TO LOAD CONFIGURATION: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Setup Logging
    setup_logging(config.log_level)
    print_banner(config)

    # 3. Detect Backend
    try:
        backend = await detect_backend(config.backend.url)
        # Auth if needed
        await backend.start(config.backend.api_key)
        
        # Initial health check
        if not await backend.health_check():
            logger.error("Backend health check failed at startup. Exiting.")
            sys.exit(1)
            
        # 3.1 Auto-resolve wildcard models if '*' is in models_to_serve
        if "*" in config.worker.models_to_serve:
            current_model = await backend.get_current_model()
            if current_model:
                logger.info(f"Auto-resolved served model: {current_model}")
                # Replace '*' with the actual model
                new_models = [m for m in config.worker.models_to_serve if m != "*"]
                if current_model not in new_models:
                    new_models.append(current_model)
                config.worker.models_to_serve = new_models
            else:
                logger.warning("Wildcard '*' in models_to_serve but could not detect model from backend.")
                if config.worker.models_to_serve == ["*"]:
                    logger.error("No specific models defined and auto-discovery failed. Horde Pop will fail.")
                    # We continue but it will probably fail with 400 as seen before

        logger.info(f"Verified backend: {backend.name} at {backend.url}")
    except Exception as e:
        logger.error(f"Failed to detect or connect to backend: {e}")
        sys.exit(1)

    # 4. Initialize Core Components
    horde = HordeAPI(
        api_key=config.horde.api_key, 
        url=config.horde.url, 
        worker_name=config.worker.name,
        version=VERSION
    )
    
    stats = WorkerStats()
    shutdown_event = asyncio.Event()

    # 5. Initialize Health Monitor
    health_monitor = HealthMonitor(backend, horde, config, stats)
    health_monitor.start()

    # 6. Initialize Worker Threads
    worker_threads = []
    for i in range(config.worker.max_threads):
        worker = WorkerThread(
            thread_id=i, 
            horde=horde, 
            backend=backend, 
            config=config, 
            stats=stats,
            health_monitor=health_monitor,
            shutdown_event=shutdown_event
        )
        worker_threads.append(asyncio.create_task(worker.run()))

    # 7. Signal Handling for Graceful Shutdown
    def handle_exit():
        if not shutdown_event.is_set():
            logger.info("SHUTDOWN REQUESTED. Cleaning up current jobs...")
            shutdown_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_exit)
    else:
        # On Windows, we need a different approach for signals, but for now...
        pass

    # 8. Main Loop / Wait for Termination
    try:
        # Wait until all worker tasks are done
        await asyncio.gather(*worker_threads)
    except asyncio.CancelledError:
        pass
    finally:
        # 9. Cleanup
        logger.info("Closing API sessions...")
        await health_monitor.stop()
        await horde.close()
        await backend.close()
        
        # Summary
        summary = stats.to_summary_str()
        logger.info(f"Worker shutdown complete. Final Summary: {summary}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass # Handled by signal handler mostly
