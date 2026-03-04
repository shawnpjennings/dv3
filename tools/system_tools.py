"""System utility tools for DV3.

Provides time, date, and other system-level information in natural-language
format suitable for the voice companion to read aloud.  Uses only the
Python standard library -- no external APIs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _ok(message: str, **data) -> dict:
    """Build a success response dict."""
    return {"success": True, "message": message, "data": data}


def _err(message: str, **data) -> dict:
    """Build an error response dict."""
    return {"success": False, "message": message, "data": data}


def _ordinal(n: int) -> str:
    """Return the ordinal string for an integer (1 -> '1st', 2 -> '2nd', ...).

    Handles the special cases for 11th, 12th, 13th correctly.
    """
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class SystemTools:
    """Time, date, and general system utilities.

    All methods return structured dictionaries with both machine-readable
    and natural-language values so Gemini can relay them conversationally.
    """

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_time(self) -> dict:
        """Get the current local time in a human-readable format.

        Returns:
            Result dict with ``time`` key (e.g. ``"3:45 PM"``).
        """
        now = datetime.now().astimezone()
        time_str = now.strftime("%-I:%M %p")
        tz_name = now.strftime("%Z") or now.tzname() or "local"

        logger.debug("get_time -> %s (%s)", time_str, tz_name)
        return _ok(
            f"It's {time_str}.",
            time=time_str,
            timezone=tz_name,
            iso=now.isoformat(),
        )

    def get_date(self) -> dict:
        """Get the current local date in a human-readable format.

        Returns:
            Result dict with ``date`` key
            (e.g. ``"Tuesday, March 4th, 2026"``).
        """
        now = datetime.now().astimezone()
        day_name = now.strftime("%A")
        month_name = now.strftime("%B")
        day_ordinal = _ordinal(now.day)
        year = now.year
        date_str = f"{day_name}, {month_name} {day_ordinal}, {year}"

        logger.debug("get_date -> %s", date_str)
        return _ok(
            f"Today is {date_str}.",
            date=date_str,
            iso=now.date().isoformat(),
        )

    # -------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------

    async def execute(self, function_name: str, args: dict) -> dict:
        """Dispatch a tool call to the appropriate method.

        Args:
            function_name: One of ``get_time``, ``get_date``.
            args: Currently unused; reserved for future parameters
                  (e.g. timezone overrides).

        Returns:
            Structured result dict.
        """
        dispatch_map = {
            "get_time": self.get_time,
            "get_date": self.get_date,
        }

        handler = dispatch_map.get(function_name)
        if handler is None:
            return _err(f"Unknown system function: {function_name}")

        return handler()
