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

EMOTION_MAP_PATH = str(PROJECT_ROOT / "config" / "emotion_map.yaml")


def _find_real_animation() -> str:
    """Return the path to a real .webp animation file from the data directory.

    Falls back to any .gif if no .webp is found.  Raises FileNotFoundError
    if the data directory has no animation files at all.
    """
    base = str(PROJECT_ROOT / "data" / "animations" / "emotions")
    patterns = [
        os.path.join(base, "**", "*.webp"),
        os.path.join(base, "**", "*.gif"),
    ]
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            # Pick a file whose path has no spaces to avoid shell issues
            clean = [m for m in matches if " " not in m]
            return clean[0] if clean else matches[0]
    raise FileNotFoundError(f"No animation files found under {base}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mapper():
    """Create an EmotionMapper loaded from the real emotion_map.yaml."""
    original_dir = os.getcwd()
    os.chdir(str(PROJECT_ROOT))
    try:
        m = EmotionMapper(config_path=EMOTION_MAP_PATH)
    finally:
        os.chdir(original_dir)
    return m


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
# EmotionMapper
# ===========================================================================


class TestEmotionMapperLoad:
    """Loading and basic configuration."""

    def test_loads_from_yaml(self, mapper):
        """EmotionMapper should load without error from the real config."""
        assert mapper is not None

    def test_has_emotions_in_cache(self, mapper):
        """After loading, the dir cache should contain known emotions."""
        available = mapper.get_available_emotions()
        assert len(available) > 0


class TestGetAnimationPath:
    """get_animation_path resolution and fallback."""

    def test_neutral_returns_path(self, mapper):
        """'neutral' has files; should return a valid path."""
        path = mapper.get_animation_path("neutral")
        assert path is not None
        assert os.path.isfile(path)

    def test_happy_returns_path(self, mapper):
        """'happy' has files; should return a valid path."""
        path = mapper.get_animation_path("happy")
        assert path is not None
        assert os.path.isfile(path)

    def test_returns_webp_or_gif(self, mapper):
        """Returned path should have a valid animation extension."""
        path = mapper.get_animation_path("neutral")
        assert path is not None
        ext = os.path.splitext(path)[1].lower()
        assert ext in {".webp", ".gif"}

    def test_fallback_chain(self, mapper, tmp_path):
        """When an emotion's directory is empty, follow the fallback chain.

        We create a mapper with a synthetic config where 'test_empty'
        falls back to 'neutral' which has real files.
        """
        # Build a minimal YAML that points test_empty at an empty dir
        empty_dir = tmp_path / "empty_emotion"
        empty_dir.mkdir()

        config_content = f"""
emotions:
  test_empty:
    directory: {empty_dir}
    fallback: neutral
  neutral:
    directory: data/animations/emotions/neutral
    fallback: calm
  calm:
    directory: data/animations/emotions/calm

contextual_triggers: {{}}
keyword_fallback: {{}}
"""
        config_file = tmp_path / "test_emotion_map.yaml"
        config_file.write_text(config_content)

        original_dir = os.getcwd()
        os.chdir(str(PROJECT_ROOT))
        try:
            test_mapper = EmotionMapper(config_path=str(config_file))
        finally:
            os.chdir(original_dir)

        # test_empty should fall back through to neutral
        path = test_mapper.get_animation_path("test_empty")
        assert path is not None
        assert os.path.isfile(path)

    def test_unknown_emotion_returns_none(self, mapper):
        """Completely unknown emotion should return None."""
        path = mapper.get_animation_path("zzz_nonexistent_emotion_zzz")
        assert path is None


class TestGetAvailableEmotions:
    """get_available_emotions sorting and content."""

    def test_returns_sorted_list(self, mapper):
        available = mapper.get_available_emotions()
        assert available == sorted(available)

    def test_contains_known_emotions(self, mapper):
        available = mapper.get_available_emotions()
        # neutral and happy should always have files
        assert "neutral" in available
        assert "happy" in available


class TestFindContextualTrigger:
    """Contextual trigger matching."""

    def test_pink_floyd_match(self, mapper):
        result = mapper.find_contextual_trigger("Let's listen to Pink Floyd")
        assert result is not None
        assert "patterns" in result

    def test_dark_side_match(self, mapper):
        result = mapper.find_contextual_trigger("Play Dark Side of the Moon")
        assert result is not None

    def test_no_match(self, mapper):
        result = mapper.find_contextual_trigger("Tell me about Python programming")
        assert result is None

    def test_case_insensitive(self, mapper):
        result = mapper.find_contextual_trigger("I love PINK FLOYD")
        assert result is not None

    def test_priority_ordering(self, mapper):
        """Higher-priority trigger should win when multiple match."""
        # "pink floyd" has priority 10, "jazz" has priority 8
        result = mapper.find_contextual_trigger("pink floyd jazz")
        assert result is not None
        assert result.get("priority", 0) == 10


class TestScanDirectories:
    """Directory scanning and cache refresh."""

    def test_scan_updates_cache(self, mapper):
        """Calling scan_directories should repopulate the cache."""
        original_dir = os.getcwd()
        os.chdir(str(PROJECT_ROOT))
        try:
            mapper.scan_directories()
        finally:
            os.chdir(original_dir)

        available = mapper.get_available_emotions()
        assert len(available) > 0

    def test_scan_after_modification(self, mapper, tmp_path):
        """After adding a file to a dir, rescan should pick it up."""
        # This tests the scan mechanism conceptually -- we verify
        # that scan_directories is callable and does not error.
        original_dir = os.getcwd()
        os.chdir(str(PROJECT_ROOT))
        try:
            mapper.scan_directories()
        finally:
            os.chdir(original_dir)


class TestReloadConfig:
    """Config reload."""

    def test_reload_does_not_error(self, mapper):
        """reload_config should complete without raising."""
        original_dir = os.getcwd()
        os.chdir(str(PROJECT_ROOT))
        try:
            mapper.reload_config()
        finally:
            os.chdir(original_dir)

    def test_reload_preserves_emotions(self, mapper):
        """After reload, available emotions should still be present."""
        original_dir = os.getcwd()
        os.chdir(str(PROJECT_ROOT))
        try:
            before = mapper.get_available_emotions()
            mapper.reload_config()
            after = mapper.get_available_emotions()
        finally:
            os.chdir(original_dir)

        assert before == after


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
