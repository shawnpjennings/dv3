"""Tests for core.emotion_parser — tag extraction, keyword fallback, contextual triggers."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.emotion_parser import EmotionParser


@pytest.fixture
def parser():
    """Create a parser loaded from the real emotion_map.yaml."""
    return EmotionParser(
        emotion_map_path=str(PROJECT_ROOT / "config" / "emotion_map.yaml")
    )


class TestParseTag:
    """Regex tag extraction."""

    def test_basic_tag(self, parser):
        result = parser.parse_tag("[happy] That's great!")
        assert result == "happy"

    def test_tag_case_insensitive(self, parser):
        result = parser.parse_tag("[HAPPY] That's great!")
        assert result == "happy"

    def test_no_tag(self, parser):
        result = parser.parse_tag("That's great!")
        assert result is None

    def test_unknown_tag_ignored(self, parser):
        result = parser.parse_tag("[flummoxed] What?")
        assert result is None

    def test_tag_mid_text(self, parser):
        result = parser.parse_tag("I feel [excited] about this!")
        assert result == "excited"

    def test_all_known_emotions(self, parser):
        """Every emotion in the YAML should be recognized."""
        known = [
            "happy", "excited", "sad", "thinking", "confused",
            "laughing", "surprised", "calm", "alert", "tired",
            "sarcastic", "neutral", "concerned", "curious", "proud",
        ]
        for emotion in known:
            assert parser.parse_tag(f"[{emotion}] test") == emotion


class TestParseKeywords:
    """Keyword fallback scanning."""

    def test_keyword_match(self, parser):
        result = parser.parse_keywords("That's amazing and awesome!")
        assert result is not None  # should match "excited" keywords

    def test_no_keyword_match(self, parser):
        result = parser.parse_keywords("The weather is fine")
        assert result is None

    def test_case_insensitive(self, parser):
        result = parser.parse_keywords("HAHA that was funny")
        assert result is not None


class TestParseContextual:
    """Contextual trigger matching."""

    def test_pink_floyd_trigger(self, parser):
        result = parser.parse_contextual("Let's listen to Pink Floyd")
        assert result is not None
        assert "patterns" in result

    def test_dark_side_trigger(self, parser):
        result = parser.parse_contextual("Play Dark Side of the Moon")
        assert result is not None

    def test_no_contextual_match(self, parser):
        result = parser.parse_contextual("Tell me about Python programming")
        assert result is None

    def test_weather_trigger(self, parser):
        result = parser.parse_contextual("It's raining outside")
        assert result is not None


class TestGetEmotionDirectory:
    """Directory resolution with fallback chain."""

    def test_known_emotion_returns_directory(self, parser):
        directory = parser.get_emotion_directory("happy")
        assert "happy" in directory

    def test_fallback_chain(self, parser):
        """Excited falls back to happy if its dir is missing."""
        directory = parser.get_emotion_directory("excited")
        assert directory is not None
        assert len(directory) > 0

    def test_unknown_emotion_defaults(self, parser):
        directory = parser.get_emotion_directory("nonexistent_emotion")
        assert "neutral" in directory or "calm" in directory


class TestStripTag:
    """Tag removal for display text."""

    def test_strip_known_tag(self, parser):
        result = parser.strip_tag("[happy] That's great!")
        assert "[happy]" not in result
        assert "great" in result

    def test_preserve_unknown_brackets(self, parser):
        result = parser.strip_tag("[1] First item in list")
        assert "[1]" in result

    def test_no_tag_unchanged(self, parser):
        original = "No tags here"
        assert parser.strip_tag(original) == original


class TestProcessStream:
    """Async stream processing."""

    @pytest.mark.asyncio
    async def test_basic_turn(self, parser):
        """Emit an emotion from a simple tagged turn."""
        text_q: asyncio.Queue = asyncio.Queue()
        emotion_q: asyncio.Queue = asyncio.Queue()

        # Feed a tagged turn
        await text_q.put("[happy] That's wonderful to hear!")
        await text_q.put("")  # end-of-turn sentinel

        # Run one turn of processing
        task = asyncio.create_task(
            parser.process_stream(text_q, emotion_q)
        )
        # Give it a moment to process
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert not emotion_q.empty()
        result = await emotion_q.get()
        assert result["type"] == "emotion"
        assert result["emotion"] == "happy"

    @pytest.mark.asyncio
    async def test_no_tag_defaults_to_neutral(self, parser):
        """When no tag or keyword matches, emit neutral."""
        text_q: asyncio.Queue = asyncio.Queue()
        emotion_q: asyncio.Queue = asyncio.Queue()

        await text_q.put("The temperature today is moderate")
        await text_q.put("")

        task = asyncio.create_task(
            parser.process_stream(text_q, emotion_q)
        )
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert not emotion_q.empty()
        result = await emotion_q.get()
        assert result["emotion"] == "neutral"
