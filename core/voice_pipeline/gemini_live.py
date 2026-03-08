"""Gemini Live API voice pipeline — raw WebSocket implementation.

Connects directly to the Gemini Live API WebSocket endpoint, bypassing
the google-genai SDK which has a bug causing immediate session closure
with native audio models.  Protocol follows the same JSON message format
used by the official Angular reference implementation:
  https://github.com/gsans/gemini-2-live-angular

Audio format:
  Input  (mic → Gemini):  PCM int16, 16 kHz, mono, base64-encoded in JSON
  Output (Gemini → speaker): PCM int16, 24 kHz, mono, base64 in JSON
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import yaml
from dotenv import load_dotenv

from .base import ToolCallRequest, VoicePipelineBase

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_settings_cache: Optional[dict] = None


def _load_settings() -> dict:
    global _settings_cache
    if _settings_cache is None:
        settings_path = _PROJECT_ROOT / "config" / "settings.yaml"
        with open(settings_path, "r") as f:
            _settings_cache = yaml.safe_load(f)
        logger.debug("Loaded settings from %s", settings_path)
    return _settings_cache


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEMINI_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha."
    "GenerativeService.BidiGenerateContent"
)

EMOTION_TAG_SYSTEM_PROMPT = """\
You are Domino, a friendly voice assistant. Always respond in English.

Before every response, begin with a single emotion tag in brackets that \
describes your current tone. Choose from this list only:
[excited] [happy] [sad] [thinking] [confused] [laughing] [surprised] [calm] \
[alert] [tired] [sarcastic] [neutral] [curious] [proud] [concerned] [angry] \
[roasting]

The tag must be the very first thing in your text response, before any \
other content.
Example: [curious] That's an interesting question...\
"""

