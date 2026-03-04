"""Wake word detector using OpenWakeWord with WSL2-safe audio capture.

Audio approach (critical for WSL2 reliability):
- sounddevice (not PyAudio) with PulseAudio backend preferred over ALSA
- Threaded stream open with 4-second timeout as safety net against hangs
- 16kHz mono, float32 -> int16 conversion
- Device detection: scan for 'pulse' device, fall back to system default

Pattern replicated from ~/projects/thumper/ wakeword implementation.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — these pull in heavy native libs, so we defer until needed.
# ---------------------------------------------------------------------------

_sd = None
_oww_Model = None


def _import_sounddevice():
    """Lazy-import sounddevice to avoid loading at module level."""
    global _sd
    if _sd is None:
        import sounddevice as sd
        _sd = sd
    return _sd


def _import_openwakeword():
    """Lazy-import openwakeword Model to avoid loading at module level."""
    global _oww_Model
    if _oww_Model is None:
        from openwakeword.model import Model
        _oww_Model = Model
    return _oww_Model


# ---------------------------------------------------------------------------
# WSL2 audio helpers
# ---------------------------------------------------------------------------


def _find_input_device(sd) -> Optional[int]:
    """Prefer 'pulse' PortAudio backend over ALSA default in WSL2.

    Scans all available audio devices and returns the index of the first
    PulseAudio input device found. Returns ``None`` to use the system
    default if no PulseAudio device is available.
    """
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
                and dev.get("max_input_channels", 0) > 0
            ):
                logger.info(
                    "WSL2 audio: selected PulseAudio input device index=%d ('%s')",
                    dev["index"],
                    dev["name"],
                )
                return dev["index"]
    except Exception:
        logger.debug("Device enumeration failed; will use system default", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# WakeWordDetector
# ---------------------------------------------------------------------------


class WakeWordDetector:
    """Async wake-word gate using OpenWakeWord.

    Parameters
    ----------
    config_path : str
        Path to the project settings.yaml file.  Wake-word settings are read
        from the ``wake_word`` and ``audio`` sections.
    on_detected : callable, optional
        Synchronous or coroutine callback invoked with the confidence score
        each time the wake word is detected.
    """

    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        on_detected: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.on_detected = on_detected

        # ── Load configuration ──────────────────────────────────────────
        cfg = self._load_config(config_path)
        ww_cfg = cfg.get("wake_word", {})
        audio_cfg = cfg.get("audio", {})

        self._model_path: str = ww_cfg.get("model_path", "temp/wakeword/Hey_Domino.onnx")
        self._threshold: float = float(ww_cfg.get("detection_threshold", 0.5))
        self._sample_rate: int = int(ww_cfg.get("sample_rate", 16000))
        self._chunk_size: int = int(ww_cfg.get("chunk_size", 1280))
        self._prefer_pulse: bool = bool(audio_cfg.get("prefer_pulse", True))
        self._configured_device = audio_cfg.get("input_device")  # None = auto

        # ── Runtime state ───────────────────────────────────────────────
        self._audio_queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._stream = None  # sounddevice.InputStream
        self._model = None  # openwakeword Model
        self._running: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info(
            "WakeWordDetector configured: model=%s, threshold=%.2f, "
            "sample_rate=%d, chunk=%d, prefer_pulse=%s",
            self._model_path,
            self._threshold,
            self._sample_rate,
            self._chunk_size,
            self._prefer_pulse,
        )

    # ── Configuration ───────────────────────────────────────────────────

    @staticmethod
    def _load_config(path: str) -> dict:
        """Load and return the YAML settings file."""
        config_path = Path(path)
        if not config_path.exists():
            logger.warning("Settings file not found at %s; using defaults", path)
            return {}
        with open(config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}

    # ── Public API ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Load the model and open the audio stream.

        Raises
        ------
        FileNotFoundError
            If the ONNX model file does not exist.
        RuntimeError
            If the audio stream fails to open within the timeout.
        """
        if self._running:
            logger.warning("WakeWordDetector.start() called while already running")
            return

        self._loop = asyncio.get_running_loop()

        # ── Load model ──────────────────────────────────────────────────
        model_file = Path(self._model_path)
        if not model_file.exists():
            raise FileNotFoundError(
                f"Wake-word model not found: {model_file.resolve()}"
            )

        Model = _import_openwakeword()
        self._model = Model(
            wakeword_models=[str(model_file)],
            inference_framework="onnx",
        )
        logger.info("OpenWakeWord model loaded from %s", model_file)

        # ── Open audio stream (threaded with timeout) ───────────────────
        self._open_audio_stream()
        self._running = True
        logger.info("WakeWordDetector started — listening for wake word")

    async def stop(self) -> None:
        """Stop listening and release the audio device."""
        self._running = False
        self._close_audio_stream()
        self._model = None
        logger.info("WakeWordDetector stopped")

    async def wait_for_detection(self) -> float:
        """Block until the wake word is detected.

        Returns
        -------
        float
            The detection confidence score (0.0 -- 1.0).

        Raises
        ------
        RuntimeError
            If the detector has not been started.
        """
        if not self._running or self._model is None:
            raise RuntimeError(
                "Detector is not running. Call start() before wait_for_detection()."
            )

        logger.debug("Waiting for wake-word detection (threshold=%.2f)...", self._threshold)

        while self._running:
            try:
                # Wait for an audio chunk with a short timeout so we can
                # check self._running periodically.
                chunk = await asyncio.wait_for(
                    self._audio_queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue

            # ── Run inference ────────────────────────────────────────────
            confidence = await self._loop.run_in_executor(
                None, self._predict, chunk
            )

            if confidence is not None and confidence >= self._threshold:
                logger.info("Wake word DETECTED (confidence=%.3f)", confidence)

                # Fire callback if registered.
                if self.on_detected is not None:
                    try:
                        result = self.on_detected(confidence)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("Error in on_detected callback")

                # Reset model state so it doesn't immediately re-trigger.
                self._model.reset()
                return confidence

        raise RuntimeError("Detector stopped while waiting for detection")

    # ── Audio stream management ─────────────────────────────────────────

    def _open_audio_stream(self) -> None:
        """Open a sounddevice InputStream in a daemon thread with timeout.

        The threaded open is a safety net against WSL2/ALSA hangs that can
        block indefinitely when PortAudio probes unavailable devices.
        """
        sd = _import_sounddevice()

        # Resolve input device.
        input_device = self._configured_device
        if input_device is None and self._prefer_pulse:
            input_device = _find_input_device(sd)
        if input_device is None:
            logger.info("Using system default input device")
        else:
            logger.info("Using input device: %s", input_device)

        # We need the loop reference for the callback's call_soon_threadsafe.
        loop = self._loop
        queue = self._audio_queue

        def _audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            """sounddevice stream callback -- runs in the audio thread."""
            if status:
                logger.warning("Audio stream status: %s", status)
            # indata is float32 in [-1, 1].  Copy to avoid buffer reuse.
            chunk = indata[:, 0].copy()
            # Enqueue via the event loop (thread-safe).
            try:
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception:
                pass  # Queue full or loop closed — drop the chunk.

        # Open stream in a daemon thread to avoid blocking the event loop.
        stream_holder: list = []
        open_error: list = []

        def _open():
            try:
                stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=self._chunk_size,
                    callback=_audio_callback,
                    device=input_device,
                )
                stream.start()
                stream_holder.append(stream)
            except Exception as exc:
                open_error.append(exc)

        open_thread = threading.Thread(target=_open, daemon=True)
        open_thread.start()
        open_thread.join(timeout=4.0)

        if open_thread.is_alive():
            logger.error(
                "Audio stream open timed out after 4 seconds — "
                "likely an ALSA/PulseAudio issue in WSL2"
            )
            raise RuntimeError(
                "Timed out opening audio stream. "
                "Ensure PulseAudio is running in WSL2."
            )

        if open_error:
            raise RuntimeError(
                f"Failed to open audio stream: {open_error[0]}"
            ) from open_error[0]

        if not stream_holder:
            raise RuntimeError("Audio stream open returned no stream object")

        self._stream = stream_holder[0]
        logger.info(
            "Audio stream opened: sr=%d, channels=1, blocksize=%d, device=%s",
            self._sample_rate,
            self._chunk_size,
            input_device,
        )

    def _close_audio_stream(self) -> None:
        """Safely stop and close the audio stream."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
                logger.debug("Audio stream closed")
            except Exception:
                logger.exception("Error closing audio stream")
            finally:
                self._stream = None

        # Drain the queue so stale chunks don't pile up.
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    # ── Inference ────────────────────────────────────────────────────────

    def _predict(self, chunk_f32: np.ndarray) -> Optional[float]:
        """Run one inference step on a float32 audio chunk.

        OpenWakeWord expects int16 PCM, so we convert from float32 here.

        Returns
        -------
        float or None
            The highest prediction score for the loaded wake-word model,
            or ``None`` if prediction fails.
        """
        if self._model is None:
            return None

        try:
            # Convert float32 [-1,1] -> int16 PCM.
            int16_chunk = (chunk_f32 * 32767).astype(np.int16)
            self._model.predict(int16_chunk)

            # Extract the highest score across all loaded models.
            scores = self._model.prediction_buffer
            max_score: float = 0.0
            for model_name, preds in scores.items():
                if preds:
                    latest = preds[-1]
                    if latest > max_score:
                        max_score = latest
            return max_score

        except Exception:
            logger.exception("Prediction error")
            return None
