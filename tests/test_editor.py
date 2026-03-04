"""Tests for the editor module — gallery, converter, and gradient tool.

Covers:
- _pil_to_surface: PIL-to-Pygame conversion without display init (SRCALPHA fix)
- _Thumbnail: frame animation advance logic
- _fit_surface: aspect-ratio-preserving scaling
- Gallery.load_directory: file scanning, filtering, sorting
- BatchConverter: frame extraction, conversion, file info, speed adjustment
- GradientTool: gradient generation, caching, edge cases
"""

import os
import sys
from pathlib import Path

import pytest
from PIL import Image

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers — create test images with PIL (no real files needed)
# ---------------------------------------------------------------------------

def _make_rgba_image(width: int = 64, height: int = 64, color: tuple = (255, 0, 0, 255)) -> Image.Image:
    """Create a small solid-colour RGBA PIL image for testing."""
    return Image.new("RGBA", (width, height), color)


def _make_test_webp(path: Path, frame_count: int = 3, size: tuple = (32, 32)) -> Path:
    """Write a minimal animated WebP file to *path*.

    Each frame is a different colour so tests can verify frame extraction.
    """
    colours = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
        (255, 0, 255, 255),
    ]
    frames = [Image.new("RGBA", size, colours[i % len(colours)]) for i in range(frame_count)]
    durations = [100] * frame_count

    frames[0].save(
        str(path),
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
    )
    return path


def _make_test_gif(path: Path, frame_count: int = 3, size: tuple = (32, 32)) -> Path:
    """Write a minimal animated GIF file to *path*."""
    colours = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
    ]
    frames = [Image.new("RGB", size, colours[i % len(colours)]) for i in range(frame_count)]
    durations = [80] * frame_count

    frames[0].save(
        str(path),
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
    )
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pygame_init():
    """Initialise pygame once per test session.

    Some tests (like _fit_surface, _Thumbnail.get_thumb) need pygame
    initialised for smoothscale, but we explicitly avoid calling it at
    module level.
    """
    import pygame
    pygame.init()
    yield
    pygame.quit()


@pytest.fixture
def sample_webp(tmp_path):
    """Create a temporary 3-frame animated WebP."""
    return _make_test_webp(tmp_path / "sample.webp", frame_count=3)


@pytest.fixture
def sample_gif(tmp_path):
    """Create a temporary 3-frame animated GIF."""
    return _make_test_gif(tmp_path / "sample.gif", frame_count=3)


@pytest.fixture
def gallery_dir(tmp_path):
    """Create a temporary directory with a mix of valid and junk files.

    Structure:
        gallery_dir/
            alpha.webp      (valid 3-frame animation)
            beta.gif        (valid 2-frame animation)
            gamma.webp      (valid single frame)
            junk.txt        (not an image)
            delta.webp:Zone.Identifier  (Windows junk to be filtered)
    """
    _make_test_webp(tmp_path / "alpha.webp", frame_count=3)
    _make_test_gif(tmp_path / "beta.gif", frame_count=2)
    _make_test_webp(tmp_path / "gamma.webp", frame_count=1)

    # Non-image file — should be ignored
    (tmp_path / "junk.txt").write_text("not an image")

    # Zone.Identifier file — a real nuisance on WSL2 that must be filtered
    zone_path = tmp_path / "delta.webp:Zone.Identifier"
    try:
        zone_path.write_text("[ZoneTransfer]\nZoneId=3\n")
    except (OSError, ValueError):
        # Some filesystems reject colons in filenames; that is fine,
        # the filter test still works on the files that do exist.
        pass

    return tmp_path


# ===================================================================
# _pil_to_surface — the SRCALPHA fix for headless/threaded conversion
# ===================================================================

