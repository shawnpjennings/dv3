"""Countdown timer tool for DV3.

Supports multiple concurrent named timers backed by asyncio tasks. When a
timer expires it calls the optional TTS callback so the voice companion can
announce completion aloud.

Typical flow:
    1. Gemini emits ``set_timer`` with ``{"duration_seconds": 600, "label": "pasta"}``
    2. ToolDispatcher routes to TimerTool.execute()
    3. A background asyncio task counts down and fires the TTS callback on
       completion.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CONCURRENT = 10


def _ok(message: str, **data) -> dict:
    """Build a success response dict."""
    return {"success": True, "message": message, **data}


def _err(message: str, **data) -> dict:
    """Build an error response dict."""
    return {"success": False, "message": message, **data}


# ---------------------------------------------------------------------------
# Timer data model
# ---------------------------------------------------------------------------


@dataclass
class Timer:
    """Represents a single running countdown timer.

    Attributes:
        id: Unique identifier for this timer.
        label: Human-readable label (e.g. ``"pasta"``).
        duration: Total duration in seconds.
        start_time: ``time.monotonic()`` value when the timer started.
        task: The asyncio task that is sleeping until expiry.
    """

    id: str
    label: str
    duration: int
    start_time: float
    task: asyncio.Task = field(repr=False, compare=False, default=None)  # type: ignore[assignment]

    @property
    def remaining(self) -> float:
        """Seconds remaining, never negative."""
        elapsed = time.monotonic() - self.start_time
        return max(0.0, self.duration - elapsed)

    @property
    def is_done(self) -> bool:
        """Whether this timer has completed."""
        return self.remaining <= 0


# ---------------------------------------------------------------------------
# TimerTool
# ---------------------------------------------------------------------------


class TimerTool:
    """Manages concurrent countdown timers with optional TTS announcements.

    Args:
        tts_callback: Async or sync callable invoked with an announcement
            string when a timer completes.  ``None`` disables announcements.
        max_concurrent: Maximum number of timers allowed at once.
    """

    def __init__(
        self,
        tts_callback: Optional[Callable[[str], None]] = None,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._tts_callback = tts_callback
        self._max_concurrent = max_concurrent
        self._timers: Dict[str, Timer] = {}
        logger.info(
            "TimerTool initialised (max_concurrent=%d, tts=%s)",
            max_concurrent,
            "enabled" if tts_callback else "disabled",
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def set_timer(self, duration_seconds: int, label: str = "") -> dict:
        """Create and start a new countdown timer.

        Args:
            duration_seconds: How many seconds to count down.  Must be > 0.
            label: Optional human-readable label (e.g. ``"eggs"``).

        Returns:
            Result dict with the timer_id and remaining_seconds.
        """
        if duration_seconds <= 0:
            return _err(
                "Duration must be a positive number of seconds.",
                timer_id="",
                remaining_seconds=0,
            )

        if len(self._timers) >= self._max_concurrent:
            return _err(
                f"Maximum of {self._max_concurrent} concurrent timers reached. "
                "Cancel an existing timer first.",
                timer_id="",
                remaining_seconds=0,
            )

        timer_id = uuid.uuid4().hex[:8]
        timer = Timer(
            id=timer_id,
            label=label,
            duration=duration_seconds,
            start_time=time.monotonic(),
        )
        timer.task = asyncio.create_task(
            self._run_timer(timer), name=f"timer-{timer_id}"
        )
        self._timers[timer_id] = timer

        human_duration = self._format_duration(duration_seconds)
        label_part = f" '{label}'" if label else ""
        logger.info("Timer %s started: %s%s", timer_id, human_duration, label_part)

        return _ok(
            f"Timer{label_part} set for {human_duration}.",
            timer_id=timer_id,
            remaining_seconds=duration_seconds,
        )

    async def list_timers(self) -> dict:
        """List all active (non-completed) timers.

        Returns:
            Result dict with a list of timer summaries.
        """
        self._purge_done()

        if not self._timers:
            return _ok("No active timers.", timer_id="", remaining_seconds=0)

        summaries = []
        for t in self._timers.values():
            remaining = int(t.remaining)
            label_part = f" ({t.label})" if t.label else ""
            summaries.append(
                {
                    "timer_id": t.id,
                    "label": t.label,
                    "remaining_seconds": remaining,
                    "remaining_human": self._format_duration(remaining),
                }
            )

        count = len(summaries)
        return _ok(
            f"{count} active timer{'s' if count != 1 else ''}.",
            timer_id="",
            remaining_seconds=0,
            timers=summaries,
        )

    async def cancel_timer(self, timer_id: str) -> dict:
        """Cancel and remove a timer by its ID.

        Args:
            timer_id: The identifier returned by :meth:`set_timer`.

        Returns:
            Result dict confirming cancellation.
        """
        timer = self._timers.pop(timer_id, None)
        if timer is None:
            return _err(
                f"No active timer with ID '{timer_id}'.",
                timer_id=timer_id,
                remaining_seconds=0,
            )

        timer.task.cancel()
        try:
            await timer.task
        except asyncio.CancelledError:
            pass

        label_part = f" '{timer.label}'" if timer.label else f" {timer_id}"
        logger.info("Timer%s cancelled.", label_part)
        return _ok(
            f"Timer{label_part} cancelled.",
            timer_id=timer_id,
            remaining_seconds=0,
        )

    async def cancel_all(self) -> None:
        """Cancel every active timer.  Used during shutdown."""
        for timer_id in list(self._timers.keys()):
            await self.cancel_timer(timer_id)
        logger.info("All timers cancelled.")

    # -------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------

    async def execute(self, function_name: str, args: dict) -> dict:
        """Dispatch a tool call to the appropriate method.

        Args:
            function_name: One of ``set_timer``, ``list_timers``,
                ``cancel_timer``.
            args: Keyword arguments forwarded to the underlying method.

        Returns:
            Structured result dict.
        """
        if function_name == "set_timer":
            duration = int(args.get("duration_seconds", 0))
            label = str(args.get("label", ""))
            return await self.set_timer(duration, label)

        if function_name == "list_timers":
            return await self.list_timers()

        if function_name == "cancel_timer":
            timer_id = str(args.get("timer_id", ""))
            if not timer_id:
                return _err(
                    "timer_id is required to cancel a timer.",
                    timer_id="",
                    remaining_seconds=0,
                )
            return await self.cancel_timer(timer_id)

        return _err(
            f"Unknown timer function: {function_name}",
            timer_id="",
            remaining_seconds=0,
        )

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    async def _run_timer(self, timer: Timer) -> None:
        """Background coroutine that waits for the timer to expire."""
        try:
            await asyncio.sleep(timer.duration)
        except asyncio.CancelledError:
            logger.debug("Timer %s task cancelled.", timer.id)
            return

        # --- Timer completed ---
        label_part = f" '{timer.label}'" if timer.label else ""
        human_duration = self._format_duration(timer.duration)
        announcement = f"Your {human_duration} timer{label_part} is done."

        logger.info("Timer %s completed: %s", timer.id, announcement)

        if self._tts_callback is not None:
            try:
                result = self._tts_callback(announcement)
                # Support both sync and async callbacks.
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("TTS callback failed for timer %s", timer.id)

        # Remove from active set after completion.
        self._timers.pop(timer.id, None)

    def _purge_done(self) -> None:
        """Remove timers whose tasks have finished."""
        done_ids = [
            tid for tid, t in self._timers.items() if t.task.done()
        ]
        for tid in done_ids:
            self._timers.pop(tid, None)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format *seconds* into a natural-language string.

        Examples:
            90 -> "1 minute 30 seconds"
            3600 -> "1 hour"
            7261 -> "2 hours 1 minute 1 second"
        """
        if seconds < 1:
            return "0 seconds"

        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)

        parts: list[str] = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if secs:
            parts.append(f"{secs} second{'s' if secs != 1 else ''}")

        return " ".join(parts)
