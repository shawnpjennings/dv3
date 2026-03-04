"""Modular voice pipeline stub -- future implementation.

This backend will compose individual open-source components into a
complete voice pipeline:

    OpenWakeWord  -> local wake word detection
    Whisper       -> speech-to-text (local or API)
    Custom LLM   -> language model (local or API, e.g. Ollama / OpenAI)
    ElevenLabs    -> text-to-speech via ElevenLabs API

This exists as a placeholder to validate that the VoicePipelineBase
abstraction is complete enough to support a non-Gemini backend.
The interface contract is identical to GeminiLivePipeline -- consumers
do not know or care which backend is active.

To activate this backend, set ``voice.backend: modular`` in
config/settings.yaml.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from .base import VoicePipelineBase

logger = logging.getLogger(__name__)


class ModularPipeline(VoicePipelineBase):
    """Modular pipeline: WakeWord + STT + LLM + TTS as separate services.

    Not yet implemented. All methods raise NotImplementedError with a
    message indicating the planned component.
    """

    async def start(self) -> None:
        """Initialize all sub-components (WakeWord, STT, LLM, TTS)."""
        raise NotImplementedError(
            "ModularPipeline is not yet implemented. "
            "Planned components: OpenWakeWord, Whisper, custom LLM, "
            "ElevenLabs TTS."
        )

    async def stop(self) -> None:
        """Shut down all sub-components."""
        raise NotImplementedError("ModularPipeline.stop() not implemented")

    async def send_audio(self, chunk: bytes) -> None:
        """Route audio to local WakeWord detector, then STT."""
        raise NotImplementedError(
            "ModularPipeline.send_audio() not implemented"
        )

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Stream TTS audio from ElevenLabs."""
        raise NotImplementedError(
            "ModularPipeline.receive_audio() not implemented"
        )
        yield b""  # pragma: no cover -- unreachable, satisfies AsyncIterator

    async def receive_text(self) -> AsyncIterator[str]:
        """Stream text from the LLM."""
        raise NotImplementedError(
            "ModularPipeline.receive_text() not implemented"
        )
        yield ""  # pragma: no cover -- unreachable, satisfies AsyncIterator

    async def send_tool_response(self, call_id: str, result: dict) -> None:
        """Forward tool result to the LLM for continued generation."""
        raise NotImplementedError(
            "ModularPipeline.send_tool_response() not implemented"
        )