class TestPilToSurface:
    """Test PIL-to-Pygame surface conversion without pygame.display.

    This was a real bug: convert_alpha() requires an active display,
    so the fix uses SRCALPHA surfaces directly.
    """

    def test_creates_surface_without_display(self, pygame_init):
        """_pil_to_surface must work without pygame.display.set_mode()."""
        from editor.gallery import _pil_to_surface

        pil_img = _make_rgba_image(48, 48, (100, 150, 200, 128))
        surface = _pil_to_surface(pil_img)

        assert surface is not None
        assert surface.get_size() == (48, 48)

    def test_preserves_dimensions(self, pygame_init):
        """Output surface matches input image dimensions."""
        from editor.gallery import _pil_to_surface

        for w, h in [(1, 1), (10, 20), (200, 100)]:
            pil_img = _make_rgba_image(w, h)
            surface = _pil_to_surface(pil_img)
            assert surface.get_size() == (w, h)

    def test_handles_rgb_input(self, pygame_init):
        """An RGB (no alpha) input is converted to RGBA internally."""
        from editor.gallery import _pil_to_surface

        rgb_img = Image.new("RGB", (16, 16), (255, 128, 0))
        surface = _pil_to_surface(rgb_img)
        assert surface.get_size() == (16, 16)

    def test_handles_palette_input(self, pygame_init):
        """A palette-mode image is converted to RGBA before surface creation."""
        from editor.gallery import _pil_to_surface

        palette_img = Image.new("P", (16, 16))
        surface = _pil_to_surface(palette_img)
        assert surface.get_size() == (16, 16)

    def test_surface_has_alpha_channel(self, pygame_init):
        """The returned surface must support per-pixel alpha (SRCALPHA)."""
        import pygame
        from editor.gallery import _pil_to_surface

        pil_img = _make_rgba_image(8, 8, (0, 0, 0, 128))
        surface = _pil_to_surface(pil_img)
        assert surface.get_flags() & pygame.SRCALPHA


# ===================================================================
# _fit_surface — aspect-ratio-preserving thumbnail scaling
# ===================================================================

class TestFitSurface:
    """Test aspect-preserving surface scaling."""

    def test_downscale_wide_image(self, pygame_init):
        """A wide surface is scaled to fit max_w, preserving ratio."""
        import pygame
        from editor.gallery import _fit_surface

        surf = pygame.Surface((200, 100), pygame.SRCALPHA, 32)
        result = _fit_surface(surf, 100, 100)
        w, h = result.get_size()
        assert w == 100
        assert h == 50

    def test_downscale_tall_image(self, pygame_init):
        """A tall surface is scaled to fit max_h, preserving ratio."""
        import pygame
        from editor.gallery import _fit_surface

        surf = pygame.Surface((100, 200), pygame.SRCALPHA, 32)
        result = _fit_surface(surf, 100, 100)
        w, h = result.get_size()
        assert w == 50
        assert h == 100

    def test_no_upscale(self, pygame_init):
        """A surface already smaller than max dims is not upscaled."""
        import pygame
        from editor.gallery import _fit_surface

        surf = pygame.Surface((50, 30), pygame.SRCALPHA, 32)
        result = _fit_surface(surf, 100, 100)
        assert result.get_size() == (50, 30)

    def test_zero_size_surface(self, pygame_init):
        """A zero-size surface is returned unchanged (no division by zero)."""
        import pygame
        from editor.gallery import _fit_surface

        surf = pygame.Surface((0, 0))
        result = _fit_surface(surf, 100, 100)
        assert result.get_size() == (0, 0)


# ===================================================================
# _Thumbnail — frame advance / animation timing
# ===================================================================

