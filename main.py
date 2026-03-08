"""DV3 Voice Companion -- application orchestrator.

Single entry point that ties together wake word detection, the Gemini Live
voice pipeline, emotion-driven animation, and tool dispatch.  Runs with
asyncio coordination for audio I/O, WebSocket communication, and
inter-component queues.

By default runs in headless mode — no Pygame window.  The web visualizer
at visualizer-web/ connects via WebSocket to receive emotion events.
Pass ``--pygame`` to enable the legacy Pygame display.

State machine:
    IDLE  ->  LISTENING  ->  CONVERSATION  ->  IDLE
       ^                                       |
       +---------------------------------------+

Usage:
    python main.py            # headless (web visualizer only)
    python main.py --debug    # verbose logging
    python main.py --pygame   # legacy Pygame display
    python main.py --pygame --windowed  # Pygame in windowed mode
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import signal
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from core.visualizer_ws import VisualizerWSServer

import numpy as np
import yaml
from dotenv import load_dotenv

# Pygame is optional — only needed with --pygame flag
try:
    import pygame
except ImportError:
    pygame = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Project root -- all relative paths resolve from here.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Logging setup (configured further in _configure_logging)
# ---------------------------------------------------------------------------
logger = logging.getLogger("dv3")

# ---------------------------------------------------------------------------
# Application states
# ---------------------------------------------------------------------------
STATE_IDLE = "IDLE"
STATE_LISTENING = "LISTENING"
STATE_CONVERSATION = "CONVERSATION"

# ---------------------------------------------------------------------------
# Emotion tag regex -- used by the inline fallback parser only
# ---------------------------------------------------------------------------
_EMOTION_TAG_RE = re.compile(r"^\[(\w+)\]")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(overrides: Optional[dict] = None) -> dict:
    """Load settings.yaml and merge with .env environment variables.

    Args:
        overrides: Optional dict of overrides to merge on top of the
            loaded config (e.g. from CLI flags).

    Returns:
        The merged configuration dictionary.
    """
    # Load .env into os.environ
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug("Loaded environment from %s", env_path)

    # Load settings.yaml
    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    config: dict = {}
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        logger.debug("Loaded settings from %s", settings_path)
    else:
        logger.warning("Settings file not found: %s", settings_path)

    if overrides:
        config.update(overrides)

    return config


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def _configure_logging(debug: bool = False) -> None:
    """Set up root logging with timestamps and module names."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s  %(levelname)-8s  %(name)-22s  %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)

    # Quiet noisy third-party loggers
    for noisy in ("PIL", "urllib3", "google", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Audio output helper -- plays PCM via sounddevice
# ---------------------------------------------------------------------------


def _find_output_device(sd, prefer_pulse: bool) -> Optional[int]:
    """Find a PulseAudio output device, similar to wake_word._find_input_device."""
    if not prefer_pulse:
        return None
    try:
        devices = sd.query_devices()
        items = (
            devices
            if hasattr(devices, "__iter__") and not isinstance(devices, dict)
            else [devices]
        )
        for dev in items:
            if (
                isinstance(dev, dict)
                and dev.get("name", "").lower() == "pulse"
                and dev.get("max_output_channels", 0) > 0
            ):
                logger.info(
                    "WSL2 audio: selected PulseAudio output device index=%d ('%s')",
                    dev["index"],
                    dev["name"],
                )
                return dev["index"]
    except Exception:
        logger.debug("Output device enumeration failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Emotion parsing -- thin adapter around core.emotion_parser
# ---------------------------------------------------------------------------


class _EmotionResult:
    """Result from feeding text to the emotion adapter."""

    __slots__ = ("emotion", "contextual_tag")

    def __init__(
        self,
        emotion: Optional[str] = None,
        contextual_tag: Optional[str] = None,
    ) -> None:
        self.emotion = emotion
        self.contextual_tag = contextual_tag


class _InlineEmotionAdapter:
    """Thin wrapper that gives the real EmotionParser a simple feed/reset API.

    The ``core.emotion_parser.EmotionParser`` uses an async
    ``process_stream`` interface.  This adapter exposes a simpler
    synchronous ``feed(text) -> _EmotionResult`` / ``reset()`` interface
    that the text receive loop can call directly, one chunk at a time.
    """

    def __init__(self, config: dict) -> None:
        emotion_cfg = config.get("emotion", {})
        self._buffer_tokens: int = int(
            emotion_cfg.get("tag_buffer_tokens", 30)
        )
        self._default: str = emotion_cfg.get("default_emotion", "neutral")
        self._buffer: str = ""
        self._emitted: bool = False
        self._emitted_tags: set = set()

        # Load the real parser for its detection methods.
        try:
            from core.emotion_parser import EmotionParser as _RealParser
            self._parser = _RealParser()
            logger.info("Using core.emotion_parser.EmotionParser")
        except Exception:
            logger.warning(
                "core.emotion_parser not available; using inline fallback"
            )
            self._parser = None

    def reset(self) -> None:
        """Clear the buffer for a new turn."""
        self._buffer = ""
        self._emitted = False
        self._emitted_tags.clear()

    def feed(self, text: str) -> _EmotionResult:
        """Feed a text chunk and return detected emotion/tag info.

        Returns:
            An _EmotionResult with emotion and/or contextual_tag populated
            when detected, or both None if not yet determined.
        """
        self._buffer += text
        tokens = self._buffer.split()
        result = _EmotionResult()

        # Check for contextual triggers on every chunk (even after emotion emitted)
        if self._parser is not None:
            ctx = self._parser.parse_contextual(self._buffer)
            if ctx is not None:
                tag_key = ctx.get("category", "unknown")
                if tag_key not in self._emitted_tags:
                    self._emitted_tags.add(tag_key)
                    result.contextual_tag = tag_key
                    logger.info("Contextual trigger: %s", tag_key)

        if self._emitted:
            return result

        # Only evaluate once we have enough tokens or see a closing bracket
        if len(tokens) < min(self._buffer_tokens, 3) and "]" not in text:
            return result

        if self._parser is not None:
            # Use the real parser's detection methods.
            emotion = self._parser.parse_tag(self._buffer.strip())
            if emotion is not None:
                self._emitted = True
                result.emotion = emotion
                return result

            if len(tokens) >= self._buffer_tokens:
                emotion = self._parser.parse_keywords(self._buffer)
                if emotion is not None:
                    self._emitted = True
                    result.emotion = emotion
                    return result
                self._emitted = True
                result.emotion = self._default
                return result
        else:
            # Inline fallback (no core.emotion_parser available).
            match = _EMOTION_TAG_RE.search(self._buffer.strip())
            if match:
                self._emitted = True
                result.emotion = match.group(1).lower()
                return result

            if len(tokens) >= self._buffer_tokens:
                self._emitted = True
                result.emotion = self._default
                return result

        return result


# ---------------------------------------------------------------------------
# DV3App -- main application class
# ---------------------------------------------------------------------------


class DV3App:
    """DV3 Voice Companion application orchestrator.

    Manages the lifecycle of all subsystems and runs the main Pygame
    render loop with asyncio coordination.
    """

    def __init__(self, config: dict, *, use_pygame: bool = False) -> None:
        self.config = config
        self.state: str = STATE_IDLE
        self._use_pygame = use_pygame and pygame is not None

        # Shutdown coordination
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        # Components -- initialized in setup()
        self.display = None
        self.animation_engine = None
        self.gradient = None
        self.emotion_mapper = None
        self.emotion_parser: Optional[EmotionParser] = None
        self.wake_word: Optional[WakeWordDetector] = None
        self.pipeline: Optional[VoicePipelineBase] = None
        self.tool_dispatcher: Optional[ToolDispatcher] = None
        self.ws_server: Optional[VisualizerWSServer] = None

        # Audio output
        self._audio_output_stream = None
        self._sd = None

        # Current emotion for visualizer
        self._current_emotion: str = ""

        # Pygame surface (only used with --pygame)
        self._screen = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Initialize all subsystems.

        Must be called before run(). In headless mode (default) only the
        WS server, voice pipeline, and wake word detector are started.
        Pass ``--pygame`` to enable the legacy Pygame display.
        """
        logger.info("=== DV3 Voice Companion starting ===")
        logger.info("Mode: %s", "pygame" if self._use_pygame else "headless (web visualizer)")

        vis_cfg = self.config.get("visualizer", {})

        # ---- Pygame display (only with --pygame) ----
        if self._use_pygame:
            from visualizer.display import DisplayManager
            self.display = DisplayManager(vis_cfg)
            self._screen = self.display.init_display()

            from visualizer.animation_engine import AnimationEngine
            self.animation_engine = AnimationEngine(vis_cfg)

            self._grad_cfg = vis_cfg.get("gradient", {})
            from visualizer.gradient_overlay import GradientOverlay
            self.gradient = None
            self._GradientOverlay = GradientOverlay

        # ---- Emotion mapper (manifest-only, needed for WS events too) ----
        from visualizer.emotion_map import EmotionMapper
        manifest_path = PROJECT_ROOT / "animations" / "manifest.json"
        self.emotion_mapper = EmotionMapper(str(manifest_path))
        if self.emotion_mapper.asset_count() == 0:
            logger.warning(
                "No animations loaded — manifest missing or empty at %s. "
                "Tag animations in the editor and save to populate it.",
                manifest_path,
            )

        # ---- WebSocket event server ----
        ws_port = self.config.get("visualizer_ws_port", 8765)
        self.ws_server = VisualizerWSServer(host="0.0.0.0", port=ws_port)
        await self.ws_server.start()
        logger.info("Visualizer WS server started on port %d", ws_port)

        # ---- Load initial (neutral) animation / emit initial event ----
        self._set_emotion("neutral", crossfade=False)
        if self._use_pygame and self.animation_engine._animation is not None:
            logger.info(
                "Initial animation loaded: %s (%d frames)",
                self.animation_engine._animation.path,
                self.animation_engine._animation.frame_count,
            )
        elif self._use_pygame:
            logger.warning("No initial animation loaded — display will be black")

        # ---- Emotion parser ----
        self.emotion_parser = _InlineEmotionAdapter(self.config)

        # ---- Tool dispatcher ----
        from tools.tool_dispatcher import ToolDispatcher
        self.tool_dispatcher = ToolDispatcher()

        # ---- Voice pipeline ----
        backend = self.config.get("voice", {}).get("backend", "gemini_live")
        if backend == "gemini_live":
            from core.voice_pipeline.gemini_live import GeminiLivePipeline
            self.pipeline = GeminiLivePipeline()
        elif backend == "modular":
            from core.voice_pipeline.modular import ModularPipeline
            self.pipeline = ModularPipeline()
        else:
            raise RuntimeError(f"Unknown voice backend: {backend}")
        logger.info("Voice backend: %s", backend)

        # ---- Wake word detector ----
        from core.wake_word import WakeWordDetector
        config_path = str(PROJECT_ROOT / "config" / "settings.yaml")
        # In headless mode, feed browser mic audio (from WS) into wake word
        ext_queue = self.ws_server.audio_in_queue if not self._use_pygame else None
        self.wake_word = WakeWordDetector(
            config_path=config_path,
            on_detected=self._on_wake_word_detected,
            external_audio_queue=ext_queue,
        )

        # ---- Audio output ----
        if self._use_pygame:
            self._setup_audio_output()
        else:
            # Headless: TTS audio goes out via WS to the browser
            logger.info("Audio output: WebSocket (browser playback)")

        logger.info("=== Setup complete ===")

    def _setup_audio_output(self) -> None:
        """Configure the sounddevice output stream for Gemini TTS playback."""
        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            logger.error(
                "sounddevice is not installed -- audio output disabled"
            )
            return

        audio_cfg = self.config.get("audio", {})
        voice_cfg = self.config.get("voice", {})
        sample_rate = int(voice_cfg.get("sample_rate", 16000))
        prefer_pulse = bool(audio_cfg.get("prefer_pulse", True))
        output_device = audio_cfg.get("output_device")

        if output_device is None and prefer_pulse:
            output_device = _find_output_device(sd, prefer_pulse)

        try:
            self._audio_output_stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=output_device,
            )
            self._audio_output_stream.start()
            logger.info(
                "Audio output stream opened: sr=%d, channels=1, "
                "dtype=int16, device=%s",
                sample_rate,
                output_device,
            )
        except Exception:
            logger.exception("Failed to open audio output stream")
            self._audio_output_stream = None

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main application loop.

        Runs setup, starts background tasks, then enters the Pygame
        render loop.  Exits cleanly on ESC, window close, or Ctrl+C.
        """
        await self.setup()

        # Install signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_shutdown)
            except NotImplementedError:
                # Windows does not support add_signal_handler
                pass

        # Start background tasks
        self._tasks.append(
            asyncio.create_task(
                self._wake_word_loop(), name="wake-word-loop"
            )
        )

        logger.info("Entering main loop (state=%s)", self.state)

        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        finally:
            await self._shutdown()

    async def _main_loop(self) -> None:
        """Main event loop.

        In headless mode, simply yields to asyncio so background tasks
        (wake word, conversation, tool dispatch) can run.  With --pygame,
        also pumps the Pygame render loop.
        """
        while not self._shutdown_event.is_set():
            if self._use_pygame:
                # ---- Pygame event pump ----
                if self.display.should_quit():
                    logger.info("Quit requested via Pygame event")
                    self._shutdown_event.set()
                    break

                # ---- Update animation ----
                dt = self.display.tick()
                if self.animation_engine is not None:
                    self.animation_engine.update(dt)
                    frame = self.animation_engine.get_current_frame()

                    if frame is not None and self.gradient is not None:
                        gradient_surf = self.gradient.get_surface()
                        self.display.render_frame(
                            self._screen, frame, gradient_surf
                        )

                pygame.display.flip()
                await asyncio.sleep(0)
            else:
                # Headless — just keep the event loop alive
                await asyncio.sleep(0.05)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _set_state(self, new_state: str) -> None:
        """Transition to a new application state with logging."""
        old_state = self.state
        self.state = new_state
        logger.info("State transition: %s -> %s", old_state, new_state)

    # ------------------------------------------------------------------
    # Wake word loop
    # ------------------------------------------------------------------

    async def _wake_word_loop(self) -> None:
        """Continuously listen for the wake word and start conversations.

        Runs as a background task for the lifetime of the application.
        Each detection triggers a conversation session; when the
        conversation ends, returns to listening.
        """
        try:
            await self.wake_word.start()
        except Exception:
            logger.exception("Failed to start wake word detector")
            return

        try:
            while not self._shutdown_event.is_set():
                if self.state != STATE_IDLE:
                    # Not our turn -- wait a bit and check again
                    await asyncio.sleep(0.1)
                    continue

                try:
                    confidence = await self.wake_word.wait_for_detection()
                    logger.info(
                        "Wake word detected (confidence=%.3f)", confidence
                    )
                except RuntimeError:
                    # Detector was stopped
                    if self._shutdown_event.is_set():
                        break
                    logger.warning("Wake word detector stopped unexpectedly")
                    await asyncio.sleep(1.0)
                    continue

                # Transition to LISTENING briefly (visual feedback)
                self._set_state(STATE_LISTENING)
                self._set_emotion("alert", crossfade=True)

                # Brief delay for the alert animation to show
                await asyncio.sleep(0.3)

                # Start conversation
                await self._start_conversation()

        except asyncio.CancelledError:
            pass
        finally:
            await self.wake_word.stop()

    def _on_wake_word_detected(self, confidence: float) -> None:
        """Callback from WakeWordDetector -- just logs.

        The actual state transition happens in _wake_word_loop after
        wait_for_detection() returns.
        """
        logger.debug("Wake word callback fired (confidence=%.3f)", confidence)

    # ------------------------------------------------------------------
    # Conversation management
    # ------------------------------------------------------------------

    async def _start_conversation(self) -> None:
        """Run a single conversation session with the Gemini pipeline.

        Connects to the pipeline, streams microphone audio, processes
        responses (audio, text, tool calls), and returns to IDLE when
        the conversation ends.
        """
        self._set_state(STATE_CONVERSATION)

        if self.emotion_parser is not None:
            self.emotion_parser.reset()

        try:
            await self.pipeline.start()
        except (ConnectionError, RuntimeError) as exc:
            logger.error("Failed to start voice pipeline: %s", exc)
            self._set_state(STATE_IDLE)
            self._set_emotion("neutral", crossfade=True)
            return

        # Start conversation sub-tasks
        conversation_tasks: list[asyncio.Task] = []
        try:
            conversation_tasks.append(
                asyncio.create_task(
                    self._mic_stream_loop(), name="mic-stream"
                )
            )
            conversation_tasks.append(
                asyncio.create_task(
                    self._audio_receive_loop(), name="audio-receive"
                )
            )
            conversation_tasks.append(
                asyncio.create_task(
                    self._text_receive_loop(), name="text-receive"
                )
            )
            conversation_tasks.append(
                asyncio.create_task(
                    self._tool_dispatch_loop(), name="tool-dispatch"
                )
            )

            # Wait until any of them completes (normally the receive
            # loops end when Gemini signals turn_complete with no further
            # audio, or when shutdown is requested).
            done, pending = await asyncio.wait(
                conversation_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Check for exceptions in completed tasks
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.error(
                        "Conversation task '%s' failed: %s",
                        task.get_name(),
                        exc,
                    )

        except asyncio.CancelledError:
            logger.info("Conversation cancelled")

        finally:
            # Cancel remaining conversation tasks
            for task in conversation_tasks:
                if not task.done():
                    task.cancel()

            # Wait for cancellation to propagate
            if conversation_tasks:
                await asyncio.gather(
                    *conversation_tasks, return_exceptions=True
                )

            # Stop the pipeline
            try:
                await self.pipeline.stop()
            except Exception:
                logger.exception("Error stopping pipeline")

            # Return to idle
            self._set_state(STATE_IDLE)
            self._set_emotion("neutral", crossfade=True)

            if self.emotion_parser is not None:
                self.emotion_parser.reset()

            logger.info("Conversation ended")

    # ------------------------------------------------------------------
    # Conversation sub-tasks
    # ------------------------------------------------------------------

    async def _mic_stream_loop(self) -> None:
        """Stream microphone audio to the Gemini pipeline.

        Reads PCM float32 chunks from the wake word detector's audio
        queue and converts them to int16 PCM before sending to the
        pipeline.  Runs until shutdown or the pipeline disconnects.
        """
        if self.wake_word is None or not self.wake_word._running:
            logger.warning("Wake word detector not running; mic stream unavailable")
            return

        audio_queue = self.wake_word._audio_queue

        # Drain stale audio that accumulated during pipeline connection.
        # These are old chunks (silence, tail of wake word) that would
        # confuse Gemini if sent as a burst.
        drained = 0
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.debug("Drained %d stale audio chunks before mic streaming", drained)

        chunks_sent = 0
        while (
            not self._shutdown_event.is_set()
            and self.state == STATE_CONVERSATION
            and self.pipeline.is_connected
        ):
            try:
                chunk_f32 = await asyncio.wait_for(
                    audio_queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue

            # Convert float32 [-1, 1] -> int16 PCM bytes
            int16_data = (chunk_f32 * 32767).astype(np.int16)
            pcm_bytes = int16_data.tobytes()

            try:
                await self.pipeline.send_audio(pcm_bytes)
                chunks_sent += 1
                if chunks_sent <= 3 or chunks_sent % 50 == 0:
                    logger.debug(
                        "Sent audio chunk #%d to Gemini (%d bytes, rms=%.4f)",
                        chunks_sent, len(pcm_bytes),
                        np.sqrt(np.mean(chunk_f32 ** 2)),
                    )
            except ConnectionError:
                logger.warning("Pipeline disconnected during mic streaming")
                break
            except Exception:
                logger.exception("Error sending audio to pipeline")
                break

        logger.debug("Mic stream loop ended (sent %d chunks total)", chunks_sent)

    async def _audio_receive_loop(self) -> None:
        """Receive and play audio responses from Gemini.

        In headless mode, sends PCM chunks to the browser via WebSocket.
        With --pygame, writes to the sounddevice output stream.
        """
        use_ws = not self._use_pygame and self.ws_server is not None
        use_sd = self._audio_output_stream is not None

        if not use_ws and not use_sd:
            logger.warning("No audio output available; consuming silently")
            async for _chunk in self.pipeline.receive_audio():
                pass
            return

        try:
            async for chunk in self.pipeline.receive_audio():
                if self._shutdown_event.is_set():
                    break
                try:
                    if use_ws:
                        await self.ws_server.send_audio(chunk)
                    elif use_sd:
                        self._audio_output_stream.write(chunk)
                except Exception:
                    logger.exception("Error writing audio output")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in audio receive loop")

    async def _text_receive_loop(self) -> None:
        """Receive text responses from Gemini and parse emotions.

        Reads text fragments from the pipeline's text iterator, feeds
        them to the emotion parser, and updates the visualizer when
        an emotion or contextual trigger is detected.  Completes when
        the pipeline signals end of turn.
        """
        try:
            async for text in self.pipeline.receive_text():
                if self._shutdown_event.is_set():
                    break

                if self.emotion_parser is not None:
                    result = self.emotion_parser.feed(text)
                    if result.emotion is not None:
                        logger.info("Emotion detected: %s", result.emotion)
                        self._set_emotion(result.emotion, crossfade=True)
                    if result.contextual_tag is not None and self.ws_server:
                        logger.info(
                            "Emitting contextual tag to visualizer: %s",
                            result.contextual_tag,
                        )
                        asyncio.create_task(
                            self.ws_server.emit_tag(result.contextual_tag)
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in text receive loop")

    async def _tool_dispatch_loop(self) -> None:
        """Dispatch tool calls from Gemini and return results.

        Reads ToolCallRequests from the pipeline's tool_queue, dispatches
        them via the ToolDispatcher, and sends results back to the
        pipeline so Gemini can incorporate them.
        """
        while (
            not self._shutdown_event.is_set()
            and self.state == STATE_CONVERSATION
            and self.pipeline.is_connected
        ):
            try:
                request = await asyncio.wait_for(
                    self.pipeline.tool_queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue

            logger.info(
                "Dispatching tool: %s(%s) [id=%s]",
                request.name,
                request.args,
                request.call_id,
            )

            try:
                result = await self.tool_dispatcher.dispatch(
                    request.name, request.args
                )
            except Exception:
                logger.exception("Tool dispatch failed for %s", request.name)
                result = {
                    "success": False,
                    "message": f"Internal error executing {request.name}",
                }

            try:
                await self.pipeline.send_tool_response(
                    request.call_id, result
                )
            except (ConnectionError, ValueError) as exc:
                logger.error("Failed to send tool response: %s", exc)
            except Exception:
                logger.exception("Error sending tool response")

    # ------------------------------------------------------------------
    # Emotion -> Animation
    # ------------------------------------------------------------------

    def _set_emotion(self, emotion: str, *, crossfade: bool = True) -> None:
        """Update the visualizer to display an animation for *emotion*.

        In headless mode, emits the emotion via WebSocket so the web
        visualizer handles rendering.  With --pygame, also loads the
        Pygame animation.
        """
        if emotion == self._current_emotion and not crossfade:
            return

        self._current_emotion = emotion

        # ---- Pygame animation (only with --pygame) ----
        if self._use_pygame and self.animation_engine is not None:
            anim_path = self._resolve_animation_path(emotion)
            if anim_path is None:
                logger.warning(
                    "No animation file for emotion '%s'; keeping current",
                    emotion,
                )
            else:
                try:
                    animation = self.animation_engine.load_animation(anim_path)
                except (FileNotFoundError, ValueError) as exc:
                    logger.error("Failed to load animation %s: %s", anim_path, exc)
                    animation = None

                if animation is not None:
                    if self.gradient is None and animation.frames:
                        native_size = animation.frames[0].size
                        anim_rect = self.display.get_animation_rect(native_size)
                        self.animation_engine.set_target_size(
                            (anim_rect.width, anim_rect.height)
                        )
                        self.gradient = self._GradientOverlay(
                            size=(anim_rect.width, anim_rect.height),
                            opacity=self._grad_cfg.get("opacity", 60),
                            gradient_size=self._grad_cfg.get("size", 70),
                        )
                        logger.info(
                            "Animation target: %dx%d (from %dx%d source)",
                            anim_rect.width, anim_rect.height,
                            native_size[0], native_size[1],
                        )

                    if crossfade:
                        self.animation_engine.crossfade_to(animation)
                    else:
                        self.animation_engine.set_animation(animation)

        # ---- WebSocket event (always) ----
        if self.ws_server:
            asyncio.create_task(self.ws_server.emit_emotion(emotion, theme="dark"))

        logger.debug("Emotion set: '%s' (crossfade=%s)", emotion, crossfade)

    def _resolve_animation_path(self, emotion: str) -> Optional[str]:
        """Resolve an emotion string to an animation file path.

        Uses the EmotionMapper if available, otherwise falls back to
        a direct directory scan.
        """
        return self.emotion_mapper.get_animation_path(emotion, theme="dark")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _signal_shutdown(self) -> None:
        """Signal handler for SIGINT/SIGTERM -- trigger graceful shutdown."""
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Graceful shutdown of all subsystems."""
        logger.info("Shutting down DV3...")

        self._shutdown_event.set()

        # Cancel background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Stop pipeline
        if self.pipeline is not None and self.pipeline.is_connected:
            try:
                await self.pipeline.stop()
            except Exception:
                logger.exception("Error stopping pipeline")

        # Stop tool dispatcher
        if self.tool_dispatcher is not None:
            try:
                await self.tool_dispatcher.shutdown()
            except Exception:
                logger.exception("Error shutting down tool dispatcher")

        # Stop wake word detector
        if self.wake_word is not None:
            try:
                await self.wake_word.stop()
            except Exception:
                logger.exception("Error stopping wake word detector")

        # Close audio output stream
        if self._audio_output_stream is not None:
            try:
                self._audio_output_stream.stop()
                self._audio_output_stream.close()
            except Exception:
                logger.exception("Error closing audio output stream")
            self._audio_output_stream = None

        # Stop WebSocket event server
        if self.ws_server is not None:
            try:
                await self.ws_server.stop()
            except Exception:
                logger.exception("Error stopping WebSocket server")
            self.ws_server = None

        # Cleanup Pygame display (only with --pygame)
        if self._use_pygame and self.display is not None:
            self.display.cleanup()

        logger.info("=== DV3 shutdown complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="DV3 Voice Companion",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--pygame",
        action="store_true",
        help="Enable legacy Pygame display (default: headless, web visualizer only)",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Force windowed Pygame display (implies --pygame)",
    )
    return parser.parse_args()


def main() -> None:
    """Application entry point."""
    args = parse_args()
    _configure_logging(debug=args.debug)

    use_pygame = args.pygame or args.windowed

    # Build config with CLI overrides
    overrides: dict = {}
    if args.windowed:
        overrides.setdefault("visualizer", {})["fullscreen"] = False

    config = load_config(overrides=overrides)

    if args.windowed:
        vis = config.setdefault("visualizer", {})
        vis["fullscreen"] = False

    app = DV3App(config, use_pygame=use_pygame)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        # asyncio.run catches SIGINT and raises KeyboardInterrupt
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
