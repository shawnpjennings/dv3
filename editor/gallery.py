"""Animated thumbnail gallery grid for the DV3 animation editor.

Displays all .webp and .gif files in a directory as a scrollable grid of
animated thumbnails.  Every thumbnail animates simultaneously -- this is a key
UX requirement so the user can see motion at a glance.

Thumbnails are loaded lazily: the first frame is decoded immediately for fast
display, and the remaining frames are decoded in a background thread so the UI
never blocks during directory scans.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import pygame
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THUMB_SIZE: int = 120
THUMB_PAD: int = 8
FONT_HEIGHT: int = 14
CELL_HEIGHT: int = THUMB_SIZE + FONT_HEIGHT + 4  # thumb + label + gap
CELL_WIDTH: int = THUMB_SIZE + THUMB_PAD

# Colours (dark theme)
COL_BG = (0x25, 0x25, 0x25)
COL_SELECTED = (0x4A, 0x9E, 0xFF)
COL_HOVER = (0x3A, 0x3A, 0x3A)
COL_TEXT = (0xE0, 0xE0, 0xE0)
COL_TEXT_DIM = (0x80, 0x80, 0x80)


def _pil_to_surface(pil_image: Image.Image) -> pygame.Surface:
    """Convert a PIL RGBA image to a pygame Surface."""
    rgba = pil_image.convert("RGBA")
    data = rgba.tobytes()
    return pygame.image.fromstring(data, rgba.size, "RGBA").convert_alpha()


def _fit_surface(surface: pygame.Surface, max_w: int, max_h: int) -> pygame.Surface:
    """Scale *surface* to fit within max_w x max_h, preserving aspect ratio."""
    sw, sh = surface.get_size()
    if sw == 0 or sh == 0:
        return surface
    scale = min(max_w / sw, max_h / sh, 1.0)
    new_w = max(1, int(sw * scale))
    new_h = max(1, int(sh * scale))
    return pygame.transform.smoothscale(surface, (new_w, new_h))


# ---------------------------------------------------------------------------
# Thumbnail container
# ---------------------------------------------------------------------------

class _Thumbnail:
    """Holds the decoded frames and playback state for a single file."""

    __slots__ = (
        "path", "frames", "durations", "current_frame", "elapsed",
        "surface_cache", "loaded", "loading",
    )

    def __init__(self, path: str) -> None:
        self.path: str = path
        self.frames: list[pygame.Surface] = []
        self.durations: list[int] = []  # milliseconds per frame
        self.current_frame: int = 0
        self.elapsed: float = 0.0  # ms accumulated
        self.surface_cache: Optional[pygame.Surface] = None  # scaled thumbnail
        self.loaded: bool = False
        self.loading: bool = False

    # --- animation tick ---------------------------------------------------

    def advance(self, dt_ms: float) -> None:
        """Advance the animation by *dt_ms* milliseconds."""
        if not self.frames or len(self.frames) == 1:
            return
        self.elapsed += dt_ms
        dur = self.durations[self.current_frame] if self.durations else 100
        if dur <= 0:
            dur = 100
        while self.elapsed >= dur:
            self.elapsed -= dur
            self.current_frame = (self.current_frame + 1) % len(self.frames)
            dur = self.durations[self.current_frame] if self.durations else 100
            if dur <= 0:
                dur = 100
        # Invalidate the cache so the gallery re-scales the current frame
        self.surface_cache = None

    def get_thumb(self) -> Optional[pygame.Surface]:
        """Return the current frame scaled to THUMB_SIZE, or None."""
        if not self.frames:
            return None
        if self.surface_cache is not None:
            return self.surface_cache
        raw = self.frames[self.current_frame % len(self.frames)]
        self.surface_cache = _fit_surface(raw, THUMB_SIZE, THUMB_SIZE)
        return self.surface_cache


# ---------------------------------------------------------------------------
# Background loader
# ---------------------------------------------------------------------------

def _load_all_frames(thumb: _Thumbnail) -> None:
    """Decode every frame of *thumb.path* in a background thread.

    The first frame is already loaded by the caller on the main thread.
    This function replaces the frame list atomically once all frames are
    ready so the main thread never sees a partially-loaded list.
    """
    try:
        img = Image.open(thumb.path)
        frames: list[Image.Image] = []
        durations: list[int] = []

        try:
            while True:
                frame = img.convert("RGBA")
                frames.append(frame.copy())
                dur = img.info.get("duration", 100)
                if dur <= 0:
                    dur = 100
                durations.append(int(dur))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        if not frames:
            frames.append(img.convert("RGBA").copy())
            durations.append(100)

        # Convert to pygame surfaces (pygame.image.fromstring is thread-safe
        # for surface creation as long as we do not blit from the thread).
        surfaces = [_pil_to_surface(f) for f in frames]

        # Atomic replacement
        thumb.frames = surfaces
        thumb.durations = durations
        thumb.current_frame = 0
        thumb.elapsed = 0.0
        thumb.surface_cache = None
        thumb.loaded = True

    except Exception:
        logger.exception("Background load failed for %s", thumb.path)
        thumb.loaded = True  # Mark done so we stop retrying

    thumb.loading = False


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------

class Gallery:
    """Scrollable grid of animated thumbnails.

    Args:
        rect: The bounding rectangle on the parent surface.
        directory: Root directory to scan for animations.
    """

    def __init__(self, rect: pygame.Rect, directory: str) -> None:
        self.rect: pygame.Rect = rect
        self.directory: str = directory

        self._thumbs: list[_Thumbnail] = []
        self._selected_paths: set[str] = set()
        self._hover_index: int = -1
        self._scroll_offset: int = 0  # pixels scrolled down

        self._font: Optional[pygame.font.Font] = None
        self._cols: int = 1

        self.load_directory(directory)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_directory(self, path: str) -> None:
        """Scan *path* recursively for .webp and .gif files and create thumbnails."""
        self.directory = path
        self._thumbs.clear()
        self._selected_paths.clear()
        self._scroll_offset = 0

        root = Path(path)
        if not root.is_dir():
            logger.warning("Gallery directory does not exist: %s", path)
            return

        extensions = {".webp", ".gif"}
        files: list[Path] = []
        for ext in extensions:
            files.extend(root.rglob(f"*{ext}"))

        # Filter out Zone.Identifier and other junk files
        files = [
            f for f in files
            if f.suffix.lower() in extensions
            and "Zone.Identifier" not in f.name
            and f.is_file()
        ]
        files.sort(key=lambda p: p.name.lower())

        for fp in files:
            thumb = _Thumbnail(str(fp))
            # Decode first frame immediately for instant display
            try:
                img = Image.open(str(fp))
                first = img.convert("RGBA").copy()
                thumb.frames = [_pil_to_surface(first)]
                thumb.durations = [img.info.get("duration", 100) or 100]
            except Exception:
                logger.warning("Could not decode first frame of %s", fp)
                continue

            self._thumbs.append(thumb)

            # Kick off background decode for the remaining frames
            thumb.loading = True
            t = threading.Thread(
                target=_load_all_frames, args=(thumb,), daemon=True
            )
            t.start()

        logger.info("Gallery loaded %d files from %s", len(self._thumbs), path)

    def update(self, dt: float) -> None:
        """Advance ALL thumbnail animations simultaneously.

        Args:
            dt: Delta time in seconds since last call.
        """
        dt_ms = dt * 1000.0
        for thumb in self._thumbs:
            thumb.advance(dt_ms)

    def render(self, surface: pygame.Surface) -> None:
        """Draw the thumbnail grid onto *surface*."""
        if self._font is None:
            pygame.font.init()
            self._font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 11)

        # Background
        pygame.draw.rect(surface, COL_BG, self.rect)

        # Compute grid layout
        inner_w = self.rect.width - THUMB_PAD * 2
        self._cols = max(1, inner_w // CELL_WIDTH)

        clip = surface.subsurface(self.rect).get_clip()
        surface.set_clip(self.rect)

        visible_top = self._scroll_offset
        visible_bottom = self._scroll_offset + self.rect.height

        for idx, thumb in enumerate(self._thumbs):
            col = idx % self._cols
            row = idx // self._cols
            cell_x = self.rect.x + THUMB_PAD + col * CELL_WIDTH
            cell_y = self.rect.y + THUMB_PAD + row * CELL_HEIGHT - self._scroll_offset

            # Skip off-screen
            if cell_y + CELL_HEIGHT < self.rect.y or cell_y > self.rect.y + self.rect.height:
                continue

            # Selection highlight
            is_selected = thumb.path in self._selected_paths
            is_hover = idx == self._hover_index

            if is_selected:
                border_rect = pygame.Rect(
                    cell_x - 2, cell_y - 2, THUMB_SIZE + 4, THUMB_SIZE + 4
                )
                pygame.draw.rect(surface, COL_SELECTED, border_rect, 2, border_radius=3)
            elif is_hover:
                bg_rect = pygame.Rect(cell_x - 2, cell_y - 2, THUMB_SIZE + 4, THUMB_SIZE + 4)
                pygame.draw.rect(surface, COL_HOVER, bg_rect, 0, border_radius=3)

            # Thumbnail image
            ts = thumb.get_thumb()
            if ts is not None:
                tw, th = ts.get_size()
                # Centre within the cell
                ox = cell_x + (THUMB_SIZE - tw) // 2
                oy = cell_y + (THUMB_SIZE - th) // 2
                surface.blit(ts, (ox, oy))

            # Filename label
            name = Path(thumb.path).stem
            if len(name) > 14:
                name = name[:12] + ".."
            label = self._font.render(name, True, COL_TEXT if is_selected else COL_TEXT_DIM)
            lx = cell_x + (THUMB_SIZE - label.get_width()) // 2
            ly = cell_y + THUMB_SIZE + 2
            surface.blit(label, (lx, ly))

        surface.set_clip(clip)

    def handle_click(self, pos: tuple[int, int]) -> Optional[str]:
        """Handle a mouse click at *pos* (screen coordinates).

        Returns the file path of the clicked thumbnail, or None.
        Multi-select: Ctrl-click toggles; plain click replaces selection.
        """
        if not self.rect.collidepoint(pos):
            return None

        idx = self._pos_to_index(pos)
        if idx is None or idx >= len(self._thumbs):
            # Click on empty space -- deselect all
            self._selected_paths.clear()
            return None

        thumb = self._thumbs[idx]
        keys = pygame.key.get_mods()
        if keys & pygame.KMOD_CTRL:
            # Toggle
            if thumb.path in self._selected_paths:
                self._selected_paths.discard(thumb.path)
            else:
                self._selected_paths.add(thumb.path)
        else:
            self._selected_paths = {thumb.path}

        return thumb.path

    def handle_scroll(self, direction: int) -> None:
        """Scroll the grid. *direction*: negative = up, positive = down."""
        scroll_step = CELL_HEIGHT // 2
        self._scroll_offset += direction * scroll_step
        self._scroll_offset = max(0, self._scroll_offset)

        # Clamp to maximum scroll
        total_rows = (len(self._thumbs) + max(1, self._cols) - 1) // max(1, self._cols)
        max_scroll = max(0, total_rows * CELL_HEIGHT + THUMB_PAD * 2 - self.rect.height)
        self._scroll_offset = min(self._scroll_offset, max_scroll)

    def handle_motion(self, pos: tuple[int, int]) -> None:
        """Track mouse hover for highlight effect."""
        if not self.rect.collidepoint(pos):
            self._hover_index = -1
            return
        idx = self._pos_to_index(pos)
        self._hover_index = idx if idx is not None and idx < len(self._thumbs) else -1

    def get_selected(self) -> list[str]:
        """Return all currently selected file paths."""
        return [t.path for t in self._thumbs if t.path in self._selected_paths]

    def deselect_all(self) -> None:
        """Clear the selection."""
        self._selected_paths.clear()

    def remove_file(self, path: str) -> None:
        """Remove a thumbnail from the gallery (does not delete the file)."""
        self._thumbs = [t for t in self._thumbs if t.path != path]
        self._selected_paths.discard(path)

    def file_count(self) -> int:
        """Return number of files currently in the gallery."""
        return len(self._thumbs)

    # ------------------------------------------------------------------
    # Layout recalculation
    # ------------------------------------------------------------------

    def set_rect(self, rect: pygame.Rect) -> None:
        """Update the bounding rectangle (e.g. on window resize)."""
        self.rect = rect

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pos_to_index(self, pos: tuple[int, int]) -> Optional[int]:
        """Convert a screen position to a thumbnail index."""
        rx = pos[0] - self.rect.x - THUMB_PAD
        ry = pos[1] - self.rect.y - THUMB_PAD + self._scroll_offset
        if rx < 0 or ry < 0:
            return None
        col = rx // CELL_WIDTH
        row = ry // CELL_HEIGHT
        if col >= self._cols:
            return None
        idx = row * self._cols + col
        return idx if 0 <= idx < len(self._thumbs) else None