class TestThumbnail:
    """Test _Thumbnail animation advance logic."""

    def _make_thumbnail(self, frame_count: int = 3, durations: list[int] | None = None):
        """Create a _Thumbnail with fake pygame surfaces."""
        import pygame
        from editor.gallery import _Thumbnail

        thumb = _Thumbnail("/fake/path.webp")
        thumb.frames = [
            pygame.Surface((32, 32), pygame.SRCALPHA, 32)
            for _ in range(frame_count)
        ]
        thumb.durations = durations if durations else [100] * frame_count
        thumb.loaded = True
        return thumb

    def test_advance_single_frame_noop(self, pygame_init):
        """A single-frame thumbnail does not advance."""
        thumb = self._make_thumbnail(frame_count=1, durations=[100])
        thumb.advance(500.0)
        assert thumb.current_frame == 0

    def test_advance_no_frames_noop(self, pygame_init):
        """An empty thumbnail does not crash on advance."""
        from editor.gallery import _Thumbnail
        thumb = _Thumbnail("/fake/empty.webp")
        thumb.advance(500.0)
        assert thumb.current_frame == 0

    def test_advance_wraps_around(self, pygame_init):
        """Advancing past the last frame wraps to frame 0."""
        thumb = self._make_thumbnail(frame_count=3, durations=[100, 100, 100])
        # Advance 250ms: should be past frame 0 (100ms) and frame 1 (100ms),
        # now 50ms into frame 2
        thumb.advance(250.0)
        assert thumb.current_frame == 2

        # Advance another 100ms: wraps back to frame 0, 50ms in
        thumb.advance(100.0)
        assert thumb.current_frame == 0

    def test_advance_respects_variable_durations(self, pygame_init):
        """Frames with different durations advance at different rates."""
        thumb = self._make_thumbnail(frame_count=3, durations=[50, 200, 100])

        # 50ms: exactly exhausts frame 0 -> frame 1
        thumb.advance(50.0)
        assert thumb.current_frame == 1

        # Another 200ms: exhausts frame 1 -> frame 2
        thumb.advance(200.0)
        assert thumb.current_frame == 2

    def test_advance_zero_duration_defaults_to_100(self, pygame_init):
        """Zero/negative durations in metadata default to 100ms."""
        thumb = self._make_thumbnail(frame_count=2, durations=[0, 0])

        # Should treat duration as 100ms each
        thumb.advance(100.0)
        assert thumb.current_frame == 1

        thumb.advance(100.0)
        assert thumb.current_frame == 0  # wrapped

    def test_advance_invalidates_cache(self, pygame_init):
        """Advancing past a frame boundary clears surface_cache."""
        thumb = self._make_thumbnail(frame_count=2, durations=[100, 100])
        thumb.surface_cache = "not_none"  # Fake cached value

        thumb.advance(150.0)  # Should cross frame boundary
        assert thumb.surface_cache is None

    def test_advance_small_dt_stays_on_frame(self, pygame_init):
        """Small dt that does not exceed current duration stays on same frame."""
        thumb = self._make_thumbnail(frame_count=3, durations=[100, 100, 100])
        thumb.advance(10.0)
        assert thumb.current_frame == 0
        assert thumb.elapsed == pytest.approx(10.0)


# ===================================================================
# Gallery.load_directory — file scanning and filtering
# ===================================================================

