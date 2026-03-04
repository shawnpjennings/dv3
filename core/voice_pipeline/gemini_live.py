"""Gemini Live API voice pipeline implementation.

Connects to Google's Gemini Live API via the google-genai SDK's async
WebSocket interface. Handles bidirectional audio streaming, text response
parsing, tool call dispatching, and automatic reconnection with
exponential backoff.

Audio format: PCM 16-bit signed integer, 16 kHz sample rate, mono channel.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

from .base import ToolCallRequest, VoicePipelineBase

logger = logging.getLogger(__name__)

# Load environment variables from .env in project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

_settings_cache: Optional[dict] = None


def _load_settings() -> dict:
    """Load and cache settings.yaml from the config directory."""
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

EMOTION_TAG_SYSTEM_PROMPT = """\
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
        "function_declarations": [
            {
                "name": "play_music",
                "description": (
                    "Play a song, artist, album, or playlist on Spotify"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "pause_music",
                "description": "Pause Spotify playback",
            },
            {
                "name": "skip_track",
                "description": "Skip to next track",
            },
            {
                "name": "previous_track",
                "description": "Go to previous track",
            },
            {
                "name": "set_volume",
                "description": "Set Spotify volume",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": "Volume 0-100",
                        }
                    },
                    "required": ["level"],
                },
            },
            {
                "name": "now_playing",
                "description": "Get currently playing track info",
            },
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
            {
                "name": "get_time",
                "description": "Get current time",
            },
            {
                "name": "get_date",
                "description": "Get current date",
            },
        ]
    },
    {"google_search": {}},
]

