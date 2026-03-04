"""Spotify playback control tool for DV3.

Wraps the spotipy library to provide voice-driven music control via the
Gemini Live API's function calling mechanism. All credentials are loaded
from environment variables -- nothing is hardcoded.

Typical flow:
    1. Gemini emits a tool_call with name ``play_music`` and args ``{"query": "..."}``
    2. ToolDispatcher routes to SpotifyTool.execute()
    3. SpotifyTool searches Spotify, starts playback on the active device,
       and returns a structured result dict.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OAUTH_SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)

_TOKEN_CACHE_PATH = Path(".cache/spotify_token")


def _ok(message: str, **data: Any) -> dict:
    """Build a success response dict."""
    return {"success": True, "message": message, "data": data}


def _err(message: str, **data: Any) -> dict:
    """Build an error response dict."""
    return {"success": False, "message": message, "data": data}


class SpotifyTool:
    """Voice-driven Spotify playback controller.

    All public methods return ``{"success": bool, "message": str, "data": {...}}``
    dictionaries so the Gemini backend can relay a natural-language summary
    back to the user.

    Attributes:
        sp: Authenticated spotipy.Spotify client instance.
    """

    # -------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------

    def __init__(self) -> None:
        """Initialise the spotipy client with OAuth credentials from env."""
        load_dotenv()

        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_SECRET")
        redirect_uri = os.getenv(
            "SPOTIFY_REDIRECT_URL", "http://127.0.0.1:8888/callback"
        )

        if not client_id or not client_secret:
            raise RuntimeError(
                "SPOTIFY_CLIENT_ID and SPOTIFY_SECRET must be set in .env"
            )

        # Ensure cache directory exists.
        _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=_OAUTH_SCOPE,
            cache_path=str(_TOKEN_CACHE_PATH),
        )

        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        logger.info("SpotifyTool initialised (cache: %s)", _TOKEN_CACHE_PATH)

    # -------------------------------------------------------------------
    # Playback controls
    # -------------------------------------------------------------------

    def play(self, query: str) -> dict:
        """Search for *query* and start playback on the active device.

        Search order: tracks -> artists -> albums.  The first match wins.

        Args:
            query: Free-text search string (track name, artist, album title,
                   or any combination thereof).

        Returns:
            Result dict with the name and type of what was played.
        """
        if not query or not query.strip():
            return _err("No search query provided.")

        query = query.strip()

        try:
            # --- Try tracks first ---
            results = self.sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                track = tracks[0]
                self.sp.start_playback(uris=[track["uri"]])
                artist = track["artists"][0]["name"] if track["artists"] else "Unknown"
                return _ok(
                    f"Playing {track['name']} by {artist}",
                    name=track["name"],
                    artist=artist,
                    type="track",
                    uri=track["uri"],
                )

            # --- Fall back to artists ---
            results = self.sp.search(q=query, type="artist", limit=1)
            artists = results.get("artists", {}).get("items", [])
            if artists:
                artist = artists[0]
                self.sp.start_playback(context_uri=artist["uri"])
                return _ok(
                    f"Playing music by {artist['name']}",
                    name=artist["name"],
                    type="artist",
                    uri=artist["uri"],
                )

            # --- Fall back to albums ---
            results = self.sp.search(q=query, type="album", limit=1)
            albums = results.get("albums", {}).get("items", [])
            if albums:
                album = albums[0]
                artist_name = (
                    album["artists"][0]["name"] if album["artists"] else "Unknown"
                )
                self.sp.start_playback(context_uri=album["uri"])
                return _ok(
                    f"Playing album {album['name']} by {artist_name}",
                    name=album["name"],
                    artist=artist_name,
                    type="album",
                    uri=album["uri"],
                )

            return _err(f"Could not find anything matching '{query}'.")

        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.play")
            return _err("An unexpected error occurred while trying to play music.")

    def pause(self) -> dict:
        """Pause playback on the active device.

        Returns:
            Result dict confirming the pause.
        """
        try:
            self.sp.pause_playback()
            return _ok("Playback paused.")
        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.pause")
            return _err("An unexpected error occurred while trying to pause.")

    def skip(self) -> dict:
        """Skip to the next track.

        Returns:
            Result dict confirming the skip.
        """
        try:
            self.sp.next_track()
            return _ok("Skipped to next track.")
        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.skip")
            return _err("An unexpected error occurred while trying to skip.")

    def previous(self) -> dict:
        """Go back to the previous track.

        Returns:
            Result dict confirming the action.
        """
        try:
            self.sp.previous_track()
            return _ok("Went back to previous track.")
        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.previous")
            return _err("An unexpected error occurred while going to previous track.")

    def set_volume(self, level: int) -> dict:
        """Set playback volume.

        Args:
            level: Volume percentage, clamped to 0-100.

        Returns:
            Result dict confirming the new volume.
        """
        level = max(0, min(100, level))
        try:
            self.sp.volume(level)
            return _ok(f"Volume set to {level}%.", volume=level)
        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.set_volume")
            return _err("An unexpected error occurred while setting volume.")

    def now_playing(self) -> dict:
        """Get information about the currently playing track.

        Returns:
            Result dict with track name, artist, album, and progress.
        """
        try:
            current = self.sp.current_playback()
            if not current or not current.get("item"):
                return _ok("Nothing is currently playing.", is_playing=False)

            item = current["item"]
            artist = item["artists"][0]["name"] if item.get("artists") else "Unknown"
            album = item.get("album", {}).get("name", "Unknown")
            progress_ms = current.get("progress_ms", 0)
            duration_ms = item.get("duration_ms", 0)
            is_playing = current.get("is_playing", False)

            progress_sec = progress_ms // 1000
            duration_sec = duration_ms // 1000
            progress_str = f"{progress_sec // 60}:{progress_sec % 60:02d}"
            duration_str = f"{duration_sec // 60}:{duration_sec % 60:02d}"

            return _ok(
                f"{'Now playing' if is_playing else 'Paused'}: "
                f"{item['name']} by {artist}",
                name=item["name"],
                artist=artist,
                album=album,
                is_playing=is_playing,
                progress=progress_str,
                duration=duration_str,
            )
        except spotipy.SpotifyException as exc:
            return self._handle_spotify_error(exc)
        except Exception:
            logger.exception("Unexpected error in SpotifyTool.now_playing")
            return _err("An unexpected error occurred while getting playback info.")

    # -------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------

    async def execute(self, function_name: str, args: dict) -> dict:
        """Dispatch a tool call to the appropriate method.

        This is the single entry-point used by :class:`ToolDispatcher`.

        Args:
            function_name: One of ``play_music``, ``pause_music``,
                ``skip_track``, ``previous_track``, ``set_volume``,
                ``now_playing``.
            args: Keyword arguments forwarded to the underlying method.

        Returns:
            Structured result dict.
        """
        dispatch_map = {
            "play_music": lambda: self.play(args.get("query", "")),
            "pause_music": lambda: self.pause(),
            "skip_track": lambda: self.skip(),
            "previous_track": lambda: self.previous(),
            "set_volume": lambda: self.set_volume(int(args.get("level", 50))),
            "now_playing": lambda: self.now_playing(),
        }

        handler = dispatch_map.get(function_name)
        if handler is None:
            return _err(f"Unknown Spotify function: {function_name}")

        return handler()

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _handle_spotify_error(exc: spotipy.SpotifyException) -> dict:
        """Translate common Spotify API errors into user-friendly messages."""
        status = exc.http_status
        reason = getattr(exc, "reason", "")

        if status == 404:
            logger.warning("Spotify: no active device found (%s)", reason)
            return _err(
                "No active Spotify device found. "
                "Please open Spotify on a device first."
            )
        if status == 403:
            logger.warning("Spotify: premium required (%s)", reason)
            return _err("This feature requires a Spotify Premium account.")
        if status == 401:
            logger.warning("Spotify: auth expired or invalid (%s)", reason)
            return _err(
                "Spotify authentication expired. Please re-authenticate."
            )

        logger.error("Spotify API error %d: %s", status, reason)
        return _err(f"Spotify error ({status}): {reason}")