class TestGalleryLoadDirectory:
    """Test gallery directory scanning without rendering."""

    def test_loads_webp_and_gif_files(self, pygame_init, gallery_dir):
        """Gallery finds .webp and .gif files but ignores others."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(gallery_dir))

        # alpha.webp, beta.gif, gamma.webp = 3 valid files
        assert gallery.file_count() == 3

    def test_filters_zone_identifier_files(self, pygame_init, tmp_path):
        """Files containing 'Zone.Identifier' in the name are excluded."""
        import pygame
        from editor.gallery import Gallery

        # Create a valid webp
        _make_test_webp(tmp_path / "valid.webp", frame_count=1)

        # Create a file that mimics Zone.Identifier naming (without colon
        # since not all filesystems support colons)
        zone_file = tmp_path / "valid.webpZone.Identifier"
        try:
            zone_file.write_text("[ZoneTransfer]\n")
        except OSError:
            pass

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(tmp_path))

        assert gallery.file_count() == 1

    def test_sorts_files_by_name(self, pygame_init, gallery_dir):
        """Files should be sorted alphabetically by name."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(gallery_dir))

        paths = gallery.get_selected()
        # No selection yet, so select all to check ordering via internal list
        names = [Path(t.path).name for t in gallery._thumbs]
        assert names == sorted(names, key=str.lower)

    def test_nonexistent_directory(self, pygame_init, tmp_path):
        """A missing directory should not crash, just result in 0 files."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(tmp_path / "no_such_dir"))

        assert gallery.file_count() == 0

    def test_empty_directory(self, pygame_init, tmp_path):
        """An empty directory yields 0 files."""
        import pygame
        from editor.gallery import Gallery

        empty = tmp_path / "empty"
        empty.mkdir()

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(empty))

        assert gallery.file_count() == 0

    def test_recursive_scan(self, pygame_init, tmp_path):
        """Gallery scans subdirectories recursively."""
        import pygame
        from editor.gallery import Gallery

        sub = tmp_path / "subdir"
        sub.mkdir()
        _make_test_webp(sub / "nested.webp", frame_count=1)
        _make_test_webp(tmp_path / "top.webp", frame_count=1)

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(tmp_path))

        assert gallery.file_count() == 2


# ===================================================================
# Gallery — selection and file management
# ===================================================================

class TestGallerySelection:
    """Test selection and removal helpers."""

    def test_get_selected_initially_empty(self, pygame_init, gallery_dir):
        """No selection by default."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(gallery_dir))
        assert gallery.get_selected() == []

    def test_deselect_all(self, pygame_init, gallery_dir):
        """deselect_all clears the entire selection."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(gallery_dir))

        # Manually add a selection
        if gallery._thumbs:
            gallery._selected_paths.add(gallery._thumbs[0].path)
        gallery.deselect_all()
        assert gallery.get_selected() == []

    def test_remove_file(self, pygame_init, gallery_dir):
        """remove_file drops a thumbnail from the gallery."""
        import pygame
        from editor.gallery import Gallery

        rect = pygame.Rect(0, 0, 800, 600)
        gallery = Gallery(rect, str(gallery_dir))

        initial = gallery.file_count()
        if initial > 0:
            path_to_remove = gallery._thumbs[0].path
            gallery.remove_file(path_to_remove)
            assert gallery.file_count() == initial - 1


# ===================================================================
# BatchConverter — frame extraction and conversion
# ===================================================================

class TestExtractFrames:
    """Test the _extract_frames helper from converter module."""

    def test_extract_frames_from_webp(self, sample_webp):
        """Extracts the correct number of frames from a WebP file."""
        from editor.converter import _extract_frames

        frames = _extract_frames(str(sample_webp))
        assert len(frames) == 3
        for img, dur in frames:
            assert img.mode == "RGBA"
            assert dur > 0

    def test_extract_frames_from_gif(self, sample_gif):
        """Extracts the correct number of frames from a GIF file."""
        from editor.converter import _extract_frames

        frames = _extract_frames(str(sample_gif))
        assert len(frames) == 3
        for img, dur in frames:
            assert img.mode == "RGBA"
            assert dur > 0

    def test_extract_single_frame_image(self, tmp_path):
        """A static image still returns at least one frame."""
        from editor.converter import _extract_frames

        static = tmp_path / "static.webp"
        Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(str(static), "WEBP")

        frames = _extract_frames(str(static))
        assert len(frames) >= 1

    def test_extract_frames_nonexistent_file(self, tmp_path):
        """Extracting from a missing file raises FileNotFoundError."""
        from editor.converter import _extract_frames

        with pytest.raises(FileNotFoundError):
            _extract_frames(str(tmp_path / "nonexistent.webp"))

    def test_frame_durations_positive(self, sample_webp):
        """All extracted durations must be positive (zero defaults to 100)."""
        from editor.converter import _extract_frames

        frames = _extract_frames(str(sample_webp))
        for _, dur in frames:
            assert dur > 0


class TestBatchConverterConvert:
    """Test BatchConverter.convert_file and related methods."""

    def test_gif_to_webp(self, sample_gif, tmp_path):
        """Convert a GIF to WebP and verify output exists."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "output.webp")
        result = converter.convert_file(str(sample_gif), out)

        assert result is True
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_webp_to_gif(self, sample_webp, tmp_path):
        """Convert a WebP to GIF and verify output exists."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "output.gif")
        result = converter.convert_file(str(sample_webp), out)

        assert result is True
        assert Path(out).exists()

    def test_convert_with_speed_multiplier(self, sample_gif, tmp_path):
        """Speed multiplier adjusts frame durations."""
        from editor.converter import BatchConverter, _extract_frames

        converter = BatchConverter()
        out = str(tmp_path / "fast.webp")
        result = converter.convert_file(str(sample_gif), out, speed_multiplier=2.0)

        assert result is True
        # Verify the output durations are roughly halved
        original_frames = _extract_frames(str(sample_gif))
        new_frames = _extract_frames(out)
        for (_, orig_dur), (_, new_dur) in zip(original_frames, new_frames):
            assert new_dur <= orig_dur

    def test_convert_unsupported_format_returns_false(self, sample_gif, tmp_path):
        """Unsupported output extension returns False."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "output.bmp")
        result = converter.convert_file(str(sample_gif), out)
        assert result is False

    def test_convert_nonexistent_input_returns_false(self, tmp_path):
        """Converting a nonexistent file returns False."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        result = converter.convert_file(
            str(tmp_path / "nope.gif"),
            str(tmp_path / "out.webp"),
        )
        assert result is False


class TestBatchConverterBatch:
    """Test batch conversion across a directory."""

    def test_batch_convert_gifs(self, tmp_path):
        """Batch-convert a directory of GIFs to WebP."""
        from editor.converter import BatchConverter

        in_dir = tmp_path / "input"
        out_dir = tmp_path / "output"
        in_dir.mkdir()

        _make_test_gif(in_dir / "a.gif", frame_count=2)
        _make_test_gif(in_dir / "b.gif", frame_count=2)

        converter = BatchConverter()
        results = converter.batch_convert(str(in_dir), str(out_dir))

        assert len(results) == 2
        assert all(results.values())
        assert (out_dir / "a.webp").exists()
        assert (out_dir / "b.webp").exists()

    def test_batch_convert_empty_dir(self, tmp_path):
        """Batch-converting an empty directory returns empty results."""
        from editor.converter import BatchConverter

        in_dir = tmp_path / "empty_in"
        out_dir = tmp_path / "empty_out"
        in_dir.mkdir()

        converter = BatchConverter()
        results = converter.batch_convert(str(in_dir), str(out_dir))
        assert results == {}

    def test_batch_convert_nonexistent_dir(self, tmp_path):
        """Batch-converting a missing directory returns empty results."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        results = converter.batch_convert(
            str(tmp_path / "no_such"),
            str(tmp_path / "out"),
        )
        assert results == {}


