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
