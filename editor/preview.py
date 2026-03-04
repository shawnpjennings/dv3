"""Large animation preview panel with interactive tool overlays.

Displays the currently selected animation at full panel size with play/pause
control.  Supports interactive crop and fill rectangle drawing, and a live
gradient overlay preview using :class:`editor.gradient_tool.GradientTool`.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import pygame
from PIL import Image

from editor.gradient_tool import GradientTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme colours
# ---------------------------------------------------------------------------

COL_BG = (0x1E, 0x1E, 0x1E)
COL_TEXT = (0xE0, 0xE0, 0xE0)
COL_TEXT_DIM = (0x80, 0x80, 0x80)
COL_ACCENT = (0x4A, 0x9E, 0xFF)
COL_CROP_BORDER = (0xFF, 0xFF, 0xFF)
COL_FILL_BORDER = (0xFF, 0x44, 0x44)
COL_FILL_OVERLAY = (0x00, 0x00, 0x00, 0x60)
COL_PLAY_INDICATOR = (0x4A, 0x9E, 0xFF)
COL_PAUSE_INDICATOR = (0xFF, 0xAA, 0x33)


def _pil_to_surface(pil_image: Image.Image) -> pygame.Surface:
    """Convert a PIL RGBA image to a pygame Surface."""
    rgba = pil_image.convert("RGBA")
    data = rgba.tobytes()
    return pygame.image.fromstring(data, rgba.size, "RGBA").convert_alpha()


# ---------------------------------------------------------------------------
# PreviewPanel
# ---------------------------------------------------------------------------

class PreviewPanel:
    """Large animation preview with interactive tool overlays.

    Args:
        rect: Bounding rectangle on the parent surface.
    """

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect: pygame.Rect = rect

        # Animation data
        self._frames: list[pygame.Surface] = []
        self._durations: list[int] = []  # ms per frame
        self._current_frame: int = 0
        self._elapsed: float = 0.0  # accumulated ms
        self._playing: bool = True
        self._path: str = ""

        # Original animation dimensions (before scaling to preview)
        self._anim_width: int = 0
        self._anim_height: int = 0

        # Scaled display info -- where the animation sits inside the panel
        self._display_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._scale: float = 1.0

        # Tool modes
        self._crop_mode: bool = False
        self._fill_mode: bool = False

        # Crop rectangle (in screen coordinates during drag, converted on get)
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_end: Optional[tuple[int, int]] = None
        self._dragging: bool = False

        # Committed rectangles (in animation/source coordinates)
        self._crop_rect: Optional[tuple[int, int, int, int]] = None
        self._fill_rect: Optional[tuple[int, int, int, int]] = None

        # Gradient overlay
        self._gradient_enabled: bool = False
        self._gradient_opacity: int = 85
        self._gradient_size: int = 70
        self._gradient_tool: GradientTool = GradientTool()
        self._gradient_surface: Optional[pygame.Surface] = None
        self._gradient_cache_key: Optional[tuple] = None

        # Font (lazy init)
        self._font: Optional[pygame.font.Font] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_animation(self, path: str) -> None:
        """Load an animated file and prepare frames for display."""
        self._path = path
        self._frames.clear()
        self._durations.clear()
        self._current_frame = 0
        self._elapsed = 0.0
        self._crop_rect = None
        self._fill_rect = None
        self._drag_start = None
        self._drag_end = None
        self._dragging = False
        self._gradient_surface = None
        self._gradient_cache_key = None

        try:
            img = Image.open(path)
            self._anim_width = img.width
            self._anim_height = img.height

            try:
                while True:
                    frame = img.convert("RGBA")
                    dur = img.info.get("duration", 100)
                    if dur <= 0:
                        dur = 100
                    self._frames.append(_pil_to_surface(frame.copy()))
                    self._durations.append(int(dur))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass

            if not self._frames:
                self._frames.append(_pil_to_surface(img.convert("RGBA").copy()))
                self._durations.append(100)

            self._compute_display_rect()
            logger.info(
                "Preview loaded %s: %dx%d, %d frames",
                path, self._anim_width, self._anim_height, len(self._frames),
            )

        except Exception:
            logger.exception("Failed to load animation: %s", path)
            self._frames.clear()

    def update(self, dt: float) -> None:
        """Advance animation by *dt* seconds."""
        if not self._playing or len(self._frames) <= 1:
            return
        dt_ms = dt * 1000.0
        self._elapsed += dt_ms
        dur = self._durations[self._current_frame] if self._durations else 100
        if dur <= 0:
            dur = 100
        while self._elapsed >= dur:
            self._elapsed -= dur
            self._current_frame = (self._current_frame + 1) % len(self._frames)
            dur = self._durations[self._current_frame] if self._durations else 100
            if dur <= 0:
                dur = 100

    def render(self, surface: pygame.Surface) -> None:
        """Draw the current frame, overlays, and status indicators."""
        if self._font is None:
            pygame.font.init()
            self._font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 12)

        # Background
        pygame.draw.rect(surface, COL_BG, self.rect)

        if not self._frames:
            # Empty state
            msg = self._font.render("No animation loaded", True, COL_TEXT_DIM)
            mx = self.rect.x + (self.rect.width - msg.get_width()) // 2
            my = self.rect.y + (self.rect.height - msg.get_height()) // 2
            surface.blit(msg, (mx, my))
            return

        # Current frame, scaled to display rect
        frame = self._frames[self._current_frame % len(self._frames)]
        scaled = pygame.transform.smoothscale(
            frame, (self._display_rect.width, self._display_rect.height)
        )
        surface.blit(scaled, self._display_rect.topleft)

        # Gradient overlay
        if self._gradient_enabled:
            self._draw_gradient_overlay(surface)

        # Tool overlays
        if self._crop_mode and self._drag_start and self._drag_end:
            self._draw_dashed_rect(
                surface, self._drag_start, self._drag_end, COL_CROP_BORDER
            )
        elif self._crop_mode and self._crop_rect:
            s, e = self._anim_rect_to_screen(self._crop_rect)
            self._draw_dashed_rect(surface, s, e, COL_CROP_BORDER)

        if self._fill_mode and self._drag_start and self._drag_end:
            self._draw_fill_rect_overlay(surface, self._drag_start, self._drag_end)
        elif self._fill_mode and self._fill_rect:
            s, e = self._anim_rect_to_screen(self._fill_rect)
            self._draw_fill_rect_overlay(surface, s, e)

        # Frame counter
        fc = self._font.render(
            f"Frame {self._current_frame + 1}/{len(self._frames)}", True, COL_TEXT_DIM
        )
        surface.blit(fc, (self.rect.x + 8, self.rect.y + self.rect.height - 22))

        # Play/Pause indicator
        indicator_x = self.rect.x + self.rect.width - 60
        indicator_y = self.rect.y + self.rect.height - 22
        if self._playing:
            # Small triangle (play)
            pts = [
                (indicator_x, indicator_y),
                (indicator_x, indicator_y + 14),
                (indicator_x + 10, indicator_y + 7),
            ]
            pygame.draw.polygon(surface, COL_PLAY_INDICATOR, pts)
            lbl = self._font.render("Play", True, COL_PLAY_INDICATOR)
            surface.blit(lbl, (indicator_x + 14, indicator_y))
        else:
            # Two bars (pause)
            pygame.draw.rect(surface, COL_PAUSE_INDICATOR,
                             (indicator_x, indicator_y, 4, 14))
            pygame.draw.rect(surface, COL_PAUSE_INDICATOR,
                             (indicator_x + 7, indicator_y, 4, 14))
            lbl = self._font.render("Pause", True, COL_PAUSE_INDICATOR)
            surface.blit(lbl, (indicator_x + 14, indicator_y))

        # Mode label
        if self._crop_mode:
            mode_lbl = self._font.render("CROP MODE - drag to select", True, COL_CROP_BORDER)
            surface.blit(mode_lbl, (self.rect.x + 8, self.rect.y + 6))
        elif self._fill_mode:
            mode_lbl = self._font.render("FILL MODE - drag to select", True, COL_FILL_BORDER)
            surface.blit(mode_lbl, (self.rect.x + 8, self.rect.y + 6))

    def set_crop_mode(self, enabled: bool) -> None:
        """Enable or disable interactive crop rectangle drawing."""
        self._crop_mode = enabled
        if not enabled:
            self._dragging = False
            self._drag_start = None
            self._drag_end = None
        if enabled:
            self._fill_mode = False
            self._crop_rect = None

    def set_fill_mode(self, enabled: bool) -> None:
        """Enable or disable interactive fill rectangle drawing."""
        self._fill_mode = enabled
        if not enabled:
            self._dragging = False
            self._drag_start = None
            self._drag_end = None
        if enabled:
            self._crop_mode = False
            self._fill_rect = None

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle mouse events for crop/fill rectangle drawing."""
        if not (self._crop_mode or self._fill_mode):
            return
        if not self._frames:
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._display_rect.collidepoint(event.pos):
                self._dragging = True
                self._drag_start = event.pos
                self._drag_end = event.pos

        elif event.type == pygame.MOUSEMOTION and self._dragging:
            # Clamp to display rect
            ex = max(self._display_rect.x,
                     min(event.pos[0], self._display_rect.x + self._display_rect.width))
            ey = max(self._display_rect.y,
                     min(event.pos[1], self._display_rect.y + self._display_rect.height))
            self._drag_end = (ex, ey)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging and self._drag_start and self._drag_end:
                # Convert to animation coordinates and commit
                anim_rect = self._screen_rect_to_anim(self._drag_start, self._drag_end)
                if anim_rect is not None:
                    if self._crop_mode:
                        self._crop_rect = anim_rect
                    elif self._fill_mode:
                        self._fill_rect = anim_rect
            self._dragging = False

    def get_crop_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Return the drawn crop rectangle in animation coordinates (l, t, r, b)."""
        return self._crop_rect

    def get_fill_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Return the drawn fill rectangle in animation coordinates (l, t, r, b)."""
        return self._fill_rect

    def toggle_gradient(self, opacity: int, size: int) -> None:
        """Toggle the gradient overlay preview on/off."""
        self._gradient_enabled = not self._gradient_enabled
        self._gradient_opacity = opacity
        self._gradient_size = size
        self._gradient_surface = None
        self._gradient_cache_key = None

    def set_gradient_params(self, opacity: int, size: int) -> None:
        """Update gradient parameters without toggling."""
        if self._gradient_opacity != opacity or self._gradient_size != size:
            self._gradient_opacity = opacity
            self._gradient_size = size
            self._gradient_surface = None
            self._gradient_cache_key = None

    def set_playing(self, playing: bool) -> None:
        """Set play/pause state."""
        self._playing = playing

    @property
    def is_playing(self) -> bool:
        """Return whether the animation is currently playing."""
        return self._playing

    @property
    def has_animation(self) -> bool:
        """Return whether an animation is loaded."""
        return len(self._frames) > 0

    @property
    def gradient_enabled(self) -> bool:
        """Return whether the gradient overlay is active."""
        return self._gradient_enabled

    def set_rect(self, rect: pygame.Rect) -> None:
        """Update bounding rectangle on resize."""
        self.rect = rect
        if self._frames:
            self._compute_display_rect()
        self._gradient_surface = None
        self._gradient_cache_key = None

    def clear(self) -> None:
        """Clear the preview (no animation)."""
        self._frames.clear()
        self._durations.clear()
        self._path = ""
        self._crop_rect = None
        self._fill_rect = None
        self._gradient_enabled = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_display_rect(self) -> None:
        """Compute the scaled display rectangle, centred in the panel."""
        if self._anim_width == 0 or self._anim_height == 0:
            return

        # Available area (leave margin for status bar)
        avail_w = self.rect.width - 16
        avail_h = self.rect.height - 40  # reserve bottom for frame counter

        self._scale = min(avail_w / self._anim_width, avail_h / self._anim_height, 1.0)
        # Allow upscale for small animations but cap at 4x
        if self._scale < 1.0:
            pass  # already set
        else:
            self._scale = min(avail_w / self._anim_width, avail_h / self._anim_height)
            self._scale = min(self._scale, 4.0)

        dw = int(self._anim_width * self._scale)
        dh = int(self._anim_height * self._scale)

        dx = self.rect.x + (self.rect.width - dw) // 2
        dy = self.rect.y + (self.rect.height - 30 - dh) // 2  # offset for status bar
        self._display_rect = pygame.Rect(dx, dy, dw, dh)

    def _screen_rect_to_anim(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> Optional[tuple[int, int, int, int]]:
        """Convert screen-space drag coordinates to animation-space (l, t, r, b)."""
        if self._scale == 0 or self._display_rect.width == 0:
            return None

        # Normalise so left < right, top < bottom
        x1 = min(start[0], end[0])
        y1 = min(start[1], end[1])
        x2 = max(start[0], end[0])
        y2 = max(start[1], end[1])

        # Convert to animation coordinates
        inv = 1.0 / self._scale
        al = int((x1 - self._display_rect.x) * inv)
        at = int((y1 - self._display_rect.y) * inv)
        ar = int((x2 - self._display_rect.x) * inv)
        ab = int((y2 - self._display_rect.y) * inv)

        # Clamp to animation bounds
        al = max(0, min(al, self._anim_width))
        at = max(0, min(at, self._anim_height))
        ar = max(0, min(ar, self._anim_width))
        ab = max(0, min(ab, self._anim_height))

        if ar <= al or ab <= at:
            return None

        return (al, at, ar, ab)

    def _anim_rect_to_screen(
        self, anim_rect: tuple[int, int, int, int]
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        """Convert animation-space rectangle to screen-space start/end points."""
        al, at, ar, ab = anim_rect
        sx = self._display_rect.x + int(al * self._scale)
        sy = self._display_rect.y + int(at * self._scale)
        ex = self._display_rect.x + int(ar * self._scale)
        ey = self._display_rect.y + int(ab * self._scale)
        return (sx, sy), (ex, ey)

    def _draw_dashed_rect(
        self,
        surface: pygame.Surface,
        start: tuple[int, int],
        end: tuple[int, int],
        colour: tuple[int, int, int],
    ) -> None:
        """Draw a dashed rectangle between two points."""
        x1 = min(start[0], end[0])
        y1 = min(start[1], end[1])
        x2 = max(start[0], end[0])
        y2 = max(start[1], end[1])

        dash_len = 6
        gap_len = 4

        # Draw four sides with dashes
        for edge in [
            ((x1, y1), (x2, y1)),  # top
            ((x2, y1), (x2, y2)),  # right
            ((x2, y2), (x1, y2)),  # bottom
            ((x1, y2), (x1, y1)),  # left
        ]:
            self._draw_dashed_line(surface, colour, edge[0], edge[1], dash_len, gap_len)

    def _draw_dashed_line(
        self,
        surface: pygame.Surface,
        colour: tuple[int, int, int],
        start: tuple[int, int],
        end: tuple[int, int],
        dash: int,
        gap: int,
    ) -> None:
        """Draw a single dashed line."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1:
            return
        nx, ny = dx / length, dy / length
        pos = 0.0
        drawing = True
        while pos < length:
            seg = dash if drawing else gap
            seg = min(seg, length - pos)
            if drawing:
                sx = int(start[0] + nx * pos)
                sy = int(start[1] + ny * pos)
                ex = int(start[0] + nx * (pos + seg))
                ey = int(start[1] + ny * (pos + seg))
                pygame.draw.line(surface, colour, (sx, sy), (ex, ey), 1)
            pos += seg
            drawing = not drawing

    def _draw_fill_rect_overlay(
        self,
        surface: pygame.Surface,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        """Draw the fill rectangle with a semi-transparent black overlay and red border."""
        x1 = min(start[0], end[0])
        y1 = min(start[1], end[1])
        x2 = max(start[0], end[0])
        y2 = max(start[1], end[1])

        w = x2 - x1
        h = y2 - y1
        if w > 0 and h > 0:
            overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 100))
            surface.blit(overlay, (x1, y1))
            pygame.draw.rect(surface, COL_FILL_BORDER, (x1, y1, w, h), 2)

    def _draw_gradient_overlay(self, surface: pygame.Surface) -> None:
        """Render the gradient preview overlay on top of the animation."""
        if self._display_rect.width == 0 or self._display_rect.height == 0:
            return

        cache_key = (
            self._display_rect.width, self._display_rect.height,
            self._gradient_opacity, self._gradient_size,
        )
        if cache_key != self._gradient_cache_key or self._gradient_surface is None:
            # Generate via PIL then convert to pygame
            pil_grad = self._gradient_tool.generate_gradient(
                (self._display_rect.width, self._display_rect.height),
                opacity=self._gradient_opacity,
                gradient_size=self._gradient_size,
            )
            data = pil_grad.tobytes()
            self._gradient_surface = pygame.image.fromstring(
                data, pil_grad.size, "RGBA"
            ).convert_alpha()
            self._gradient_cache_key = cache_key

        surface.blit(self._gradient_surface, self._display_rect.topleft)