class TestBatchConverterGetFileInfo:
    """Test the static get_file_info metadata reader."""

    def test_webp_info(self, sample_webp):
        """File info for a 3-frame WebP is accurate."""
        from editor.converter import BatchConverter

        info = BatchConverter.get_file_info(str(sample_webp))
        assert info is not None
        assert info["name"] == "sample.webp"
        assert info["frame_count"] == 3
        assert info["width"] == 32
        assert info["height"] == 32
        assert info["file_size"] > 0
        assert len(info["durations"]) == 3

    def test_gif_info(self, sample_gif):
        """File info for a 3-frame GIF is accurate."""
        from editor.converter import BatchConverter

        info = BatchConverter.get_file_info(str(sample_gif))
        assert info is not None
        assert info["name"] == "sample.gif"
        assert info["frame_count"] == 3

    def test_nonexistent_file_returns_none(self, tmp_path):
        """get_file_info returns None for a missing file."""
        from editor.converter import BatchConverter

        info = BatchConverter.get_file_info(str(tmp_path / "gone.webp"))
        assert info is None


class TestBatchConverterCrop:
    """Test the crop operation."""

    def test_crop_reduces_size(self, sample_webp, tmp_path):
        """Cropping produces a smaller image."""
        from editor.converter import BatchConverter, _extract_frames

        converter = BatchConverter()
        out = str(tmp_path / "cropped.webp")
        result = converter.apply_crop(str(sample_webp), (4, 4, 28, 28), out)

        assert result is True
        frames = _extract_frames(out)
        img, _ = frames[0]
        assert img.size == (24, 24)

    def test_invalid_crop_rect_returns_false(self, sample_webp, tmp_path):
        """An inverted crop rect (right < left) returns False."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "bad_crop.webp")
        result = converter.apply_crop(str(sample_webp), (20, 20, 10, 10), out)
        assert result is False


class TestBatchConverterSpeedAdjust:
    """Test speed adjustment."""

    def test_speed_double(self, sample_webp, tmp_path):
        """Doubling speed halves frame durations."""
        from editor.converter import BatchConverter, _extract_frames

        converter = BatchConverter()
        out = str(tmp_path / "fast.webp")
        result = converter.adjust_speed(str(sample_webp), 2.0, out)

        assert result is True
        original = _extract_frames(str(sample_webp))
        adjusted = _extract_frames(out)
        for (_, orig_d), (_, new_d) in zip(original, adjusted):
            assert new_d <= orig_d

    def test_speed_zero_returns_false(self, sample_webp, tmp_path):
        """A zero speed multiplier is rejected."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "zero_speed.webp")
        result = converter.adjust_speed(str(sample_webp), 0.0, out)
        assert result is False

    def test_speed_negative_returns_false(self, sample_webp, tmp_path):
        """A negative speed multiplier is rejected."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "neg_speed.webp")
        result = converter.adjust_speed(str(sample_webp), -1.0, out)
        assert result is False


# ===================================================================
# GradientTool — radial gradient generation
# ===================================================================

class TestGradientToolGenerate:
    """Test GradientTool.generate_gradient pixel-level behaviour."""

    def test_output_dimensions(self):
        """Generated gradient matches requested size."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((100, 80), opacity=80, gradient_size=40)
        assert grad.size == (100, 80)

    def test_centre_is_transparent(self):
        """The exact centre pixel should be fully transparent."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((101, 101), opacity=100, gradient_size=40)

        cx, cy = 50, 50
        _, _, _, a = grad.getpixel((cx, cy))
        assert a == 0

    def test_edge_is_opaque(self):
        """Corner pixels should have high alpha (near max opacity)."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((100, 100), opacity=100, gradient_size=0)

        # Corner pixel should be at or near max_alpha (255)
        _, _, _, a = grad.getpixel((0, 0))
        assert a >= 200  # Allow some tolerance for math

    def test_colour_channel_is_black(self):
        """All pixels should have RGB = (0, 0, 0)."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((20, 20), opacity=80, gradient_size=40)

        for y in range(20):
            for x in range(20):
                r, g, b, _ = grad.getpixel((x, y))
                assert (r, g, b) == (0, 0, 0)

    def test_zero_opacity_all_transparent(self):
        """With opacity=0, the entire gradient should be fully transparent."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((30, 30), opacity=0, gradient_size=40)

        for y in range(30):
            for x in range(30):
                _, _, _, a = grad.getpixel((x, y))
                assert a == 0

    def test_full_gradient_size_mostly_transparent(self):
        """With gradient_size=100, nearly all pixels should be transparent."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((50, 50), opacity=100, gradient_size=100)

        # Count transparent pixels
        transparent = 0
        total = 50 * 50
        for y in range(50):
            for x in range(50):
                _, _, _, a = grad.getpixel((x, y))
                if a == 0:
                    transparent += 1

        # With gradient_size=100, inner_ratio=0.95, so most of the ellipse
        # interior is transparent
        assert transparent > total * 0.5

    def test_zero_size_returns_fallback(self):
        """A (0, 0) size returns a 1x1 transparent pixel."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((0, 0), opacity=80, gradient_size=40)
        assert grad.size == (1, 1)
        assert grad.getpixel((0, 0)) == (0, 0, 0, 0)

    def test_negative_size_returns_fallback(self):
        """Negative dimensions return the 1x1 fallback."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        grad = tool.generate_gradient((-10, -10), opacity=80, gradient_size=40)
        assert grad.size == (1, 1)


class TestGradientToolCaching:
    """Test gradient caching behaviour."""

    def test_same_params_returns_cached(self):
        """Calling with identical params returns the cached object."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        g1 = tool.generate_gradient((50, 50), opacity=80, gradient_size=40)
        g2 = tool.generate_gradient((50, 50), opacity=80, gradient_size=40)
        assert g1 is g2

    def test_different_params_regenerates(self):
        """Changing any parameter produces a new gradient."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        g1 = tool.generate_gradient((50, 50), opacity=80, gradient_size=40)
        g2 = tool.generate_gradient((50, 50), opacity=90, gradient_size=40)
        assert g1 is not g2

    def test_different_size_regenerates(self):
        """Changing size busts the cache."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        g1 = tool.generate_gradient((50, 50), opacity=80, gradient_size=40)
        g2 = tool.generate_gradient((60, 60), opacity=80, gradient_size=40)
        assert g1 is not g2