TOOL_DECLARATIONS = [
    {
        "functionDeclarations": [
            {
                "name": "play_music",
                "description": "Play a song, artist, album, or playlist on Spotify",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
            },
            {"name": "pause_music", "description": "Pause Spotify playback"},
            {"name": "skip_track", "description": "Skip to next track"},
            {"name": "previous_track", "description": "Go to previous track"},
            {
                "name": "set_volume",
                "description": "Set Spotify volume",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "integer", "description": "Volume 0-100"}
                    },
                    "required": ["level"],
                },
            },
            {"name": "now_playing", "description": "Get currently playing track info"},
            {
                "name": "set_timer",
                "description": "Set a countdown timer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_seconds": {"type": "integer"},
                        "label": {"type": "string"},
                    },
                    "required": ["duration_seconds"],
                },
            },
            {"name": "get_time", "description": "Get current time"},
            {"name": "get_date", "description": "Get current date"},
        ]
    },
    {"googleSearch": {}},
]


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class GeminiLivePipeline(VoicePipelineBase):
    """Voice pipeline using raw WebSocket to the Gemini Live API.

    Bypasses the google-genai SDK (which has a bug causing immediate
    session closure with native audio models) and connects directly
    using the same protocol as the Angular reference implementation.
    """

    def __init__(self) -> None:
        super().__init__()

        settings = _load_settings()
        voice_cfg = settings.get("voice", {})

        self._model: str = voice_cfg.get(
            "model", "gemini-2.5-flash-native-audio-preview-12-2025"
        )
        self._max_retries: int = int(voice_cfg.get("reconnect_max_retries", 5))
        self._base_delay: float = float(voice_cfg.get("reconnect_base_delay", 1.0))

        # API keys
        self._primary_key: str = os.environ.get("GOOGLE_API_KEY", "")
        self._fallback_key: str = os.environ.get("GOOGLE_FALLBACK_API_KEY", "")
        if not self._primary_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. Add it to .env."
            )
        self._active_key: str = self._primary_key
        self._using_fallback: bool = False

        # WebSocket connection
        self._ws = None  # websockets.WebSocketClientProtocol

        # Internal queues
        self._audio_out_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._text_out_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        # Background receive task
        self._receive_task: Optional[asyncio.Task] = None

        # Pending tool calls
        self._pending_tool_calls: set[str] = set()

    # --- Lifecycle ---

    async def start(self) -> None:
        if self._connected:
            logger.warning("start() called but pipeline is already connected")
            return
        await self._connect_with_retry()

    async def stop(self) -> None:
        logger.info("Stopping Gemini Live pipeline")
        self._connected = False

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Exception closing WebSocket (ignored)", exc_info=True)
            self._ws = None

        await self._audio_out_queue.put(None)
        await self._text_out_queue.put(None)

        self._session_id = ""
        self._pending_tool_calls.clear()
        logger.info("Gemini Live pipeline stopped")

    # --- Audio streaming ---

    async def send_audio(self, chunk: bytes) -> None:
        """Send PCM int16 audio chunk to Gemini as base64-encoded JSON."""
        if not self._connected or self._ws is None:
            raise ConnectionError("Cannot send audio: pipeline is not connected")
        try:
            audio_b64 = base64.b64encode(chunk).decode("ascii")
            msg = {
                "realtimeInput": {
                    "mediaChunks": [
                        {
                            "mimeType": "audio/pcm;rate=16000",
                            "data": audio_b64,
                        }
                    ]
                }
            }
            await self._ws.send(json.dumps(msg))
        except Exception as exc:
            logger.error("Error sending audio: %s", exc)
            await self._handle_disconnect(exc)

    async def receive_audio(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._audio_out_queue.get()
            if chunk is None:
                break
            yield chunk

    async def receive_text(self) -> AsyncIterator[str]:
        while True:
            text = await self._text_out_queue.get()
            if text is None:
                break
            yield text

    # --- Tool communication ---

    async def send_tool_response(self, call_id: str, result: dict) -> None:
        if not self._connected or self._ws is None:
            raise ConnectionError("Cannot send tool response: not connected")
        if call_id not in self._pending_tool_calls:
            raise ValueError(
                f"Unknown tool call ID: {call_id}. "
                f"Pending: {self._pending_tool_calls}"
            )

        self._pending_tool_calls.discard(call_id)
        logger.debug("Sending tool response for call_id=%s", call_id)

        try:
            msg = {
                "toolResponse": {
                    "functionResponses": [
                        {"id": call_id, "response": result}
                    ]
                }
            }
            await self._ws.send(json.dumps(msg))
        except Exception as exc:
            logger.error("Error sending tool response: %s", exc)
            await self._handle_disconnect(exc)

    # --- Internal: connection ---

    def _build_setup_message(self) -> dict:
        """Build the setup message matching the Angular reference protocol."""
        return {
            "setup": {
                "model": f"models/{self._model}",
                "generationConfig": {
                    "responseModalities": "audio",
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": "Kore",
                            }
                        },
                        "languageCode": "en-US",
                    },
                },
                "systemInstruction": {
                    "parts": [{"text": EMOTION_TAG_SYSTEM_PROMPT}]
                },
                "tools": TOOL_DECLARATIONS,
            }
        }

    async def _connect_with_retry(self) -> None:
        import websockets

        delay = self._base_delay

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(
                    "Connecting to Gemini Live API (attempt %d/%d, "
                    "model=%s, fallback=%s)",
                    attempt, self._max_retries,
                    self._model, self._using_fallback,
                )

                url = f"{GEMINI_WS_URL}?key={self._active_key}"
                self._ws = await websockets.connect(url)
                logger.debug("WebSocket connected, sending setup...")

                # Send setup message
                setup = self._build_setup_message()
                await self._ws.send(json.dumps(setup))

                # Wait for setupComplete
                resp_raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
                if isinstance(resp_raw, bytes):
                    resp_raw = resp_raw.decode("utf-8")
                resp = json.loads(resp_raw)

                if "setupComplete" not in resp:
                    raise RuntimeError(
                        f"Expected setupComplete, got: {json.dumps(resp)[:200]}"
                    )

                self._connected = True
                self._session_id = uuid.uuid4().hex[:12]
                logger.info(
                    "Connected to Gemini Live API (session=%s, model=%s)",
                    self._session_id, self._model,
                )

                # Start receive loop
                self._receive_task = asyncio.create_task(
                    self._receive_loop(),
                    name=f"gemini-receive-{self._session_id}",
                )
                return

            except Exception as exc:
                is_rate_limit = _is_rate_limit_error(exc)

                if is_rate_limit and not self._using_fallback and self._fallback_key:
                    logger.warning(
                        "Rate limited on primary key. Switching to fallback."
                    )
                    self._active_key = self._fallback_key
                    self._using_fallback = True

                if attempt == self._max_retries:
                    logger.error(
                        "Failed to connect after %d attempts: %s",
                        self._max_retries, exc,
                    )
                    raise ConnectionError(
                        f"Could not connect to Gemini Live API "
                        f"after {self._max_retries} attempts"
                    ) from exc

                logger.warning(
                    "Attempt %d failed (%s). Retrying in %.1fs...",
                    attempt, exc, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _handle_disconnect(self, exc: Exception) -> None:
        if not self._connected:
            return

        logger.warning("Gemini Live session disconnected: %s", exc)
        self._connected = False

        if _is_rate_limit_error(exc) and not self._using_fallback:
            if self._fallback_key:
                self._active_key = self._fallback_key
                self._using_fallback = True

        await self._audio_out_queue.put(None)
        await self._text_out_queue.put(None)

        self._audio_out_queue = asyncio.Queue()
        self._text_out_queue = asyncio.Queue()

        try:
            await self._connect_with_retry()
        except ConnectionError:
            logger.error("Reconnection failed. Pipeline remains disconnected.")

    # --- Internal: receive loop ---

    async def _receive_loop(self) -> None:
        """Read JSON messages from the Gemini WebSocket and dispatch."""
        if self._ws is None:
            return

        try:
            async for raw in self._ws:
                if not self._connected:
                    break

                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON message from Gemini: %s", raw[:100])
                    continue

                await self._dispatch_message(data)

        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
            raise

        except Exception as exc:
            if self._connected:
                logger.error("Receive loop error: %s (%s)", exc, type(exc).__name__)
                await self._handle_disconnect(exc)
            return

        if self._connected:
            logger.info("Gemini Live stream ended. Attempting reconnect.")
            await self._handle_disconnect(ConnectionError("Stream ended by server"))

    async def _dispatch_message(self, data: dict) -> None:
        """Route a JSON message from Gemini to the correct queue."""

        # --- Server content (audio, text, turn signals) ---
        if "serverContent" in data:
            sc = data["serverContent"]

            # Model turn with parts (audio and/or text)
            model_turn = sc.get("modelTurn")
            if model_turn and "parts" in model_turn:
                for part in model_turn["parts"]:
                    part_keys = list(part.keys())
                    # Inline audio data
                    if "inlineData" in part:
                        inline = part["inlineData"]
                        mime = inline.get("mimeType", "")
                        b64_data = inline.get("data", "")
                        logger.debug(
                            "Received audio part: mime=%s, data_len=%d",
                            mime, len(b64_data),
                        )
                        if mime.startswith("audio/pcm") and b64_data:
                            pcm_bytes = base64.b64decode(b64_data)
                            await self._audio_out_queue.put(pcm_bytes)
                        elif b64_data:
                            # Try decoding anyway for non-pcm audio
                            logger.warning(
                                "Unexpected audio mime: %s — trying decode anyway",
                                mime,
                            )
                            pcm_bytes = base64.b64decode(b64_data)
                            await self._audio_out_queue.put(pcm_bytes)
                    # Text
                    if "text" in part:
                        text = part["text"]
                        logger.debug("Received text part: %s", text[:100])
                        await self._text_out_queue.put(text)
                        await self.text_queue.put(text)
                    # Log unknown part types
                    if not any(k in part for k in ("inlineData", "text")):
                        logger.debug("Unknown part keys: %s", part_keys)

            # Output transcription (native audio models emit this)
            output_tx = sc.get("outputTranscription")
            if output_tx and "text" in output_tx:
                text = output_tx["text"]
                logger.debug("Output transcription: %s", text[:100])
                await self._text_out_queue.put(text)
                await self.text_queue.put(text)

            if sc.get("turnComplete"):
                logger.debug("Server turn complete")
                # Signal end-of-turn to audio consumer (empty bytes sentinel)
                await self._audio_out_queue.put(b"")

            if sc.get("interrupted"):
                logger.debug("Server response interrupted by user input")

            return

        # --- Tool calls ---
        if "toolCall" in data:
            for fc in data["toolCall"].get("functionCalls", []):
                call_id = fc.get("id") or uuid.uuid4().hex[:16]
                name = fc.get("name", "")
                args = fc.get("args", {})

                logger.info("Tool call: %s(%s) [id=%s]", name, args, call_id)
                self._pending_tool_calls.add(call_id)

                request = ToolCallRequest(call_id=call_id, name=name, args=args)
                await self.tool_queue.put(request)
            return

        # --- Tool call cancellation ---
        if "toolCallCancellation" in data:
            for cid in data["toolCallCancellation"].get("ids", []):
                self._pending_tool_calls.discard(cid)
                logger.info("Tool call cancelled: %s", cid)
            return

        # --- Setup complete (handled in connect, shouldn't appear here) ---
        if "setupComplete" in data:
            return

        # Unknown message type
        logger.debug("Unhandled Gemini message keys: %s", list(data.keys()))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_rate_limit_error(exc: Exception) -> bool:
    exc_str = str(exc).lower()
    if "429" in exc_str or "resource exhausted" in exc_str:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status == 429
