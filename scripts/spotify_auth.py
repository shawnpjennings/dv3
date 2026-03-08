"""One-time Spotify OAuth authorization flow.

Run this script interactively to complete the browser-based OAuth flow
and cache the token at .cache/spotify_token. After this succeeds,
SpotifyTool will work without browser interaction.

Usage:
    python scripts/spotify_auth.py
"""

import os
import sys
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)
CACHE_PATH = PROJECT_ROOT / ".cache" / "spotify_token"


def main():
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URL", "http://127.0.0.1:8888/callback")

    if not client_id or not client_secret:
        print("ERROR: SPOTIFY_CLIENT_ID and SPOTIFY_SECRET must be set in .env")
        sys.exit(1)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"Client ID: {client_id[:8]}...")
    print(f"Redirect URI: {redirect_uri}")
    print(f"Token cache: {CACHE_PATH}")
    print()
    print("Opening browser for Spotify authorization...")
    print("If the browser doesn't open, copy the URL from the terminal.")
    print()

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=str(CACHE_PATH),
        open_browser=False,
    )

    # Check for existing cached token first
    token_info = auth.get_cached_token()
    if token_info:
        print("Found cached token, refreshing if needed...")
        sp = spotipy.Spotify(auth_manager=auth)
    else:
        # Manual URL-paste flow (works in WSL2 without browser)
        auth_url = auth.get_authorize_url()
        print(f"Open this URL in your browser:\n\n{auth_url}\n")
        print("After authorizing, you'll be redirected to a URL (may show 404).")
        print("Copy the FULL URL from your browser's address bar and paste it here.\n")
        response_url = input("Paste the redirect URL: ").strip()

        code = auth.parse_response_code(response_url)
        if not code:
            print("ERROR: Could not extract authorization code from URL")
            sys.exit(1)

        token_info = auth.get_access_token(code, as_dict=True)
        sp = spotipy.Spotify(auth_manager=auth)

    # Verify it works
    try:
        user = sp.current_user()
        print(f"\nAuthorized as: {user['display_name']} ({user['id']})")
        print(f"Token cached at: {CACHE_PATH}")

        current = sp.current_playback()
        if current and current.get("item"):
            track = current["item"]
            artist = track["artists"][0]["name"] if track.get("artists") else "?"
            print(f"Now playing: {track['name']} by {artist}")
        else:
            print("No active playback (open Spotify on a device to test)")

        print("\nSpotify auth: SUCCESS")
    except Exception as e:
        print(f"\nSpotify API test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