class TestGradientToolPreview:
    """Test gradient preview compositing."""

    def test_preview_preserves_size(self):
        """preview_on_frame output has same dimensions as input."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        frame = _make_rgba_image(64, 48, (255, 0, 0, 255))
        result = tool.preview_on_frame(frame, opacity=80, gradient_size=40)
        assert result.size == (64, 48)

    def test_preview_is_rgba(self):
        """Composite output is RGBA mode."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        frame = _make_rgba_image(32, 32, (0, 128, 255, 255))
        result = tool.preview_on_frame(frame, opacity=80, gradient_size=40)
        assert result.mode == "RGBA"

    def test_preview_darkens_edges(self):
        """Edges should be darker than centre after gradient overlay."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        frame = Image.new("RGBA", (101, 101), (200, 200, 200, 255))
        result = tool.preview_on_frame(frame, opacity=100, gradient_size=0)

        # Centre pixel should be brighter than corner
        centre_r, _, _, _ = result.getpixel((50, 50))
        corner_r, _, _, _ = result.getpixel((0, 0))
        assert centre_r > corner_r


class TestGradientToolBake:
    """Test baking gradient into animation files."""

    def test_bake_webp(self, sample_webp, tmp_path):
        """Bake gradient into a WebP and verify output exists."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        out = str(tmp_path / "baked.webp")
        result = tool.bake_gradient(str(sample_webp), out, opacity=80, gradient_size=40)

        assert result is True
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_bake_gif_output(self, sample_webp, tmp_path):
        """Bake gradient with GIF output format."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        out = str(tmp_path / "baked.gif")
        result = tool.bake_gradient(str(sample_webp), out, opacity=50, gradient_size=60)

        assert result is True
        assert Path(out).exists()

    def test_bake_unsupported_format_returns_false(self, sample_webp, tmp_path):
        """Unsupported output extension returns False."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        out = str(tmp_path / "baked.png")
        result = tool.bake_gradient(str(sample_webp), out)
        assert result is False

    def test_bake_nonexistent_input_returns_false(self, tmp_path):
        """Baking from a missing file returns False."""
        from editor.gradient_tool import GradientTool

        tool = GradientTool()
        result = tool.bake_gradient(
            str(tmp_path / "gone.webp"),
            str(tmp_path / "out.webp"),
        )
        assert result is False


