"""Radial gradient overlay that makes animations float on a black background.

Generates a single pre-rendered RGBA surface with a radial (elliptical)
gradient.  The center is fully transparent so the animation shows through;
the edges fade to opaque black so the rectangular frame boundary disappears
and the content appears to hover in space.

The overlay is cached and only regenerated when opacity or gradient-size
parameters change.  At runtime it is blitted on top of the animation frame
once per display loop -- no per-pixel work on the hot path.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import pygame

logger = logging.getLogger(__name__)


class GradientOverlay:
    """Pre-rendered elliptical radial gradient mask.

    The gradient runs from fully transparent at the center to opaque
    black at the edges.  Two knobs control the look:

    *   **opacity** (0-100): peak alpha at the outermost edge.  At 100
        the border is solid black; at 0 the overlay does nothing.
    *   **gradient_size** (0-100): how far inward the gradient extends,
        as a percentage of the animation area.  At 100 the fade covers
        the entire surface; at 0 only the very edge is darkened.

    The gradient is elliptical, matching the aspect ratio of the
    animation rect so the visible "hole" is proportional in both axes.

    Usage::

        overlay = GradientOverlay(size=(800, 600), opacity=85, size=70)
        gradient_surface = overlay.get_surface()
        screen.blit(gradient_surface, anim_rect)
    """

    def __init__(
        self,
        size: tuple[int, int],
        opacity: int = 85,
        gradient_size: int = 70,
    ) -> None:
        """Create the overlay for a given animation area.

        Args:
            size: ``(width, height)`` of the animation blit area.
            opacity: Edge opacity percentage (0 = invisible, 100 = solid
                black border).
            gradient_size: How far into the center the gradient reaches,
                as a percentage of the surface dimensions.
        """
        self._size: tuple[int, int] = size
        self._opacity: int = self._clamp(opacity, 0, 100)
        self._gradient_size: int = self._clamp(gradient_size, 0, 100)

        self._surface: Optional[pygame.Surface] = None
        self._dirty: bool = True  # needs (re)generation

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> pygame.Surface:
        """Render the gradient and return the RGBA surface.

        This is moderately expensive (pixel-level iteration via
        ``PixelArray`` / ``surfarray``), but only called once per param
        change -- never per frame.

        Returns:
            A ``pygame.Surface`` with ``SRCALPHA``.
        """
        width, height = self._size
        if width <= 0 or height <= 0:
            # Degenerate -- return a 1x1 transparent surface.
            self._surface = pygame.Surface((1, 1), pygame.SRCALPHA)
            self._dirty = False
            return self._surface

        surface = pygame.Surface((width, height), pygame.SRCALPHA)

        max_alpha = int(255 * self._opacity / 100)

        # The gradient_size parameter defines how far *into* the surface
        # the fade extends.  At gradient_size=100 the transparent center
        # is a single pixel; at gradient_size=0 only the outermost pixel
        # row is black and everything else is transparent.
        #
        # We model this as an ellipse centered on the surface.  Points
        # inside the ellipse are transparent; outside the ellipse the
        # alpha ramps linearly to max_alpha.
        #
        # inner_rx / inner_ry define the semi-axes of the "fully clear"
        # ellipse.  They shrink as gradient_size increases.
        gradient_fraction = self._gradient_size / 100.0
        inner_rx = (width / 2.0) * (1.0 - gradient_fraction)
        inner_ry = (height / 2.0) * (1.0 - gradient_fraction)

        cx = width / 2.0
        cy = height / 2.0

        # Outer radii are always the surface half-dimensions.
        outer_rx = width / 2.0
        outer_ry = height / 2.0

        # Guard: if inner == outer no gradient range exists.
        range_rx = outer_rx - inner_rx if outer_rx > inner_rx else 1.0
        range_ry = outer_ry - inner_ry if outer_ry > inner_ry else 1.0

        # Use pygame.surfarray for fast bulk pixel writes.  We build a
        # 2-D numpy alpha channel and assign it directly.
        try:
            import numpy as np

            # Build coordinate grids.
            xs = np.arange(width, dtype=np.float64)
            ys = np.arange(height, dtype=np.float64)
            gx, gy = np.meshgrid(xs, ys)  # shape (H, W)

            # Normalised elliptical distance from center.
            dx = np.abs(gx - cx)
            dy = np.abs(gy - cy)

            # How far past the inner ellipse boundary this pixel is,
            # normalised so 0 = on the inner boundary, 1 = on the outer
            # edge.  We take the *maximum* of the two axis-normalised
            # distances so the shape is always a proper ellipse.
            ex = (dx - inner_rx) / range_rx
            ey = (dy - inner_ry) / range_ry
            # Pixels inside the inner ellipse get a negative value;
            # clip to 0 so they stay transparent.
            t = np.clip(np.maximum(ex, ey), 0.0, 1.0)

            alpha = (t * max_alpha).astype(np.uint8)  # (H, W)

            # surfarray pixel layout is (W, H, channels).
            arr = pygame.surfarray.pixels3d(surface)
            arr[:, :, :] = 0  # RGB = black

            alpha_arr = pygame.surfarray.pixels_alpha(surface)
            alpha_arr[:, :] = alpha.T  # transpose H,W -> W,H

            del arr, alpha_arr  # release the pixel locks

        except ImportError:
            # numpy not available -- fall back to a pure-Python scanline
            # approach.  Slower, but only called once per param change.
            logger.warning(
                "numpy unavailable; falling back to pure-Python gradient "
                "generation (this may take a moment)"
            )
            self._generate_pure_python(
                surface, width, height, cx, cy,
                inner_rx, inner_ry, range_rx, range_ry, max_alpha,
            )

        self._surface = surface
        self._dirty = False

        logger.debug(
            "Gradient generated: %dx%d  opacity=%d%%  size=%d%%",
            width, height, self._opacity, self._gradient_size,
        )
        return surface

    def get_surface(self) -> pygame.Surface:
        """Return the cached gradient surface, regenerating if needed.

        Returns:
            The gradient ``pygame.Surface``.
        """
        if self._dirty or self._surface is None:
            self.generate()
        assert self._surface is not None
        return self._surface

    def update_params(
        self,
        opacity: Optional[int] = None,
        gradient_size: Optional[int] = None,
    ) -> None:
        """Change gradient parameters and mark the cache dirty.

        Only the supplied parameters are updated; the others retain
        their current values.  The surface will be regenerated lazily on
        the next ``get_surface`` call.

        Args:
            opacity: New edge opacity (0-100), or *None* to keep current.
            gradient_size: New gradient extent (0-100), or *None* to keep.
        """
        changed = False
        if opacity is not None:
            clamped = self._clamp(opacity, 0, 100)
            if clamped != self._opacity:
                self._opacity = clamped
                changed = True
        if gradient_size is not None:
            clamped = self._clamp(gradient_size, 0, 100)
            if clamped != self._gradient_size:
                self._gradient_size = clamped
                changed = True

        if changed:
            self._dirty = True
            logger.debug(
                "Gradient params updated: opacity=%d  size=%d",
                self._opacity, self._gradient_size,
            )

    def update_size(self, size: tuple[int, int]) -> None:
        """Change the overlay dimensions and mark the cache dirty.

        Args:
            size: New ``(width, height)`` in pixels.
        """
        if size != self._size:
            self._size = size
            self._dirty = True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def opacity(self) -> int:
        """Current edge opacity (0-100)."""
        return self._opacity

    @property
    def gradient_size(self) -> int:
        """Current gradient extent (0-100)."""
        return self._gradient_size

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))

    @staticmethod
    def _generate_pure_python(
        surface: pygame.Surface,
        width: int,
        height: int,
        cx: float,
        cy: float,
        inner_rx: float,
        inner_ry: float,
        range_rx: float,
        range_ry: float,
        max_alpha: int,
    ) -> None:
        """Pixel-by-pixel fallback when numpy is not available."""
        for y in range(height):
            dy = abs(y - cy)
            ey = (dy - inner_ry) / range_ry if range_ry > 0 else 0.0
            for x in range(width):
                dx = abs(x - cx)
                ex = (dx - inner_rx) / range_rx if range_rx > 0 else 0.0
                t = max(ex, ey)
                t = max(0.0, min(1.0, t))
                alpha = int(t * max_alpha)
                surface.set_at((x, y), (0, 0, 0, alpha))
