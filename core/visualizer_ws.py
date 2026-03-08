"""WebSocket server for broadcasting emotion/state events to the web visualizer."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Set

from aiohttp import web

logger = logging.getLogger(__name__)


class VisualizerWSServer:
    """Lightweight WS server — emits events, visualizer clients subscribe."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._clients: Set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/ws", self._ws_handler)
        self._runner: Optional[web.AppRunner] = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Visualizer WS server started at ws://%s:%d/ws", self._host, self._port)

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    async def emit_emotion(self, emotion: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "emotion", "emotion": emotion, "theme": theme})

    async def emit_state(self, state: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "state", "state": state, "theme": theme})

    async def emit_tag(self, tag: str) -> None:
        await self._broadcast({"type": "tag", "tag": tag})

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(payload)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.debug("Visualizer client connected (%d total)", len(self._clients))
        try:
            async for _ in ws:
                pass
        finally:
            self._clients.discard(ws)
            logger.debug("Visualizer client disconnected (%d remaining)", len(self._clients))
        return ws
