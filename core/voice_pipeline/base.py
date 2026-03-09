"""Abstract base class for DV3 voice pipeline backends.

The voice pipeline abstraction is the core architectural pattern of DV3.
All consumer code (visualizer, tools, emotion parser) imports only from this
module. Concrete implementations (gemini_live, modular) are selected and
instantiated in main.py based on settings.yaml `voice.backend`.

Communication between the pipeline and the rest of the application happens
through three asyncio.Queue channels:
    - emotion_queue: emotion tag strings for the visualizer
    - tool_queue: tool call requests for the tool dispatcher
    - text_queue: raw text chunks for the emotion parser
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRequest:
    """A tool call emitted by the voice backend.

    Attributes:
        call_id: Unique identifier for this call, used to correlate the
            response back to the backend.
        name: Function name as declared in the tool config.
        args: Dictionary of arguments parsed from the backend's request.
    """

    call_id: str
    name: str
    args: dict = field(default_factory=dict)


class VoicePipelineBase(ABC):
    """Abstract interface for a voice pipeline backend.

    Subclasses must implement all abstract methods. The pipeline lifecycle
    follows a strict sequence:

        pipeline = SomeBackend(config)
        await pipeline.start()      # establish connection
        # ... stream audio, receive responses ...
        await pipeline.stop()       # graceful shutdown

    Event queues are created at construction time and are safe to read
    from consumer coroutines before start() is called -- they will simply
    block until the pipeline begins producing events.
    """

    def __init__(self) -> None:
        # --- Event queues for cross-component communication ---
        # Emotion tags (str) consumed by the visualizer.
        self.emotion_queue: asyncio.Queue[str] = asyncio.Queue()
        # Tool call requests consumed by the tool dispatcher.
        self.tool_queue: asyncio.Queue[ToolCallRequest] = asyncio.Queue()
        # Raw text chunks consumed by the emotion parser.
        self.text_queue: asyncio.Queue[str] = asyncio.Queue()

        # Turn completion signal — set when backend signals end-of-turn,
        # cleared when new content arrives.  Used by the app to detect
        # conversation idle and return to wake word detection.
        self.turn_complete_event: asyncio.Event = asyncio.Event()

        # Internal state
        self._connected: bool = False
        self._session_id: str = ""

    # --- Properties ---

    @property
    def is_connected(self) -> bool:
        """Whether the backend session is currently active and connected."""
        return self._connected

    @property
    def session_id(self) -> str:
        """Identifier for the current backend session, or empty string."""
        return self._session_id

    # --- Lifecycle ---

    @abstractmethod
    async def start(self) -> None:
        """Initialize the backend session.

        Opens any network connections, authenticates, and prepares the
        pipeline for audio streaming. After this method returns, the
        pipeline should be ready to accept send_audio() calls.

        Raises:
            ConnectionError: If the backend cannot be reached.
            RuntimeError: If required configuration is missing.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Perform a clean shutdown of the backend session.

        Closes network connections, cancels pending tasks, and releases
        resources. Safe to call multiple times. After stop() returns,
        is_connected must be False.
        """
        ...

    # --- Audio streaming ---

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send a chunk of microphone audio to the backend.

        Audio format is PCM 16-bit signed integer, 16 kHz sample rate,
        mono channel. Chunk size is determined by the caller (typically
        the wake word detector's frame size).

        Args:
            chunk: Raw PCM audio bytes.

        Raises:
            ConnectionError: If the session is not connected.
        """
        ...

    @abstractmethod
    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Stream audio response chunks from the backend.

        Yields PCM 16-bit 16 kHz mono audio chunks as they arrive from
        the backend's TTS output. The iterator completes when the
        backend signals end of turn.

        Yields:
            Raw PCM audio bytes.
        """
        # This must be overridden as an async generator.
        # The yield below is unreachable and exists only to satisfy
        # the type checker that this is an AsyncIterator.
        yield b""  # pragma: no cover

    @abstractmethod
    async def receive_text(self) -> AsyncIterator[str]:
        """Stream text response chunks from the backend.

        Yields text fragments as they arrive from the backend's LLM
        output. These are also placed on self.text_queue for the
        emotion parser. The iterator completes when the backend
        signals end of turn.

        Yields:
            Text fragment strings.
        """
        yield ""  # pragma: no cover

    # --- Tool communication ---

    @abstractmethod
    async def send_tool_response(self, call_id: str, result: dict) -> None:
        """Return the result of a tool call to the backend.

        After the tool dispatcher executes a tool, it calls this method
        to feed the result back into the backend so the LLM can
        incorporate it into the ongoing response.

        Args:
            call_id: The call_id from the original ToolCallRequest.
            result: Dictionary containing the tool's output.

        Raises:
            ConnectionError: If the session is not connected.
            ValueError: If call_id does not match a pending tool call.
        """
        ...
