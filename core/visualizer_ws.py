"""WebSocket server for the DV3 web visualizer.

Handles two concerns:
1. Broadcasting emotion/state/tag events (JSON text) to visualizer clients.
2. Bidirectional audio streaming — browser mic audio in (binary), Gemini
   TTS audio out (binary) — so the full voice pipeline works through the
   browser without needing PulseAudio/sounddevice on the host.

Audio protocol (binary messages):
- Browser → Server: raw PCM int16, 16 kHz mono chunks
- Server → Browser: raw PCM int16, 16 kHz mono chunks (prefixed with 1-byte
  message type: 0x01 = audio data)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Set

import numpy as np
from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)


class VisualizerWSServer:
    """WS server — emits events, receives browser mic audio, sends TTS audio."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._clients: Set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/ws", self._ws_handler)
        self._runner: Optional[web.AppRunner] = None

        # Audio queue: browser mic PCM arrives here as float32 numpy arrays
        # (same format as wake_word._audio_queue for drop-in compatibility).
        self.audio_in_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._audio_chunk_count = 0
        # Only accept mic audio from one client (first to connect).
        # Prevents doubling from React StrictMode dual connections.
        self._audio_source_ws: Optional[web.WebSocketResponse] = None

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

    # --- Outbound events (JSON) ---

    async def emit_emotion(self, emotion: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "emotion", "emotion": emotion, "theme": theme})

    async def emit_state(self, state: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "state", "state": state, "theme": theme})

    async def emit_tag(self, tag: str) -> None:
        await self._broadcast({"type": "tag", "tag": tag})

    async def emit_wakeword(self, confidence: float) -> None:
        await self._broadcast({"type": "wakeword", "confidence": float(confidence)})

    # --- Outbound audio (binary) ---

    async def send_audio(self, pcm_int16_bytes: bytes) -> None:
        """Send TTS audio to ONE connected browser client.

        Only sends to the first client to prevent doubling when React
        StrictMode (or multiple tabs) creates duplicate WS connections.
        The bytes are raw PCM int16, 24 kHz mono.  We prepend a 1-byte
        type header (0x01) so the browser can distinguish audio from
        other binary messages.
        """
        if not self._clients:
            return
        payload = b'\x01' + pcm_int16_bytes
        # Send to first client only — prevents audio doubling
        ws = next(iter(self._clients))
        try:
            await ws.send_bytes(payload)
        except Exception:
            self._clients.discard(ws)

    # --- Internal ---

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
        ws = web.WebSocketResponse(max_msg_size=1024 * 1024)
        await ws.prepare(request)
        self._clients.add(ws)
        # First client to connect becomes the audio source
        is_audio_source = self._audio_source_ws is None
        if is_audio_source:
            self._audio_source_ws = ws
        logger.debug(
            "Visualizer client connected (%d total, audio_source=%s)",
            len(self._clients), is_audio_source,
        )
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    # Only accept mic audio from the designated source
                    if ws is self._audio_source_ws:
                        self._handle_audio_in(msg.data)
                elif msg.type == WSMsgType.TEXT:
                    # Could be JSON commands from browser in the future
                    pass
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
            if ws is self._audio_source_ws:
                self._audio_source_ws = None
            logger.debug("Visualizer client disconnected (%d remaining)", len(self._clients))
        return ws

    def _handle_audio_in(self, data: bytes) -> None:
        """Convert incoming PCM int16 bytes to float32 numpy and enqueue."""
        try:
            int16_arr = np.frombuffer(data, dtype=np.int16)
            float32_arr = int16_arr.astype(np.float32) / 32767.0
            self._audio_chunk_count += 1
            rms = float(np.sqrt(np.mean(float32_arr ** 2)))
            if self._audio_chunk_count <= 3 or self._audio_chunk_count % 500 == 0 or rms > 0.01:
                logger.debug(
                    "Audio chunk #%d received (%d samples, rms=%.4f, queue=%d)",
                    self._audio_chunk_count, len(float32_arr), rms,
                    self.audio_in_queue.qsize(),
                )
            try:
                self.audio_in_queue.put_nowait(float32_arr)
            except asyncio.QueueFull:
                # Drop oldest chunk to prevent unbounded lag
                try:
                    self.audio_in_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self.audio_in_queue.put_nowait(float32_arr)
        except Exception:
            logger.debug("Failed to process incoming audio chunk", exc_info=True)
