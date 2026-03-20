import asyncio
import logging
import signal
import sys
import time
from .core.config import load_config
from .core.logger import setup_logging
from .core.horde_api import HordeAPI
from .core.health import HealthMonitor
from .core.stats import StatsAggregator
from .backends.adapters import detect_backend
from .worker import WorkerThread, WorkerStats
from .webui.server import WebUI

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

        # 3.2 Apply model_name_override if set — overrides any auto-resolved names
        if config.backend.model_name_override:
            logger.info(f"Applying model_name_override: '{config.backend.model_name_override}'")
            config.worker.models_to_serve = [config.backend.model_name_override]

        # 3.3 Auto-resolve max_context_length if possible
        backend_ctx = await backend.get_max_context()
        if backend_ctx:
            if backend_ctx < config.worker.max_context_length:
                logger.warning(
                    f"Backend context ({backend_ctx}) is LOWER than config "
                    f"max_context_length ({config.worker.max_context_length}). "
                    f"Adjusting to backend limit to avoid errors."
                )
                config.worker.max_context_length = backend_ctx
            elif backend_ctx > config.worker.max_context_length:
                logger.info(
                    f"Backend supports larger context ({backend_ctx}) than "
                    f"config ({config.worker.max_context_length}). Using config limit."
                )
            else:
                logger.info(f"Backend context matches config: {backend_ctx} tokens.")
        else:
            logger.info(
                f"Backend did not report a context size. "
                f"Using config fallback: {config.worker.max_context_length} tokens."
            )

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
    aggregator = StatsAggregator()
    shutdown_event = asyncio.Event()

    # 4.1 Initialize WebUI
    webui = None
    if config.worker.webui_enabled:
        webui = WebUI(aggregator, shutdown_event, port=config.worker.webui_port)
        await webui.start()

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
            shutdown_event=shutdown_event,
            aggregator=aggregator
        )
        worker_threads.append(asyncio.create_task(worker.run()))
        
    # 6.1 Snapshot Loop (for WebUI chart permanence)
    async def snapshot_loop():
        while not shutdown_event.is_set():
            aggregator.take_snapshot()
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=60.0) # Snapshot every minute
            except asyncio.TimeoutError:
                pass
    
    snapshot_task = asyncio.create_task(snapshot_loop())

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
        await asyncio.gather(snapshot_task, *worker_threads)
    except asyncio.CancelledError:
        pass
    finally:
        # 9. Cleanup
        logger.info("Closing API sessions...")
        if webui:
            await webui.stop()
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
