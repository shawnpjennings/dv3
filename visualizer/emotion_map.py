"""Emotion string to animation file resolver for the DV3 visualizer.

Maps emotion tags (e.g. "happy", "thinking") to animation file paths
by reading ``config/emotion_map.yaml`` and scanning the corresponding
directories under ``data/animations/``.  Supports:

*   **Emotion buckets**: each emotion has a directory; a random file is
    chosen on every request so the visual stays fresh.
*   **Fallback chains**: if the emotion directory is empty, the mapper
    walks the ``fallback`` chain until it finds a directory with content.
*   **Contextual triggers**: specific keyword-matched patterns can
    override the emotion animation with a particular file or a random
    pick from a contextual directory.

Directory listings are cached at startup and can be rescanned on demand
(e.g. after new animation files are added at runtime via the editor).
"""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# File extensions the mapper considers valid animation files.
_ANIMATION_EXTENSIONS: frozenset[str] = frozenset({".webp", ".gif"})


class EmotionMapper:
    """Resolves emotion strings and contextual triggers to animation paths.

    Usage::

        mapper = EmotionMapper("config/emotion_map.yaml")
        path = mapper.get_animation_path("happy")       # random from bucket
        path = mapper.get_contextual_path(trigger_dict)  # keyword match
    """

    def __init__(self, config_path: str = "config/emotion_map.yaml") -> None:
        """Load the emotion map configuration and scan directories.

        Args:
            config_path: Path to the YAML file defining emotion
                directories, fallback chains, and contextual triggers.

        Raises:
            FileNotFoundError: If *config_path* does not exist.
            yaml.YAMLError: If the YAML is malformed.
        """
        self._config_path: str = config_path
        self._emotions: dict[str, dict] = {}
        self._contextual: dict[str, list[dict]] = {}

        # Cache: emotion name -> list of absolute file paths
        self._dir_cache: dict[str, list[str]] = {}

        self._load_config()
        self.scan_directories()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_animation_path(self, emotion: str) -> Optional[str]:
        """Return a random animation file path for *emotion*.

        If the emotion's own directory is empty the fallback chain is
        traversed.  Returns *None* only if every directory in the chain
        (including the terminal fallback) is empty.

        Args:
            emotion: Emotion tag string (e.g. ``"happy"``).

        Returns:
            Absolute path to a ``.webp`` or ``.gif`` file, or *None*.
        """
        visited: set[str] = set()
        current: Optional[str] = emotion

        while current and current not in visited:
            visited.add(current)

            files = self._dir_cache.get(current, [])
            if files:
                return random.choice(files)

            # Follow the fallback chain.
            emotion_cfg = self._emotions.get(current)
            if emotion_cfg is None:
                logger.warning("Unknown emotion '%s', no mapping found", current)
                return None
            current = emotion_cfg.get("fallback")

        logger.warning(
            "No animation found for '%s' after exhausting fallback chain", emotion
        )
        return None

    def get_contextual_path(self, trigger: dict) -> Optional[str]:
        """Resolve a contextual trigger dict to a file path.

        A trigger dict has the structure defined in ``emotion_map.yaml``
        under ``contextual_triggers``.  It may specify either a single
        ``file`` (used directly) or a ``directory`` (random pick).

        Args:
            trigger: A single trigger entry, e.g.::

                {
                    "patterns": ["pink floyd"],
                    "file": "data/animations/contextual/music/pink_floyd_prism.webp",
                    "duration": 8.0,
                    "priority": 10,
                }

        Returns:
            An absolute path string, or *None* if the file/directory is
            missing or empty.
        """
        # Direct file reference.
        if "file" in trigger:
            path = trigger["file"]
            abs_path = os.path.abspath(path)
            if os.path.isfile(abs_path):
                return abs_path
            logger.warning("Contextual trigger file not found: %s", path)
            return None

        # Directory reference -- pick a random valid file.
        if "directory" in trigger:
            directory = trigger["directory"]
            files = self._list_animation_files(directory)
            if files:
                return random.choice(files)
            logger.warning(
                "Contextual trigger directory empty or missing: %s", directory
            )
            return None

        logger.warning("Contextual trigger has neither 'file' nor 'directory': %s", trigger)
        return None

    def scan_directories(self) -> None:
        """Scan (or rescan) all emotion directories and update the cache.

        Called automatically at init and can be invoked manually after
        new files are added to the animation directories.
        """
        self._dir_cache.clear()

        for emotion, cfg in self._emotions.items():
            directory = cfg.get("directory", "")
            files = self._list_animation_files(directory)
            self._dir_cache[emotion] = files

            if not files:
                logger.warning(
                    "Emotion '%s' has no animation files in %s", emotion, directory
                )

        total = sum(len(v) for v in self._dir_cache.values())
        logger.info(
            "Scanned %d emotion directories: %d total animation files",
            len(self._dir_cache),
            total,
        )

    def get_available_emotions(self) -> list[str]:
        """Return emotion names that have at least one animation file.

        Returns:
            Sorted list of emotion strings.
        """
        return sorted(e for e, files in self._dir_cache.items() if files)

    # ------------------------------------------------------------------
    # Contextual trigger lookup
    # ------------------------------------------------------------------

    def find_contextual_trigger(self, text: str) -> Optional[dict]:
        """Search all contextual triggers for a pattern match in *text*.

        Returns the highest-priority matching trigger dict, or *None*.

        Args:
            text: Lowercased text to search (user speech or Gemini output).

        Returns:
            The matching trigger dict (with ``patterns``, ``file`` or
            ``directory``, ``duration``, ``priority``), or *None*.
        """
        text_lower = text.lower()
        best: Optional[dict] = None
        best_priority: int = -1

        for _category, triggers in self._contextual.items():
            for trigger in triggers:
                priority = trigger.get("priority", 0)
                if priority <= best_priority:
                    continue
                patterns: list[str] = trigger.get("patterns", [])
                for pattern in patterns:
                    if pattern.lower() in text_lower:
                        best = trigger
                        best_priority = priority
                        break  # first pattern match is enough

        return best

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Parse the emotion map YAML file."""
        with open(self._config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        self._emotions = data.get("emotions", {})
        self._contextual = data.get("contextual_triggers", {})

        logger.info(
            "Loaded emotion map: %d emotions, %d contextual categories",
            len(self._emotions),
            len(self._contextual),
        )

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_animation_files(directory: str) -> list[str]:
        """Return sorted absolute paths of animation files in *directory*.

        Only files whose extension is in ``_ANIMATION_EXTENSIONS`` are
        included.  Returns an empty list if the directory does not exist.

        Args:
            directory: Relative or absolute path to scan.

        Returns:
            Sorted list of absolute file path strings.
        """
        abs_dir = os.path.abspath(directory)
        if not os.path.isdir(abs_dir):
            return []

        files: list[str] = []
        try:
            for entry in os.scandir(abs_dir):
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in _ANIMATION_EXTENSIONS:
                        files.append(entry.path)
        except OSError as exc:
            logger.error("Failed to scan directory %s: %s", abs_dir, exc)
            return []

        files.sort()
        return files

    # ------------------------------------------------------------------
    # Manifest support (written by WebPew editor on export)
    # ------------------------------------------------------------------

    def load_manifest(self, manifest_path: str) -> int:
        """Load a ``manifest.json`` produced by the WebPew editor.

        The manifest records emotion/context/theme tags for each exported
        animation, enabling multi-emotion assignment and theme filtering.
        Loaded entries are merged into the existing directory cache so that
        manifest-tagged files are returned alongside folder-scanned files.

        Args:
            manifest_path: Path to ``manifest.json``.

        Returns:
            Number of asset entries successfully loaded from the manifest.
        """
        abs_path = os.path.abspath(manifest_path)
        if not os.path.isfile(abs_path):
            logger.debug("No manifest found at %s — skipping.", abs_path)
            return 0

        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load manifest %s: %s", abs_path, exc)
            return 0

        export_root = data.get("exportRoot", "data/animations")
        assets = data.get("assets", [])
        loaded = 0

        for entry in assets:
            filename: str = entry.get("filename", "")
            emotions: list[str] = entry.get("emotions", [])
            if not filename or not emotions:
                continue

            # Resolve the file path relative to the export root.
            candidate = os.path.abspath(os.path.join(export_root, filename))
            if not os.path.isfile(candidate):
                # Try filename only (flat layout).
                for ext in (".webp", ".gif"):
                    flat = os.path.abspath(
                        os.path.join(export_root, os.path.basename(filename))
                    )
                    if os.path.isfile(flat):
                        candidate = flat
                        break
                else:
                    logger.debug("Manifest asset not found on disk: %s", filename)
                    continue

            # Merge into dir_cache for all tagged emotions.
            for emotion in emotions:
                cache_list = self._dir_cache.setdefault(emotion, [])
                if candidate not in cache_list:
                    cache_list.append(candidate)
            loaded += 1

        logger.info(
            "Loaded %d/%d assets from manifest %s",
            loaded, len(assets), abs_path,
        )
        return loaded

    def get_animation_by_tags(
        self,
        emotions: list[str],
        theme: str = "dark",
    ) -> Optional[str]:
        """Return a random animation matching ANY of the given emotion tags.

        Prefers files tagged with the requested *theme* when duplicates
        exist (future use — currently theme filtering is best-effort).

        Args:
            emotions: List of emotion tags to match (in priority order).
            theme: ``'dark'``, ``'light'``, or ``'both'``.

        Returns:
            Absolute file path, or ``None`` if no match found.
        """
        for emotion in emotions:
            result = self.get_animation_path(emotion)
            if result:
                return result
        return None

    def reload_config(self) -> None:
        """Re-read the YAML config and rescan directories.

        Useful if the config file or animation directories are modified
        at runtime (e.g. via the editor).
        """
        self._load_config()
        self.scan_directories()