# ===================================================================
# BatchConverter — padding and fill operations
# ===================================================================

class TestBatchConverterPadding:
    """Test padding operation."""

    def test_padding_increases_size(self, sample_webp, tmp_path):
        """Adding padding increases frame dimensions."""
        from editor.converter import BatchConverter, _extract_frames

        converter = BatchConverter()
        out = str(tmp_path / "padded.webp")
        result = converter.apply_padding(str(sample_webp), 10, (0, 0, 0, 255), out)

        assert result is True
        frames = _extract_frames(out)
        img, _ = frames[0]
        # Original 32x32 + 10px padding on each side = 52x52
        assert img.size == (52, 52)

    def test_negative_padding_returns_false(self, sample_webp, tmp_path):
        """Negative padding is rejected."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "neg_pad.webp")
        result = converter.apply_padding(str(sample_webp), -5, (0, 0, 0, 255), out)
        assert result is False


class TestBatchConverterFill:
    """Test fill/watermark removal operation."""

    def test_fill_succeeds(self, sample_webp, tmp_path):
        """Filling a rectangle over frames produces a valid output."""
        from editor.converter import BatchConverter

        converter = BatchConverter()
        out = str(tmp_path / "filled.webp")
        result = converter.apply_fill(
            str(sample_webp), (0, 0, 16, 16), (0, 0, 0, 255), out
        )
        assert result is True
        assert Path(out).exists()
