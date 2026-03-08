"""Tests for tools.tool_dispatcher — tool routing and system tools."""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.system_tools import SystemTools
from tools.timer_tool import TimerTool
from tools.tool_dispatcher import ToolDispatcher


class TestSystemTools:
    """System utility tool tests."""

    @pytest.fixture
    def tools(self):
        return SystemTools()

    @pytest.mark.asyncio
    async def test_get_time(self, tools):
        result = await tools.execute("get_time", {})
        assert result["success"] is True
        assert "time" in result or "message" in result

    @pytest.mark.asyncio
    async def test_get_date(self, tools):
        result = await tools.execute("get_date", {})
        assert result["success"] is True
        assert "date" in result or "message" in result

    @pytest.mark.asyncio
    async def test_unknown_function(self, tools):
        result = await tools.execute("nonexistent", {})
        assert result["success"] is False


class TestTimerTool:
    """Timer tool tests."""

    @pytest.fixture
    def timer(self):
        return TimerTool()

    @pytest.mark.asyncio
    async def test_set_timer(self, timer):
        result = await timer.execute(
            "set_timer", {"duration_seconds": 2, "label": "test"}
        )
        assert result["success"] is True
        assert "timer_id" in result

        # Clean up
        timer_id = result["timer_id"]
        await timer.execute("cancel_timer", {"timer_id": timer_id})

    @pytest.mark.asyncio
    async def test_list_timers(self, timer):
        result = await timer.execute("list_timers", {})
        assert result["success"] is True


class TestTimerCallback:
    """Timer TTS callback actually fires on expiry."""

    @pytest.mark.asyncio
    async def test_tts_callback_fires_on_expiry(self):
        """Set a 1-second timer with a callback. Wait for it. Verify callback fired."""
        fired = []

        def on_done(msg):
            fired.append(msg)

        timer = TimerTool(tts_callback=on_done)
        result = await timer.set_timer(1, "pasta")
        assert result["success"] is True

        # Wait for expiry
        await asyncio.sleep(2)

        assert len(fired) == 1, f"Expected 1 callback, got {len(fired)}"
        assert "pasta" in fired[0]
        assert "done" in fired[0].lower()

    @pytest.mark.asyncio
    async def test_tts_callback_not_fired_when_cancelled(self):
        """Cancel a timer before expiry. Callback must NOT fire."""
        fired = []

        def on_done(msg):
            fired.append(msg)

        timer = TimerTool(tts_callback=on_done)
        result = await timer.set_timer(5, "cancelled_test")
        timer_id = result["timer_id"]

        await timer.cancel_timer(timer_id)
        await asyncio.sleep(1)

        assert len(fired) == 0, f"Callback should not fire after cancel, got {fired}"


class TestSpotifyAuth:
    """Spotify OAuth token and API access.

    These tests verify the REAL Spotify integration works.
    If the OAuth token is missing, they fail with a clear message
    telling you to run: python scripts/spotify_auth.py
    """

    @pytest.fixture
    def token_path(self):
        return Path(PROJECT_ROOT / ".cache" / "spotify_token")

    def test_oauth_token_exists(self, token_path):
        """OAuth token must be cached. Run scripts/spotify_auth.py if missing."""
        assert token_path.exists(), (
            f"Spotify OAuth token not found at {token_path}. "
            "Run: python scripts/spotify_auth.py"
        )

    def test_oauth_token_is_valid_json(self, token_path):
        """Cached token must be valid JSON with expected fields."""
        if not token_path.exists():
            pytest.skip("No token — run scripts/spotify_auth.py first")

        import json
        data = json.loads(token_path.read_text())
        assert "access_token" in data, "Token file missing access_token"
        assert "refresh_token" in data, "Token file missing refresh_token"
        assert "token_type" in data, "Token file missing token_type"

    @pytest.mark.asyncio
    async def test_now_playing_returns_without_hanging(self, token_path):
        """SpotifyTool.now_playing() must return (not hang) within 10 seconds."""
        if not token_path.exists():
            pytest.skip("No token — run scripts/spotify_auth.py first")

        from tools.spotify_tool import SpotifyTool
        st = SpotifyTool()

        # Must complete within 10 seconds — if it hangs, token is bad
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, st.now_playing),
            timeout=10,
        )
        assert "success" in result, f"Unexpected result shape: {result}"
        assert isinstance(result["success"], bool)


class TestToolDispatcher:
    """Dispatcher routing tests."""

    @pytest.fixture
    def dispatcher(self):
        return ToolDispatcher()

    @pytest.mark.asyncio
    async def test_routes_get_time(self, dispatcher):
        result = await dispatcher.dispatch("get_time", {})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_routes_get_date(self, dispatcher):
        result = await dispatcher.dispatch("get_date", {})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unknown_tool(self, dispatcher):
        result = await dispatcher.dispatch("totally_fake_tool", {})
        assert result["success"] is False
