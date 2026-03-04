"""Tests for core.voice_pipeline.base and core.wake_word modules.

Covers ToolCallRequest dataclass, VoicePipelineBase abstract class,
and WakeWordDetector unit behavior.  All hardware-dependent code
(audio devices, OpenWakeWord model) is mocked -- these tests never
open a real microphone or load a real ONNX model.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import directly from base.py to avoid pulling in gemini_live.py
# (which requires google-genai at module level).
from core.voice_pipeline.base import ToolCallRequest, VoicePipelineBase


# ---------------------------------------------------------------------------
# ToolCallRequest tests
# ---------------------------------------------------------------------------


class TestToolCallRequest:
    """ToolCallRequest dataclass construction and field access."""

    def test_create_with_all_fields(self):
        """Construct with explicit call_id, name, and args."""
        req = ToolCallRequest(
            call_id="abc-123",
            name="play_music",
            args={"artist": "Pink Floyd", "track": "Comfortably Numb"},
        )
        assert req.call_id == "abc-123"
        assert req.name == "play_music"
        assert req.args == {"artist": "Pink Floyd", "track": "Comfortably Numb"}

    def test_default_args_is_empty_dict(self):
        """When args is omitted it defaults to an empty dict, not None."""
        req = ToolCallRequest(call_id="id-1", name="timer_set")
        assert req.args == {}
        assert isinstance(req.args, dict)

    def test_default_args_not_shared(self):
        """Each instance gets its own default dict (no mutable default trap)."""
        a = ToolCallRequest(call_id="1", name="a")
        b = ToolCallRequest(call_id="2", name="b")
        a.args["x"] = 1
        assert "x" not in b.args

    def test_fields_are_accessible(self):
        """All three fields are readable as attributes."""
        req = ToolCallRequest(call_id="c1", name="volume_up", args={"level": 8})
        assert hasattr(req, "call_id")
        assert hasattr(req, "name")
        assert hasattr(req, "args")

    def test_equality(self):
        """Dataclass equality compares by value."""
        req1 = ToolCallRequest(call_id="x", name="y", args={"k": "v"})
        req2 = ToolCallRequest(call_id="x", name="y", args={"k": "v"})
        assert req1 == req2

    def test_inequality(self):
        req1 = ToolCallRequest(call_id="x", name="y")
        req2 = ToolCallRequest(call_id="x", name="z")
        assert req1 != req2


# ---------------------------------------------------------------------------
# VoicePipelineBase tests
# ---------------------------------------------------------------------------


class _MinimalPipeline(VoicePipelineBase):
    """Concrete subclass that satisfies all abstract methods with no-ops."""

    async def start(self) -> None:
        self._connected = True

    async def stop(self) -> None:
        self._connected = False

    async def send_audio(self, chunk: bytes) -> None:
        pass

    async def receive_audio(self) -> AsyncIterator[bytes]:
        yield b""

    async def receive_text(self) -> AsyncIterator[str]:
        yield ""

    async def send_tool_response(self, call_id: str, result: dict) -> None:
        pass


class TestVoicePipelineBase:
    """VoicePipelineBase abstract class invariants."""

    def test_cannot_instantiate_directly(self):
        """VoicePipelineBase is abstract and must not be instantiated."""
        with pytest.raises(TypeError):
            VoicePipelineBase()

    def test_concrete_subclass_can_be_created(self):
        """A minimal concrete subclass can be instantiated without error."""
        pipeline = _MinimalPipeline()
        assert isinstance(pipeline, VoicePipelineBase)

    def test_queues_created_at_init(self):
        """emotion_queue, tool_queue, and text_queue exist after __init__."""
        pipeline = _MinimalPipeline()
        assert isinstance(pipeline.emotion_queue, asyncio.Queue)
        assert isinstance(pipeline.tool_queue, asyncio.Queue)
        assert isinstance(pipeline.text_queue, asyncio.Queue)

    def test_queues_are_independent(self):
        """Each queue is a distinct object."""
        pipeline = _MinimalPipeline()
        assert pipeline.emotion_queue is not pipeline.tool_queue
        assert pipeline.tool_queue is not pipeline.text_queue
        assert pipeline.emotion_queue is not pipeline.text_queue

    def test_is_connected_starts_false(self):
        """is_connected property is False before start() is called."""
        pipeline = _MinimalPipeline()
        assert pipeline.is_connected is False

    def test_session_id_starts_empty(self):
        """session_id property is an empty string before start()."""
        pipeline = _MinimalPipeline()
        assert pipeline.session_id == ""

    @pytest.mark.asyncio
    async def test_start_sets_connected(self):
        """start() on the minimal subclass sets is_connected to True."""
        pipeline = _MinimalPipeline()
        await pipeline.start()
        assert pipeline.is_connected is True

    @pytest.mark.asyncio
    async def test_stop_clears_connected(self):
        """stop() on the minimal subclass resets is_connected to False."""
        pipeline = _MinimalPipeline()
        await pipeline.start()
        await pipeline.stop()
        assert pipeline.is_connected is False

    @pytest.mark.asyncio
    async def test_queues_accept_items(self):
        """Queues are functional -- items can be put and retrieved."""
        pipeline = _MinimalPipeline()
        await pipeline.emotion_queue.put("happy")
        await pipeline.tool_queue.put(
            ToolCallRequest(call_id="t1", name="timer_set")
        )
        await pipeline.text_queue.put("Hello world")

        assert await pipeline.emotion_queue.get() == "happy"
        tool_req = await pipeline.tool_queue.get()
        assert tool_req.name == "timer_set"
        assert await pipeline.text_queue.get() == "Hello world"


# ---------------------------------------------------------------------------
# WakeWordDetector tests
# ---------------------------------------------------------------------------


def _make_settings_file(config: dict) -> str:
    """Write a config dict to a temporary YAML file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="dv3_test_"
    )
    yaml.dump(config, tmp, default_flow_style=False)
    tmp.close()
    return tmp.name


