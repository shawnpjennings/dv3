"""Central tool dispatcher for DV3.

Routes incoming Gemini Live API ``tool_call`` messages to the correct tool
handler based on the function name.  This is the single integration point
between the voice pipeline and all tool implementations.

Usage from the voice pipeline::

    dispatcher = ToolDispatcher()

    # When Gemini emits a tool_call:
    result = await dispatcher.dispatch(tool_call.name, tool_call.args)
    await pipeline.send_tool_response(tool_call.call_id, result)
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from .spotify_tool import SpotifyTool
from .system_tools import SystemTools
from .timer_tool import TimerTool

logger = logging.getLogger(__name__)


def _err(message: str) -> dict:
    """Build an error response dict."""
    return {"success": False, "message": message, "data": {}}


# Mapping from Gemini function names to the tool class that handles them.
_SPOTIFY_FUNCTIONS = frozenset(
    {
        "play_music",
        "pause_music",
        "skip_track",
        "previous_track",
        "set_volume",
        "now_playing",
    }
)

_TIMER_FUNCTIONS = frozenset(
    {
        "set_timer",
        "list_timers",
        "cancel_timer",
    }
)

_SYSTEM_FUNCTIONS = frozenset(
    {
        "get_time",
        "get_date",
    }
)


class ToolDispatcher:
    """Routes tool calls from the Gemini backend to the correct handler.

    On construction every tool is initialised eagerly.  If a tool fails to
    initialise (e.g. missing Spotify credentials) it is logged and the tool
    is disabled -- calls to its functions will return a graceful error dict
    rather than crashing the pipeline.

    Args:
        tts_callback: Optional callback forwarded to :class:`TimerTool` for
            announcing timer completions via the voice pipeline.
    """

    def __init__(
        self,
        tts_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        # --- Spotify ---
        self._spotify: Optional[SpotifyTool] = None
        try:
            self._spotify = SpotifyTool()
        except Exception:
            logger.warning(
                "SpotifyTool failed to initialise -- Spotify functions disabled.",
                exc_info=True,
            )

        # --- Timer ---
        self._timer = TimerTool(tts_callback=tts_callback)

        # --- System ---
        self._system = SystemTools()

        logger.info(
            "ToolDispatcher ready (spotify=%s, timer=ok, system=ok)",
            "ok" if self._spotify else "disabled",
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def dispatch(self, function_name: str, args: dict) -> dict:
        """Route a function call to the correct tool and return its result.

        Args:
            function_name: The name emitted in the Gemini ``tool_call``
                (e.g. ``"play_music"``, ``"set_timer"``, ``"get_time"``).
            args: Argument dict parsed from the tool call payload.

        Returns:
            Structured result dict from the tool, always containing at
            least ``success`` (bool) and ``message`` (str) keys.
        """
        logger.debug("Dispatching tool call: %s(%s)", function_name, args)

        try:
            if function_name in _SPOTIFY_FUNCTIONS:
                if self._spotify is None:
                    return _err(
                        "Spotify is not available. "
                        "Check that SPOTIFY_CLIENT_ID and SPOTIFY_SECRET are "
                        "configured in .env."
                    )
                return await self._spotify.execute(function_name, args)

            if function_name in _TIMER_FUNCTIONS:
                return await self._timer.execute(function_name, args)

            if function_name in _SYSTEM_FUNCTIONS:
                return await self._system.execute(function_name, args)

            logger.warning("Unknown tool function: %s", function_name)
            return _err(f"Unknown tool function: {function_name}")

        except Exception:
            logger.exception("Unhandled error dispatching %s", function_name)
            return _err(f"Internal error while executing {function_name}.")

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Clean up resources held by tools.

        Cancels all active timers. Safe to call multiple times.
        """
        logger.info("ToolDispatcher shutting down.")
        await self._timer.cancel_all()

    # -------------------------------------------------------------------
    # Introspection
    # -------------------------------------------------------------------

    @property
    def available_functions(self) -> frozenset[str]:
        """Set of all function names this dispatcher can handle."""
        functions: set[str] = set()
        if self._spotify is not None:
            functions.update(_SPOTIFY_FUNCTIONS)
        functions.update(_TIMER_FUNCTIONS)
        functions.update(_SYSTEM_FUNCTIONS)
        return frozenset(functions)

    @property
    def spotify_enabled(self) -> bool:
        """Whether Spotify integration is active."""
        return self._spotify is not None
