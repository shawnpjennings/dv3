"""Emotion tag extraction and keyword fallback for DV3.

Parses Gemini text output to determine the current emotional state for the
visualizer. Three detection strategies are used in priority order:

    1. **Contextual triggers** -- pattern matching against a curated list of
       topic-specific keywords (e.g. "pink floyd" -> special music animation).
    2. **Regex tag extraction** -- looks for ``[emotion]`` tags embedded in
       the first 30 tokens of a Gemini response.
    3. **Keyword fallback** -- scans those same tokens for sentiment-bearing
       keywords defined in ``emotion_map.yaml``.
    4. **Default** -- emits ``"neutral"`` when nothing else matches.

All configuration is loaded from ``config/emotion_map.yaml`` at init time.
Nothing is hardcoded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

# Compiled once at module level for performance.
_TAG_PATTERN: re.Pattern[str] = re.compile(r"\[(\w+)\]")


class EmotionParser:
    """Extract emotion cues from streaming text and route them to the visualizer.

    The parser sits between the voice pipeline's ``text_queue`` and the
    visualizer's ``emotion_queue``. It buffers a configurable number of leading
    tokens, applies the detection cascade, and emits a result dict that the
    animation engine can act on.

    Args:
        emotion_map_path: Filesystem path (relative to project root or
            absolute) to the emotion map YAML file.
        tag_buffer_tokens: Number of leading tokens to buffer before
            attempting tag/keyword extraction. Overrides the YAML default
            if provided explicitly.
        default_emotion: Emotion string to emit when no detection method
            produces a result.

    Raises:
        FileNotFoundError: If the emotion map file cannot be located.
        yaml.YAMLError: If the file contains invalid YAML.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        emotion_map_path: str = "config/emotion_map.yaml",
        tag_buffer_tokens: int = 30,
        default_emotion: str = "neutral",
    ) -> None:
        self._emotion_map_path = emotion_map_path
        self._tag_buffer_tokens = tag_buffer_tokens
        self._default_emotion = default_emotion

        # Populated by _load_config.
        self._emotions: dict[str, dict[str, str]] = {}
        self._contextual_triggers: list[dict[str, Any]] = []
        self._keyword_fallback: dict[str, list[str]] = {}

        self._load_config()

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Load and validate the emotion map YAML file.

        Populates ``_emotions``, ``_contextual_triggers`` (flattened), and
        ``_keyword_fallback``.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            ValueError: If required top-level keys are missing.
        """
        path = Path(self._emotion_map_path)
        if not path.is_absolute():
            # Resolve relative to the project root (two levels up from this file).
            project_root = Path(__file__).resolve().parent.parent
            path = project_root / path

        if not path.exists():
            raise FileNotFoundError(
                f"Emotion map not found: {path}. "
                "Ensure config/emotion_map.yaml exists in the project root."
            )

        logger.info("Loading emotion map from %s", path)

        with open(path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            raise ValueError(
                f"Emotion map YAML must be a mapping, got {type(raw).__name__}"
            )

        # --- emotions ---
        self._emotions = raw.get("emotions", {})
        if not self._emotions:
            logger.warning("No emotions defined in %s", path)

        # --- contextual_triggers (flatten category -> list) ---
        self._contextual_triggers = self._flatten_triggers(
            raw.get("contextual_triggers", {})
        )

        # --- keyword_fallback ---
        self._keyword_fallback = raw.get("keyword_fallback", {})
        if not self._keyword_fallback:
            logger.warning("No keyword_fallback entries in %s", path)

        logger.info(
            "Emotion map loaded: %d emotions, %d contextual triggers, "
            "%d keyword groups",
            len(self._emotions),
            len(self._contextual_triggers),
            len(self._keyword_fallback),
        )

    @staticmethod
    def _flatten_triggers(
        categories: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Flatten the nested contextual_triggers structure.

        Each trigger entry gains a ``category`` key from its parent group and
        is normalized so that ``patterns`` are lowercased for case-insensitive
        matching. The returned list is sorted by descending priority so that
        the first match wins.
        """
        flat: list[dict[str, Any]] = []
        for category, entries in categories.items():
            for entry in entries:
                trigger = dict(entry)  # shallow copy
                trigger["category"] = category
                # Normalize patterns to lowercase for matching.
                trigger["patterns"] = [
                    p.lower() for p in trigger.get("patterns", [])
                ]
                flat.append(trigger)

        # Higher priority first so first-match semantics are correct.
        flat.sort(key=lambda t: t.get("priority", 0), reverse=True)
        return flat

    # ------------------------------------------------------------------
    # Public parsing methods
    # ------------------------------------------------------------------

    def parse_tag(self, text: str) -> Optional[str]:
        """Extract an emotion tag from text using regex.

        Looks for the pattern ``[word]`` and returns the lowercased word if
        it corresponds to a known emotion. Unknown tags are logged and
        discarded.

        Args:
            text: Raw text to scan.

        Returns:
            The emotion string (e.g. ``"happy"``) or ``None``.
        """
        match = _TAG_PATTERN.search(text)
        if match is None:
            return None

        tag = match.group(1).lower()
        if tag in self._emotions:
            return tag

        logger.debug(
            "Matched tag [%s] but it is not a known emotion; ignoring", tag
        )
        return None

    def parse_keywords(self, text: str) -> Optional[str]:
        """Scan text for keyword-based emotion detection.

        Iterates through keyword groups and returns the first emotion whose
        keyword list contains a match. Matching is case-insensitive.

        Args:
            text: Raw text to scan.

        Returns:
            The matched emotion string or ``None``.
        """
        text_lower = text.lower()
        for emotion, keywords in self._keyword_fallback.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    logger.debug(
                        "Keyword fallback matched '%s' -> %s", keyword, emotion
                    )
                    return emotion
        return None

    def parse_contextual(self, text: str) -> Optional[dict[str, Any]]:
        """Check text against contextual trigger patterns.

        Returns the first (highest-priority) trigger whose pattern list
        contains a substring match against the input text.

        Args:
            text: Text to scan (user speech or Gemini output).

        Returns:
            A trigger config dict with keys like ``file``/``directory``,
            ``duration``, ``priority``, ``category``, and ``patterns``; or
            ``None`` if no trigger matches.
        """
        text_lower = text.lower()
        for trigger in self._contextual_triggers:
            for pattern in trigger["patterns"]:
                if pattern in text_lower:
                    logger.info(
                        "Contextual trigger matched: '%s' (category=%s, priority=%d)",
                        pattern,
                        trigger.get("category", "unknown"),
                        trigger.get("priority", 0),
                    )
                    return trigger
        return None

    def get_emotion_directory(self, emotion: str) -> str:
        """Resolve an emotion string to its animation directory path.

        Follows the fallback chain defined in ``emotion_map.yaml``. If the
        resolved directory does not exist on disk, the chain is followed
        until a valid directory is found or the default emotion is reached.

        Args:
            emotion: The emotion to resolve (e.g. ``"excited"``).

        Returns:
            Filesystem path to the animation directory.
        """
        visited: set[str] = set()
        current = emotion.lower()

        while current and current not in visited:
            visited.add(current)
            entry = self._emotions.get(current)
            if entry is None:
                logger.warning(
                    "Unknown emotion '%s'; falling back to '%s'",
                    current,
                    self._default_emotion,
                )
                current = self._default_emotion
                continue

            directory = entry.get("directory", "")
            if directory and os.path.isdir(directory):
                return directory

            # Directory missing on disk -- follow the fallback chain.
            fallback = entry.get("fallback", self._default_emotion)
            if fallback == current:
                # Self-referential fallback; break to avoid infinite loop.
                break
            logger.debug(
                "Directory for '%s' not found (%s); trying fallback '%s'",
                current,
                directory,
                fallback,
            )
            current = fallback

        # Ultimate fallback: return the configured directory even if it does
        # not exist yet (the animation engine handles missing dirs gracefully).
        default_entry = self._emotions.get(self._default_emotion, {})
        return default_entry.get(
            "directory",
            f"data/animations/emotions/{self._default_emotion}",
        )

    def strip_tag(self, text: str) -> str:
        """Remove the first ``[emotion]`` tag from text for display.

        Only strips tags that correspond to known emotions so that
        legitimate bracket usage (e.g. ``[1]`` footnotes) is preserved.

        Args:
            text: Raw text potentially containing an emotion tag.

        Returns:
            Cleaned text with the tag removed and surrounding whitespace
            collapsed.
        """
        match = _TAG_PATTERN.search(text)
        if match is None:
            return text

        tag = match.group(1).lower()
        if tag not in self._emotions:
            return text

        # Remove the matched tag and clean up whitespace.
        cleaned = text[: match.start()] + text[match.end() :]
        # Collapse any double-spaces left behind.
        cleaned = re.sub(r"  +", " ", cleaned).strip()
        return cleaned

    # ------------------------------------------------------------------
    # Stream processing
    # ------------------------------------------------------------------

    async def process_stream(
        self,
        text_queue: asyncio.Queue[str],
        emotion_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Main processing loop -- bridges text_queue to emotion_queue.

        Runs indefinitely (designed to be wrapped in an ``asyncio.Task``
        and cancelled on shutdown). For each "turn" of text:

        1. Buffer the first ``tag_buffer_tokens`` tokens.
        2. Try regex tag extraction on the buffered text.
        3. If no tag, run keyword fallback.
        4. If neither, emit ``"neutral"``.
        5. Put the result on ``emotion_queue`` immediately.
        6. Continue scanning *all* remaining text for contextual triggers.

        A turn boundary is signalled by the sentinel ``""`` (empty string)
        on ``text_queue``.

        Args:
            text_queue: Incoming text chunks from the voice pipeline.
            emotion_queue: Outgoing emotion events for the visualizer.
        """
        logger.info(
            "EmotionParser stream processor started "
            "(buffer_tokens=%d, default=%s)",
            self._tag_buffer_tokens,
            self._default_emotion,
        )

        while True:
            try:
                await self._process_one_turn(text_queue, emotion_queue)
            except asyncio.CancelledError:
                logger.info("EmotionParser stream processor cancelled")
                raise
            except Exception:
                logger.exception(
                    "Unexpected error in EmotionParser stream processor; "
                    "continuing"
                )
                # Yield control briefly to avoid tight error loops.
                await asyncio.sleep(0.1)

    async def _process_one_turn(
        self,
        text_queue: asyncio.Queue[str],
        emotion_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Process a single turn of text from the voice pipeline.

        A turn consists of sequential text chunks terminated by an empty
        string sentinel.
        """
        buffer: list[str] = []
        token_count: int = 0
        emotion_emitted: bool = False
        full_text_parts: list[str] = []

        while True:
            chunk = await text_queue.get()

            # Empty string signals end of turn.
            if chunk == "":
                break

            full_text_parts.append(chunk)

            # --- Phase 1: Buffer first N tokens for tag/keyword detection ---
            if not emotion_emitted:
                buffer.append(chunk)
                # Approximate token count by whitespace splitting.
                token_count += len(chunk.split())

                if token_count >= self._tag_buffer_tokens:
                    buffered_text = " ".join(buffer)
                    result = self._resolve_emotion(buffered_text)
                    await emotion_queue.put(result)
                    emotion_emitted = True
                    logger.debug("Emitted emotion after buffering: %s", result)

            # --- Phase 2: Contextual trigger scan (runs on every chunk) ---
            contextual = self.parse_contextual(chunk)
            if contextual is not None:
                ctx_result: dict[str, Any] = {
                    "type": "contextual",
                    "emotion": None,
                    "trigger": contextual,
                }
                await emotion_queue.put(ctx_result)
                logger.debug("Emitted contextual trigger: %s", ctx_result)

        # End of turn -- emit emotion if we never hit the buffer threshold
        # (short responses).
        if not emotion_emitted:
            buffered_text = " ".join(buffer) if buffer else ""
            result = self._resolve_emotion(buffered_text)
            await emotion_queue.put(result)
            logger.debug("Emitted emotion at end of turn: %s", result)

        # Run contextual scan over the full assembled text as well, in case
        # a multi-word pattern spans chunk boundaries.
        full_text = " ".join(full_text_parts)
        contextual = self.parse_contextual(full_text)
        if contextual is not None:
            ctx_result = {
                "type": "contextual",
                "emotion": None,
                "trigger": contextual,
            }
            await emotion_queue.put(ctx_result)
            logger.debug(
                "Emitted contextual trigger (full-text rescan): %s", ctx_result
            )

    def _resolve_emotion(self, text: str) -> dict[str, Any]:
        """Apply the tag -> keyword -> default cascade and return a result dict.

        Args:
            text: Buffered text from the start of the turn.

        Returns:
            A dict with keys ``type``, ``emotion``, and ``directory``.
        """
        # 1. Try regex tag.
        emotion = self.parse_tag(text)
        if emotion is not None:
            return {
                "type": "emotion",
                "emotion": emotion,
                "directory": self.get_emotion_directory(emotion),
            }

        # 2. Try keyword fallback.
        emotion = self.parse_keywords(text)
        if emotion is not None:
            return {
                "type": "emotion",
                "emotion": emotion,
                "directory": self.get_emotion_directory(emotion),
            }

        # 3. Default.
        return {
            "type": "emotion",
            "emotion": self._default_emotion,
            "directory": self.get_emotion_directory(self._default_emotion),
        }