@pytest.fixture
def minimal_settings_path():
    """Create a temporary settings.yaml with valid wake_word + audio sections."""
    config = {
        "wake_word": {
            "model_path": "temp/wakeword/test_model.onnx",
            "detection_threshold": 0.6,
            "sample_rate": 16000,
            "chunk_size": 1280,
        },
        "audio": {
            "prefer_pulse": True,
            "input_device": None,
        },
    }
    path = _make_settings_file(config)
    yield path
    os.unlink(path)


@pytest.fixture
def empty_settings_path():
    """Create a temporary settings.yaml that is empty (returns defaults)."""
    path = _make_settings_file({})
    yield path
    os.unlink(path)


class TestWakeWordDetectorConfig:
    """WakeWordDetector configuration loading (no audio or model)."""

    def test_load_with_valid_config(self, minimal_settings_path):
        """Constructor reads wake_word and audio sections correctly."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        assert det._threshold == 0.6
        assert det._sample_rate == 16000
        assert det._chunk_size == 1280
        assert det._prefer_pulse is True
        assert det._model_path == "temp/wakeword/test_model.onnx"

    def test_load_with_empty_config_uses_defaults(self, empty_settings_path):
        """When no wake_word section exists, sensible defaults are used."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=empty_settings_path)
        assert det._threshold == 0.5
        assert det._sample_rate == 16000
        assert det._chunk_size == 1280
        assert det._model_path == "temp/wakeword/Hey_Domino.onnx"

    def test_load_with_missing_file(self, tmp_path):
        """A nonexistent config file is handled gracefully (uses defaults)."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=str(tmp_path / "nonexistent.yaml"))
        assert det._threshold == 0.5

    def test_custom_threshold(self):
        """Custom threshold is read from config."""
        config = {
            "wake_word": {"detection_threshold": 0.8},
        }
        path = _make_settings_file(config)
        try:
            from core.wake_word import WakeWordDetector

            det = WakeWordDetector(config_path=path)
            assert det._threshold == 0.8
        finally:
            os.unlink(path)

    def test_callback_stored(self, minimal_settings_path):
        """The on_detected callback is stored."""
        from core.wake_word import WakeWordDetector

        cb = MagicMock()
        det = WakeWordDetector(
            config_path=minimal_settings_path, on_detected=cb
        )
        assert det.on_detected is cb

    def test_initial_state(self, minimal_settings_path):
        """Runtime state is properly initialized."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        assert det._running is False
        assert det._stream is None
        assert det._model is None


class TestFindInputDevice:
    """_find_input_device helper with mocked sounddevice."""

    def test_finds_pulse_device(self):
        """Returns the index of a PulseAudio input device when one exists."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {
                "name": "HDA Intel PCH: ALC233",
                "index": 0,
                "max_input_channels": 2,
            },
            {
                "name": "pulse",
                "index": 5,
                "max_input_channels": 2,
            },
            {
                "name": "default",
                "index": 7,
                "max_input_channels": 1,
            },
        ]
        result = _find_input_device(mock_sd)
        assert result == 5

    def test_returns_none_when_no_pulse(self):
        """Returns None when no PulseAudio device is listed."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {
                "name": "HDA Intel PCH: ALC233",
                "index": 0,
                "max_input_channels": 2,
            },
        ]
        result = _find_input_device(mock_sd)
        assert result is None

    def test_ignores_pulse_output_only_device(self):
        """A pulse device with 0 input channels should be skipped."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {
                "name": "pulse",
                "index": 3,
                "max_input_channels": 0,  # output only
            },
        ]
        result = _find_input_device(mock_sd)
        assert result is None

    def test_handles_single_device_dict(self):
        """When query_devices returns a single dict instead of a list."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = {
            "name": "pulse",
            "index": 1,
            "max_input_channels": 1,
        }
        result = _find_input_device(mock_sd)
        assert result == 1

    def test_handles_empty_device_list(self):
        """Returns None when no devices are available."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = []
        result = _find_input_device(mock_sd)
        assert result is None

    def test_handles_query_exception(self):
        """Returns None when query_devices raises an exception."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.side_effect = RuntimeError("ALSA lib error")
        result = _find_input_device(mock_sd)
        assert result is None

    def test_case_insensitive_pulse_match(self):
        """Device named 'Pulse' (capital P) is still matched."""
        from core.wake_word import _find_input_device

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {
                "name": "Pulse",
                "index": 2,
                "max_input_channels": 1,
            },
        ]
        # The implementation uses .lower() == "pulse"
        result = _find_input_device(mock_sd)
        assert result == 2


