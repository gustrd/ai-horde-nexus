import os
import asyncio
import logging
from aiohttp import web
from src.core.stats import StatsAggregator

logger = logging.getLogger("horde.webui")

class WebUI:
    def __init__(self, aggregator: StatsAggregator, shutdown_event: asyncio.Event, host: str = "0.0.0.0", port: int = 8082):
        self.aggregator = aggregator
        self.shutdown_event = shutdown_event
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        
        # Setup routes
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/api/stats", self.handle_stats)
        self.app.router.add_get("/api/jobs/active", self.handle_active)
        self.app.router.add_get("/api/jobs/history", self.handle_history)
        self.app.router.add_post("/api/control", self.handle_control)
        
        # Static files
        static_path = os.path.join(os.path.dirname(__file__), "static")
        self.app.router.add_static("/static/", static_path)

    async def handle_index(self, request):
        index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="WebUI index.html not found", status=404)

    async def handle_stats(self, request):
        return web.json_response(self.aggregator.get_summary())

    async def handle_active(self, request):
        return web.json_response(self.aggregator.get_active_list())

    async def handle_history(self, request):
        return web.json_response(self.aggregator.get_history_list())

    async def handle_control(self, request):
        try:
            data = await request.json()
            action = data.get("action")
            if action == "pause":
                self.aggregator.paused = True
            elif action == "resume":
                self.aggregator.paused = False
            elif action == "shutdown":
                logger.info("WebUI requested Worker Shutdown.")
                self.shutdown_event.set()
            else:
                return web.json_response({"error": f"Invalid action: {action}"}, status=400)
            return web.json_response({"status": "ok", "paused": self.aggregator.paused})
        except Exception as e:
            logger.error(f"WebUI control error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        logger.info(f"WebUI started at http://{self.host}:{self.port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            logger.info("WebUI stopped.")
