"""Manifest-only animation resolver for the DV3 visualizer.

Reads animations/manifest.json to map emotion/state tags to animation
file paths. No directory scanning. No emotion_map.yaml.

Usage:
    mapper = EmotionMapper("animations/manifest.json")
    path = mapper.get_animation_path("happy", theme="dark")
    path = mapper.get_state_path("idle", theme="dark")
"""
from __future__ import annotations

import json
import logging
import os
import random
from typing import Optional

logger = logging.getLogger(__name__)


class EmotionMapper:
    """Resolves emotion/state strings to animation file paths via manifest.json.

    On init, loads the manifest and builds an index keyed by emotion and state.
    Files tagged theme='both' match any theme query.
    Falls back to neutral, then any entry, if no exact match.
    """

    def __init__(self, manifest_path: str) -> None:
        self._manifest_path = os.path.abspath(manifest_path)
        self._manifest_dir = os.path.dirname(self._manifest_path)
        self._emotion_index: dict[str, list[str]] = {}
        self._state_index: dict[str, list[str]] = {}
        self._file_theme: dict[str, str] = {}
        self._all_files: list[str] = []
        self._load()

    def get_animation_path(self, emotion: str, theme: str = "dark") -> Optional[str]:
        """Return a random animation matching the given emotion and theme.

        Falls back: emotion → neutral → any file in theme → None.
        """
        candidates = self._resolve(self._emotion_index, emotion, theme)
        if candidates:
            return random.choice(candidates)
        neutral = self._resolve(self._emotion_index, "neutral", theme)
        if neutral:
            logger.warning("No animation for emotion=%r theme=%r — using neutral", emotion, theme)
            return random.choice(neutral)
        themed = [f for f in self._all_files if self._theme_matches(self._file_theme.get(f, "dark"), theme)]
        if themed:
            logger.warning("No neutral animation — picking random file")
            return random.choice(themed)
        logger.error("No animations available (manifest empty or missing?)")
        return None

    def get_state_path(self, state: str, theme: str = "dark") -> Optional[str]:
        """Return a random animation for the given state (idle/listening/processing)."""
        candidates = self._resolve(self._state_index, state, theme)
        if candidates:
            return random.choice(candidates)
        return self.get_animation_path(state, theme)

    def asset_count(self) -> int:
        return len(self._all_files)

    def reload(self) -> None:
        """Reload manifest from disk (call after new exports)."""
        self._emotion_index.clear()
        self._state_index.clear()
        self._file_theme.clear()
        self._all_files.clear()
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self._manifest_path):
            logger.warning("Manifest not found at %s — no animations will play", self._manifest_path)
            return
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load manifest %s: %s", self._manifest_path, exc)
            return

        assets = data.get("assets", [])
        loaded = 0
        for entry in assets:
            filename: str = entry.get("file", "")
            if not filename:
                continue
            abs_path = os.path.join(self._manifest_dir, filename)
            if not os.path.isfile(abs_path):
                logger.debug("Manifest file not on disk: %s", abs_path)
                continue
            theme = entry.get("theme", "dark")
            self._file_theme[abs_path] = theme
            self._all_files.append(abs_path)
            for emotion in entry.get("emotions", []):
                self._emotion_index.setdefault(emotion, []).append(abs_path)
            for state in entry.get("states", []):
                self._state_index.setdefault(state, []).append(abs_path)
            loaded += 1

        logger.info("EmotionMapper: loaded %d/%d assets from manifest", loaded, len(assets))

    def _resolve(self, index: dict[str, list[str]], key: str, theme: str) -> list[str]:
        return [f for f in index.get(key, []) if self._theme_matches(self._file_theme.get(f, "dark"), theme)]

    @staticmethod
    def _theme_matches(file_theme: str, requested: str) -> bool:
        if file_theme == "both":
            return True
        return file_theme == requested