class TestWakeWordDetectorStartStop:
    """Start/stop lifecycle with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_start_raises_without_model_file(self, minimal_settings_path):
        """start() raises FileNotFoundError when the ONNX model is missing."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        with pytest.raises(FileNotFoundError, match="Wake-word model not found"):
            await det.start()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, minimal_settings_path):
        """stop() is safe to call even when the detector was never started."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        # Should not raise
        await det.stop()
        assert det._running is False
        assert det._model is None

    @pytest.mark.asyncio
    async def test_stop_clears_state(self, minimal_settings_path):
        """stop() resets _running and _model to initial values."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        # Manually set internal state as if it were running
        det._running = True
        det._model = MagicMock()
        det._stream = None  # no real stream

        await det.stop()
        assert det._running is False
        assert det._model is None

    @pytest.mark.asyncio
    async def test_wait_for_detection_raises_when_not_running(
        self, minimal_settings_path
    ):
        """wait_for_detection() raises RuntimeError if not started."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        with pytest.raises(RuntimeError, match="not running"):
            await det.wait_for_detection()


class TestWakeWordDetectorPredict:
    """_predict method with mocked model."""

    def test_predict_converts_and_returns_score(self, minimal_settings_path):
        """_predict converts float32 to int16 and returns max score."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)

        # Mock the model
        mock_model = MagicMock()
        mock_model.prediction_buffer = {
            "Hey_Domino": [0.1, 0.3, 0.85],
        }
        det._model = mock_model

        chunk = np.zeros(1280, dtype=np.float32)
        score = det._predict(chunk)

        assert score == 0.85
        mock_model.predict.assert_called_once()
        # Verify the argument was int16
        call_args = mock_model.predict.call_args[0][0]
        assert call_args.dtype == np.int16

    def test_predict_returns_none_when_no_model(self, minimal_settings_path):
        """_predict returns None when _model is None."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        det._model = None
        result = det._predict(np.zeros(1280, dtype=np.float32))
        assert result is None

    def test_predict_returns_none_on_exception(self, minimal_settings_path):
        """_predict returns None if the model raises an error."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("inference error")
        det._model = mock_model

        result = det._predict(np.zeros(1280, dtype=np.float32))
        assert result is None

    def test_predict_with_multiple_models(self, minimal_settings_path):
        """_predict returns the max score across multiple loaded models."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        mock_model = MagicMock()
        mock_model.prediction_buffer = {
            "model_a": [0.2, 0.4],
            "model_b": [0.1, 0.9],
        }
        det._model = mock_model

        score = det._predict(np.zeros(1280, dtype=np.float32))
        assert score == 0.9

    def test_predict_with_empty_buffer(self, minimal_settings_path):
        """_predict returns 0.0 when prediction_buffer is empty."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        mock_model = MagicMock()
        mock_model.prediction_buffer = {}
        det._model = mock_model

        score = det._predict(np.zeros(1280, dtype=np.float32))
        assert score == 0.0


class TestWakeWordDetectorCloseStream:
    """_close_audio_stream method."""

    def test_close_with_no_stream(self, minimal_settings_path):
        """_close_audio_stream is safe when _stream is None."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        det._stream = None
        # Should not raise
        det._close_audio_stream()

    def test_close_stops_and_closes_stream(self, minimal_settings_path):
        """_close_audio_stream calls stop() and close() on the stream."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        mock_stream = MagicMock()
        det._stream = mock_stream

        det._close_audio_stream()

        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()
        assert det._stream is None

    def test_close_drains_queue(self, minimal_settings_path):
        """_close_audio_stream drains any pending items from _audio_queue."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        det._stream = None

        # Put some items in the queue
        det._audio_queue.put_nowait(np.zeros(100, dtype=np.float32))
        det._audio_queue.put_nowait(np.zeros(100, dtype=np.float32))
        assert not det._audio_queue.empty()

        det._close_audio_stream()
        assert det._audio_queue.empty()

    def test_close_handles_stream_exception(self, minimal_settings_path):
        """_close_audio_stream handles exceptions from stream.stop()."""
        from core.wake_word import WakeWordDetector

        det = WakeWordDetector(config_path=minimal_settings_path)
        mock_stream = MagicMock()
        mock_stream.stop.side_effect = RuntimeError("device lost")
        det._stream = mock_stream

        # Should not raise even though stop() fails
        det._close_audio_stream()
        assert det._stream is None
