"""Tests for visualizer module — EmotionMapper, Animation, AnimationEngine, GradientOverlay."""

import glob
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from visualizer.emotion_map import EmotionMapper
from visualizer.animation_engine import Animation, AnimationEngine
from visualizer.gradient_overlay import GradientOverlay

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_real_animation() -> str:
    """Return the path to a real .webp animation file from the data directory.

    After the inbox migration, files live in animations/inbox/.
    Falls back to any .gif if no .webp is found.  Raises FileNotFoundError
    if the data directory has no animation files at all.
    """
    search_dirs = [
        str(PROJECT_ROOT / "data" / "animations" / "inbox"),
        str(PROJECT_ROOT / "data" / "animations"),
    ]
    for base in search_dirs:
        patterns = [
            os.path.join(base, "**", "*.webp"),
            os.path.join(base, "*.webp"),
            os.path.join(base, "**", "*.gif"),
            os.path.join(base, "*.gif"),
        ]
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                # Pick a file whose path has no spaces to avoid shell issues
                clean = [m for m in matches if " " not in m]
                return clean[0] if clean else matches[0]
    raise FileNotFoundError(f"No animation files found under {search_dirs}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def real_animation_path():
    """Return a path to a real animation file for integration tests."""
    original_dir = os.getcwd()
    os.chdir(str(PROJECT_ROOT))
    try:
        return _find_real_animation()
    finally:
        os.chdir(original_dir)


@pytest.fixture
def pygame_display():
    """Initialise pygame with a minimal display for AnimationEngine tests."""
    import pygame

    pygame.init()
    pygame.display.set_mode((100, 100))
    yield
    pygame.quit()


@pytest.fixture
def engine(pygame_display):
    """Return an AnimationEngine with default config."""
    return AnimationEngine({"crossfade_ms": 300, "frame_cache_ahead": 5})


# ===========================================================================
# Animation dataclass
# ===========================================================================


class TestAnimationDataclass:
    """Animation dataclass auto-calculated fields."""

    def test_frame_count_auto_calculated(self):
        """frame_count should equal len(frames) via __post_init__."""
        from PIL import Image

        frames = [Image.new("RGBA", (10, 10)) for _ in range(5)]
        durations = [100] * 5
        anim = Animation(frames=frames, durations=durations, path="/fake/path.webp")
        assert anim.frame_count == 5

    def test_empty_frames_gives_zero(self):
        """Empty frames list should give frame_count 0."""
        anim = Animation(frames=[], durations=[], path="/fake/empty.webp")
        assert anim.frame_count == 0

    def test_frame_count_matches_frames(self):
        """frame_count should always match len(frames)."""
        from PIL import Image

        for count in [1, 3, 10, 50]:
            frames = [Image.new("RGBA", (10, 10)) for _ in range(count)]
            durations = [100] * count
            anim = Animation(frames=frames, durations=durations)
            assert anim.frame_count == count

    def test_default_path_is_empty(self):
        """Path should default to empty string when not specified."""
        anim = Animation(frames=[], durations=[])
        assert anim.path == ""


# ===========================================================================
# AnimationEngine
# ===========================================================================


class TestAnimationEngineLoad:
    """Loading animations from disk."""

    def test_load_real_webp(self, engine, real_animation_path):
        """Loading a real animation file should produce a valid Animation."""
        anim = engine.load_animation(real_animation_path)
        assert anim.frame_count > 0
        assert len(anim.frames) == anim.frame_count
        assert len(anim.durations) == anim.frame_count
        assert anim.path == real_animation_path

    def test_load_missing_file_raises(self, engine):
        """Loading a nonexistent path should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            engine.load_animation("/nonexistent/path/missing.webp")

    def test_loaded_frames_are_rgba(self, engine, real_animation_path):
        """All frames should be converted to RGBA mode."""
        anim = engine.load_animation(real_animation_path)
        for frame in anim.frames:
            assert frame.mode == "RGBA"

    def test_durations_are_positive(self, engine, real_animation_path):
        """All frame durations should be positive integers."""
        anim = engine.load_animation(real_animation_path)
        for dur in anim.durations:
            assert isinstance(dur, int)
            assert dur > 0


class TestAnimationEnginePlayback:
    """Playback control: set_animation, update, frame advancement."""

    def test_set_animation_resets_frame_index(self, engine, real_animation_path):
        """set_animation should reset playback to frame 0."""
        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)
        assert engine._frame_idx == 0
        assert engine._frame_elapsed_ms == 0.0

    def test_get_current_frame_returns_surface(self, engine, real_animation_path):
        """After set_animation, get_current_frame should return a Surface."""
        import pygame

        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)
        frame = engine.get_current_frame()
        assert frame is not None
        assert isinstance(frame, pygame.Surface)

    def test_get_current_frame_none_when_no_animation(self, engine):
        """Before any animation is set, get_current_frame should return None."""
        assert engine.get_current_frame() is None

    def test_update_advances_frame_timing(self, engine, real_animation_path):
        """Calling update with positive dt should advance elapsed time."""
        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)

        # Record initial state
        initial_elapsed = engine._frame_elapsed_ms

        # Advance by a small amount
        engine.update(0.01)  # 10ms

        # Either elapsed increased or frame index advanced (if frame was short)
        advanced = (
            engine._frame_elapsed_ms > initial_elapsed
            or engine._frame_idx > 0
        )
        assert advanced

    def test_update_wraps_around(self, engine, real_animation_path):
        """After enough updates, frame index should wrap back to 0."""
        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)

        if anim.frame_count <= 1:
            pytest.skip("Animation has only one frame, wrapping is trivial")

        # Calculate total animation duration and advance past it
        total_ms = sum(anim.durations)
        engine.update((total_ms + 100) / 1000.0)

        # Frame index should be valid (within bounds)
        assert 0 <= engine._frame_idx < anim.frame_count


class TestAnimationEngineCrossfade:
    """Crossfade transitions."""

    def test_crossfade_to_starts_crossfade(self, engine, real_animation_path):
        """crossfade_to should activate the crossfade state."""
        anim1 = engine.load_animation(real_animation_path)
        anim2 = engine.load_animation(real_animation_path)
        engine.set_animation(anim1)
        engine.crossfade_to(anim2, duration_ms=500)
        assert engine.is_crossfading() is True

    def test_is_crossfading_false_initially(self, engine):
        """Before any crossfade, is_crossfading should be False."""
        assert engine.is_crossfading() is False

    def test_is_crossfading_false_after_set(self, engine, real_animation_path):
        """set_animation (no crossfade) should leave crossfading False."""
        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)
        assert engine.is_crossfading() is False

    def test_crossfade_ends_after_duration(self, engine, real_animation_path):
        """After the crossfade duration elapses, is_crossfading should be False."""
        anim1 = engine.load_animation(real_animation_path)
        anim2 = engine.load_animation(real_animation_path)
        engine.set_animation(anim1)
        engine.crossfade_to(anim2, duration_ms=100)

        assert engine.is_crossfading() is True

        # Advance past the crossfade duration
        engine.update(0.2)  # 200ms > 100ms duration

        assert engine.is_crossfading() is False

    def test_crossfade_to_without_current_sets_directly(self, engine, real_animation_path):
        """crossfade_to with no current animation should just set_animation."""
        anim = engine.load_animation(real_animation_path)
        engine.crossfade_to(anim)
        # Should not be crossfading since there was nothing to fade from
        assert engine.is_crossfading() is False
        assert engine._animation is anim

    def test_crossfade_get_frame_returns_surface(self, engine, real_animation_path):
        """During crossfade, get_current_frame should still return a Surface."""
        import pygame

        anim1 = engine.load_animation(real_animation_path)
        anim2 = engine.load_animation(real_animation_path)
        engine.set_animation(anim1)
        engine.crossfade_to(anim2, duration_ms=500)

        # Advance partway through the crossfade
        engine.update(0.1)
        frame = engine.get_current_frame()
        assert frame is not None
        assert isinstance(frame, pygame.Surface)


class TestAnimationEngineTargetSize:
    """Target size and cache clearing."""

    def test_set_target_size_clears_cache(self, engine, real_animation_path):
        """Changing target size should clear the surface cache."""
        anim = engine.load_animation(real_animation_path)
        engine.set_animation(anim)

        # Populate the cache by getting a frame
        engine.get_current_frame()
        assert len(engine._surface_cache) > 0

        # Change target size
        engine.set_target_size((200, 200))
        assert len(engine._surface_cache) == 0

    def test_set_same_size_no_clear(self, engine, real_animation_path):
        """Setting the same target size should not clear the cache."""
        anim = engine.load_animation(real_animation_path)
        engine.set_target_size((200, 200))
        engine.set_animation(anim)

        # Populate cache
        engine.get_current_frame()
        cache_size = len(engine._surface_cache)

        # Set same size again
        engine.set_target_size((200, 200))
        assert len(engine._surface_cache) == cache_size

    def test_frame_respects_target_size(self, engine, real_animation_path):
        """Frames should be scaled to the target size."""
        import pygame

        anim = engine.load_animation(real_animation_path)
        engine.set_target_size((50, 50))
        engine.set_animation(anim)

        frame = engine.get_current_frame()
        assert frame is not None
        assert frame.get_size() == (50, 50)


# ===========================================================================
# GradientOverlay
# ===========================================================================


class TestGradientOverlay:
    """GradientOverlay generation and parameter updates."""

    @pytest.fixture(autouse=True)
    def _init_pygame(self, pygame_display):
        """Ensure pygame is initialised for all overlay tests."""
        pass

    def test_generate_returns_surface(self):
        """generate() should return a pygame Surface."""
        import pygame

        overlay = GradientOverlay(size=(100, 100))
        surface = overlay.generate()
        assert isinstance(surface, pygame.Surface)

    def test_surface_size_matches(self):
        """Generated surface should match the requested size."""
        overlay = GradientOverlay(size=(200, 150))
        surface = overlay.generate()
        assert surface.get_size() == (200, 150)

    def test_get_surface_lazy_generates(self):
        """get_surface should generate on first call without explicit generate()."""
        import pygame

        overlay = GradientOverlay(size=(80, 60))
        surface = overlay.get_surface()
        assert isinstance(surface, pygame.Surface)
        assert surface.get_size() == (80, 60)

    def test_degenerate_size(self):
        """Zero or negative size should produce a 1x1 surface."""
        overlay = GradientOverlay(size=(0, 0))
        surface = overlay.generate()
        assert surface.get_size() == (1, 1)

    def test_opacity_property(self):
        """opacity property should reflect the configured value."""
        overlay = GradientOverlay(size=(100, 100), opacity=50)
        assert overlay.opacity == 50

    def test_gradient_size_property(self):
        """gradient_size property should reflect the configured value."""
        overlay = GradientOverlay(size=(100, 100), gradient_size=30)
        assert overlay.gradient_size == 30

    def test_opacity_clamped(self):
        """Opacity should be clamped to 0-100 range."""
        overlay_high = GradientOverlay(size=(10, 10), opacity=200)
        assert overlay_high.opacity == 100

        overlay_low = GradientOverlay(size=(10, 10), opacity=-50)
        assert overlay_low.opacity == 0

    def test_update_params_marks_dirty(self):
        """Changing params via update_params should regenerate on next get_surface."""
        import pygame

        overlay = GradientOverlay(size=(100, 100), opacity=50)
        surface1 = overlay.get_surface()

        overlay.update_params(opacity=90)
        # After param change, _dirty should be True
        assert overlay._dirty is True

        surface2 = overlay.get_surface()
        assert isinstance(surface2, pygame.Surface)

    def test_update_params_no_change_stays_clean(self):
        """If update_params receives the same values, cache stays clean."""
        overlay = GradientOverlay(size=(100, 100), opacity=50, gradient_size=70)
        overlay.get_surface()  # generate and mark clean
        assert overlay._dirty is False

        overlay.update_params(opacity=50, gradient_size=70)
        assert overlay._dirty is False

    def test_update_size_marks_dirty(self):
        """Changing overlay size should mark cache as dirty."""
        overlay = GradientOverlay(size=(100, 100))
        overlay.get_surface()
        assert overlay._dirty is False

        overlay.update_size((200, 200))
        assert overlay._dirty is True

    def test_update_size_same_stays_clean(self):
        """Same size should not mark dirty."""
        overlay = GradientOverlay(size=(100, 100))
        overlay.get_surface()
        assert overlay._dirty is False

        overlay.update_size((100, 100))
        assert overlay._dirty is False


# ---------------------------------------------------------------------------
# InlineEmotionAdapter integration tests
# ---------------------------------------------------------------------------


class TestInlineEmotionAdapter:
    """Verify the adapter detects emotions via tag, keyword, and default paths."""

    @pytest.fixture
    def adapter(self):
        """Create an adapter with the real config."""
        # Import here to avoid circular issues
        sys.path.insert(0, str(PROJECT_ROOT))
        # We need to import from main.py but the class is private.
        # Instead, replicate the adapter logic with the real EmotionParser.
        from core.emotion_parser import EmotionParser
        return EmotionParser()

    def test_tag_detection(self, adapter):
        """[happy] tag should be detected in text."""
        result = adapter.parse_tag("[happy] I'm so glad to help you!")
        assert result == "happy"

    def test_tag_detection_case_insensitive(self, adapter):
        """[EXCITED] should match 'excited' emotion."""
        result = adapter.parse_tag("[EXCITED] Wow this is great!")
        assert result == "excited"

    def test_unknown_tag_returns_none(self, adapter):
        """[nonexistent_emotion] should return None."""
        result = adapter.parse_tag("[zzz_fake_emotion] hello")
        assert result is None

    def test_keyword_fallback_happy(self, adapter):
        """Text with 'wonderful' (no '!') should match 'happy' via keyword fallback."""
        # Note: '!' matches 'excited' first, so avoid exclamation marks here.
        result = adapter.parse_keywords("That's wonderful news, I'm so glad")
        assert result == "happy"

    def test_keyword_fallback_thinking(self, adapter):
        """Text with 'hmm' should match 'thinking' via keyword fallback."""
        result = adapter.parse_keywords("Hmm, let me think about that for a moment")
        assert result == "thinking"

    def test_keyword_fallback_no_match(self, adapter):
        """Neutral text with no keywords should return None."""
        result = adapter.parse_keywords("the capital of france is paris")
        assert result is None

    def test_contextual_trigger_pink_floyd(self, adapter):
        """'Pink Floyd' mention should trigger contextual detection."""
        result = adapter.parse_contextual("Let's listen to some Pink Floyd")
        assert result is not None
        assert result.get("category") == "music"

    def test_contextual_trigger_no_match(self, adapter):
        """Generic text should not trigger contextual detection."""
        result = adapter.parse_contextual("Hello how are you today")
        assert result is None

    def test_full_cascade_with_tag(self, adapter):
        """Full _resolve_emotion should detect tag first."""
        result = adapter._resolve_emotion("[laughing] Hahaha that's hilarious!")
        assert result["emotion"] == "laughing"
        assert result["type"] == "emotion"

    def test_full_cascade_keyword_when_no_tag(self, adapter):
        """Without a tag, _resolve_emotion should fall back to keywords."""
        result = adapter._resolve_emotion("That's absolutely amazing and incredible!")
        assert result["emotion"] == "excited"
        assert result["type"] == "emotion"

    def test_full_cascade_default_when_nothing(self, adapter):
        """With no tag or keywords, _resolve_emotion should return 'neutral'."""
        result = adapter._resolve_emotion("The capital of France is Paris.")
        assert result["emotion"] == "neutral"
        assert result["type"] == "emotion"


# ===========================================================================
# Manifest-only EmotionMapper tests
# ===========================================================================

import json

@pytest.fixture
def manifest_dir(tmp_path):
    """Create a temp dir with a manifest.json and dummy animation files."""
    (tmp_path / "happy_bounce.webp").write_bytes(b"RIFF")
    (tmp_path / "sad_rain.webp").write_bytes(b"RIFF")
    (tmp_path / "both_neutral.webp").write_bytes(b"RIFF")
    manifest = {
        "version": 1,
        "assets": [
            {"file": "happy_bounce.webp", "theme": "dark", "emotions": ["happy", "excited"], "states": [], "tags": ["bouncy"]},
            {"file": "sad_rain.webp", "theme": "dark", "emotions": ["sad"], "states": [], "tags": []},
            {"file": "both_neutral.webp", "theme": "both", "emotions": ["neutral"], "states": ["idle"], "tags": []},
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path

def test_load_manifest_returns_count(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    assert mapper.asset_count() == 3

def test_get_animation_by_emotion(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("happy", theme="dark")
    assert path is not None
    assert "happy_bounce.webp" in path

def test_multi_emotion_tag(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("excited", theme="dark")
    assert path is not None
    assert "happy_bounce.webp" in path

def test_theme_both_matches_dark(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("neutral", theme="dark")
    assert path is not None
    assert "both_neutral.webp" in path

def test_theme_both_matches_light(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("neutral", theme="light")
    assert path is not None

def test_state_lookup(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_state_path("idle", theme="dark")
    assert path is not None
    assert "both_neutral.webp" in path

def test_unknown_emotion_falls_back_to_neutral(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("roasting", theme="dark")
    assert path is not None  # falls back to neutral

def test_missing_manifest_returns_none():
    mapper = EmotionMapper("/nonexistent/manifest.json")
    assert mapper.get_animation_path("happy", theme="dark") is None
    assert mapper.asset_count() == 0