AUDIO_MIME_TYPE = "audio/pcm;rate=16000"


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class GeminiLivePipeline(VoicePipelineBase):
    """Voice pipeline backed by the Gemini Live API.

    Uses the google-genai async client to maintain a persistent WebSocket
    session with Gemini. Audio is streamed bidirectionally -- microphone
    PCM chunks go in via send_audio(), and Gemini's TTS audio comes back
    through receive_audio().

    Text responses are emitted on the text_queue for the emotion parser.
    Tool calls are emitted on the tool_queue for the tool dispatcher.

    Configuration is read from config/settings.yaml under the ``voice``
    key. API keys come from environment variables GOOGLE_API_KEY
    (primary) and GOOGLE_FALLBACK_API_KEY (secondary).
    """

    def __init__(self) -> None:
        super().__init__()

        settings = _load_settings()
        voice_cfg = settings.get("voice", {})

        # Model and reconnection settings from config.
        self._model: str = voice_cfg.get(
            "model", "gemini-2.5-flash-native-audio-preview"
        )
        self._max_retries: int = int(
            voice_cfg.get("reconnect_max_retries", 5)
        )
        self._base_delay: float = float(
            voice_cfg.get("reconnect_base_delay", 1.0)
        )

        # API keys.
        self._primary_key: str = os.environ.get("GOOGLE_API_KEY", "")
        self._fallback_key: str = os.environ.get(
            "GOOGLE_FALLBACK_API_KEY", ""
        )
        if not self._primary_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Add it to your .env file."
            )
        self._active_key: str = self._primary_key
        self._using_fallback: bool = False

        # Client and session references -- set during start().
        self._client: Optional[genai.Client] = None
        self._session: Optional[genai.types.AsyncSession] = None

        # Internal queues for bridging the receive loop to iterators.
        self._audio_out_queue: asyncio.Queue[Optional[bytes]] = (
            asyncio.Queue()
        )
        self._text_out_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        # Background task running the receive loop.
        self._receive_task: Optional[asyncio.Task] = None

        # Track pending tool calls so we can validate responses.
        self._pending_tool_calls: set[str] = set()

    # --- Lifecycle ---

    async def start(self) -> None:
        """Connect to the Gemini Live API and begin the receive loop.

        On failure, retries with exponential backoff up to max_retries.
        On HTTP 429, switches to the fallback API key before retrying.
        """
        if self._connected:
            logger.warning("start() called but pipeline is already connected")
            return

        await self._connect_with_retry()

    async def stop(self) -> None:
        """Shut down the session and cancel background tasks."""
        logger.info("Stopping Gemini Live pipeline")
        self._connected = False

        # Cancel the receive loop.
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # Close the session.
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                logger.debug("Exception closing session (ignored)", exc_info=True)
            self._session = None

        # Signal iterators that we are done.
        await self._audio_out_queue.put(None)
        await self._text_out_queue.put(None)

        self._client = None
        self._session_id = ""
        self._pending_tool_calls.clear()
        logger.info("Gemini Live pipeline stopped")

    # --- Audio streaming ---

    async def send_audio(self, chunk: bytes) -> None:
        """Send a PCM audio chunk to the Gemini Live session."""
        if not self._connected or self._session is None:
            raise ConnectionError(
                "Cannot send audio: pipeline is not connected"
            )
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=AUDIO_MIME_TYPE)
            )
        except Exception as exc:
            logger.error("Error sending audio: %s", exc)
            # Trigger reconnection on send failure.
            await self._handle_disconnect(exc)

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield PCM audio chunks from Gemini's TTS output.

        Completes when the session ends or stop() is called.
        """
        while True:
            chunk = await self._audio_out_queue.get()
            if chunk is None:
                break
            yield chunk

    async def receive_text(self) -> AsyncIterator[str]:
        """Yield text fragments from Gemini's LLM output.

        Completes when the session ends or stop() is called.
        """
        while True:
            text = await self._text_out_queue.get()
            if text is None:
                break
            yield text

    # --- Tool communication ---

    async def send_tool_response(self, call_id: str, result: dict) -> None:
        """Return the result of a tool execution to Gemini.

        Args:
            call_id: The ID from the original ToolCallRequest.
            result: Dictionary with the tool's output.

        Raises:
            ConnectionError: If the session is not connected.
            ValueError: If call_id is not a pending tool call.
        """
        if not self._connected or self._session is None:
            raise ConnectionError(
                "Cannot send tool response: pipeline is not connected"
            )

        if call_id not in self._pending_tool_calls:
            raise ValueError(
                f"Unknown tool call ID: {call_id}. "
                f"Pending calls: {self._pending_tool_calls}"
            )

        self._pending_tool_calls.discard(call_id)
        logger.debug("Sending tool response for call_id=%s", call_id)

        try:
            await self._session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        id=call_id,
                        name="",  # SDK resolves the name from the ID.
                        response=result,
                    )
                ]
            )
        except Exception as exc:
            logger.error("Error sending tool response: %s", exc)
            await self._handle_disconnect(exc)

    # --- Internal: connection management ---

    def _build_config(self) -> dict:
        """Build the Live API session configuration dictionary."""
        return {
            "response_modalities": ["AUDIO", "TEXT"],
            "system_instruction": EMOTION_TAG_SYSTEM_PROMPT,
            "tools": TOOL_DECLARATIONS,
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": "Kore",
                    }
                }
            },
        }

    async def _connect_with_retry(self) -> None:
        """Attempt to connect with exponential backoff.

        On HTTP 429 (rate limit), switches to the fallback API key
        before the next retry attempt.
        """
        delay = self._base_delay

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(
                    "Connecting to Gemini Live API (attempt %d/%d, "
                    "model=%s, fallback=%s)",
                    attempt,
                    self._max_retries,
                    self._model,
                    self._using_fallback,
                )

                self._client = genai.Client(api_key=self._active_key)
                config = self._build_config()

                # The connect() context manager returns an async session.
                # We enter it manually so the session persists beyond this
                # method -- __aexit__ is called in stop().
                self._session = await self._client.aio.live.connect(
                    model=self._model, config=config
                ).__aenter__()

                self._connected = True
                self._session_id = uuid.uuid4().hex[:12]
                logger.info(
                    "Connected to Gemini Live API (session=%s)",
                    self._session_id,
                )

                # Start the background receive loop.
                self._receive_task = asyncio.create_task(
                    self._receive_loop(),
                    name=f"gemini-receive-{self._session_id}",
                )
                return

            except Exception as exc:
                is_rate_limit = _is_rate_limit_error(exc)

                if is_rate_limit and not self._using_fallback:
                    logger.warning(
                        "Rate limited (429) on primary key. "
                        "Switching to fallback key."
                    )
                    if self._fallback_key:
                        self._active_key = self._fallback_key
                        self._using_fallback = True
                    else:
                        logger.error(
                            "No GOOGLE_FALLBACK_API_KEY configured. "
                            "Cannot switch keys."
                        )

                if attempt == self._max_retries:
                    logger.error(
                        "Failed to connect after %d attempts: %s",
                        self._max_retries,
                        exc,
                    )
                    raise ConnectionError(
                        f"Could not connect to Gemini Live API "
                        f"after {self._max_retries} attempts"
                    ) from exc

                logger.warning(
                    "Connection attempt %d failed (%s). "
                    "Retrying in %.1fs...",
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _handle_disconnect(self, exc: Exception) -> None:
        """Handle an unexpected disconnection during operation.

        Marks the pipeline as disconnected, signals output iterators,
        and attempts to reconnect.
        """
        if not self._connected:
            return  # Already handling a disconnect.

        logger.warning("Gemini Live session disconnected: %s", exc)
        self._connected = False

        if _is_rate_limit_error(exc) and not self._using_fallback:
            logger.info(
                "Rate limited during session. Switching to fallback key."
            )
            if self._fallback_key:
                self._active_key = self._fallback_key
                self._using_fallback = True

        # Signal current iterators to stop (they will get None sentinel).
        await self._audio_out_queue.put(None)
        await self._text_out_queue.put(None)

        # Replace queues so new iterators after reconnect start clean.
        self._audio_out_queue = asyncio.Queue()
        self._text_out_queue = asyncio.Queue()

        try:
            await self._connect_with_retry()
        except ConnectionError:
            logger.error(
                "Reconnection failed. Pipeline remains disconnected."
            )

    # --- Internal: receive loop ---

    async def _receive_loop(self) -> None:
        """Background task that reads messages from the Gemini session.

        Routes incoming data to the appropriate queues:
        - Audio bytes  -> _audio_out_queue
        - Text strings -> _text_out_queue + text_queue (emotion parser)
        - Tool calls   -> tool_queue
        """
        if self._session is None:
            return

        try:
            async for message in self._session.receive():
                if not self._connected:
                    break

                await self._dispatch_message(message)

        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
            raise

        except Exception as exc:
            if self._connected:
                logger.error("Receive loop error: %s", exc)
                await self._handle_disconnect(exc)
            return

        # If we exit the loop normally (server closed the stream),
        # treat it as a disconnection.
        if self._connected:
            logger.info("Gemini Live stream ended. Attempting reconnect.")
            await self._handle_disconnect(
                ConnectionError("Stream ended by server")
            )

    async def _dispatch_message(self, message: types.LiveServerMessage) -> None:
        """Route a single LiveServerMessage to the correct queue."""

        # --- Audio data ---
        # The SDK surfaces raw audio bytes via message.data when the
        # server sends inline audio blobs.
        if message.data is not None:
            await self._audio_out_queue.put(message.data)
            return

        # --- Tool calls ---
        if message.tool_call is not None:
            for fc in message.tool_call.function_calls:
                call_id = fc.id or uuid.uuid4().hex[:16]
                name = fc.name or ""
                # The SDK provides args as a dict or None.
                args = dict(fc.args) if fc.args else {}

                logger.info(
                    "Tool call received: %s(%s) [id=%s]",
                    name,
                    args,
                    call_id,
                )
                self._pending_tool_calls.add(call_id)

                request = ToolCallRequest(
                    call_id=call_id, name=name, args=args
                )
                await self.tool_queue.put(request)
            return

        # --- Server content (text, turn signals) ---
        if message.server_content is not None:
            sc = message.server_content

            # Text from the model turn.
            if sc.model_turn and sc.model_turn.parts:
                for part in sc.model_turn.parts:
                    if part.text:
                        await self._text_out_queue.put(part.text)
                        await self.text_queue.put(part.text)
                    # Inline audio can also arrive inside parts.
                    if (
                        part.inline_data
                        and part.inline_data.data
                        and isinstance(part.inline_data.data, bytes)
                    ):
                        await self._audio_out_queue.put(
                            part.inline_data.data
                        )

            # Output transcription (text representation of audio output).
            if sc.output_transcription and sc.output_transcription.text:
                text = sc.output_transcription.text
                await self._text_out_queue.put(text)
                await self.text_queue.put(text)

            # Turn complete signal.
            if sc.turn_complete:
                logger.debug("Server turn complete")
                # Sentinel so iterators for this turn can finish.
                await self._audio_out_queue.put(None)
                await self._text_out_queue.put(None)

            # Interrupted -- the user started speaking mid-response.
            if sc.interrupted:
                logger.debug("Server response interrupted by user input")

            return

        # --- Tool call cancellation ---
        if hasattr(message, "tool_call_cancellation") and message.tool_call_cancellation:
            cancelled_ids = getattr(
                message.tool_call_cancellation, "ids", []
            )
            for cid in cancelled_ids:
                self._pending_tool_calls.discard(cid)
                logger.info("Tool call cancelled: %s", cid)
            return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check whether an exception represents an HTTP 429 rate limit."""
    exc_str = str(exc).lower()
    if "429" in exc_str or "resource exhausted" in exc_str:
        return True
    # google-genai wraps HTTP errors; check status code if available.
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429:
        return True
    return False
