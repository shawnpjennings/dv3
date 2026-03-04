"""Radial gradient generation, preview compositing, and bake-in tool.

Produces the same elliptical vignette used by the live visualizer but entirely
in PIL/Pillow so it works without a running Pygame display.  The gradient is
centre-transparent, edges-black -- designed to focus attention on the animation
centre and hide hard edges when displayed on a dark background.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


def _extract_frames(path: str) -> list[tuple[Image.Image, int]]:
    """Extract all frames from an animated image.

    Reuses the same logic as converter but kept local to avoid circular
    imports and keep gradient_tool self-contained.
    """
    img = Image.open(path)
    frames: list[tuple[Image.Image, int]] = []
    try:
        while True:
            frame = img.convert("RGBA")
            duration = img.info.get("duration", 100)
            if duration <= 0:
                duration = 100
            frames.append((frame.copy(), int(duration)))
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    if not frames:
        frames.append((img.convert("RGBA").copy(), 100))
    return frames


def _save_animated_webp(
    frames: list[tuple[Image.Image, int]],
    output_path: str,
    quality: int = 90,
) -> None:
    """Save frames as animated WebP."""
    images = [f for f, _ in frames]
    durations = [d for _, d in frames]
    images[0].save(
        output_path,
        format="WEBP",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        quality=quality,
    )


def _save_animated_gif(
    frames: list[tuple[Image.Image, int]],
    output_path: str,
) -> None:
    """Save frames as animated GIF."""
    gif_frames: list[Image.Image] = []
    durations: list[int] = []
    for frame, dur in frames:
        rgba = frame.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, (0, 0, 0))
        rgb.paste(rgba, mask=rgba.split()[3])
        gif_frames.append(rgb.quantize(colors=256))
        durations.append(dur)
    gif_frames[0].save(
        output_path,
        format="GIF",
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=0,
    )


class GradientTool:
    """Radial/elliptical gradient overlay for animation frames.

    The gradient is an RGBA image: fully transparent at the centre, fading to
    opaque black at the edges.  ``opacity`` controls the maximum alpha at the
    perimeter (0-100 mapped to 0-255).  ``gradient_size`` controls how far the
    transparent centre extends before the fade begins (0 = fade starts at
    centre, 100 = nearly no fade, all transparent).
    """

    # Cache the last generated gradient to avoid redundant computation when
    # only the frame changes but size/opacity/gradient_size stay the same.
    _cache_key: Optional[tuple] = None
    _cache_img: Optional[Image.Image] = None

    def generate_gradient(
        self,
        size: tuple[int, int],
        opacity: int = 80,
        gradient_size: int = 40,
    ) -> Image.Image:
        """Create a radial gradient as an RGBA PIL Image.

        Args:
            size: (width, height) in pixels.
            opacity: Maximum edge opacity 0-100 (mapped to 0-255 alpha).
            gradient_size: How much of the centre is kept transparent, 0-100.
                Higher values push the fade-out closer to the edge.

        Returns:
            PIL RGBA Image with black colour channel and computed alpha.
        """
        cache_key = (size, opacity, gradient_size)
        if cache_key == self._cache_key and self._cache_img is not None:
            return self._cache_img

        w, h = size
        if w <= 0 or h <= 0:
            # Return a 1x1 transparent pixel as a safe fallback
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

        max_alpha = int((opacity / 100.0) * 255)
        max_alpha = max(0, min(255, max_alpha))

        # gradient_size 0..100 -> inner_ratio 0.0..0.95
        # inner_ratio is the fraction of the half-axis that stays transparent
        inner_ratio = (gradient_size / 100.0) * 0.95

        cx, cy = w / 2.0, h / 2.0
        # Semi-axes for normalisation (elliptical)
        rx, ry = cx if cx > 0 else 1.0, cy if cy > 0 else 1.0

        gradient = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        # Build row by row for reasonable performance with pure Python.
        # For very large images this is the bottleneck; an optimised version
        # would use numpy, but Pillow-only is acceptable for editor use.
        pixels = gradient.load()

        for y in range(h):
            dy = (y - cy) / ry
            for x in range(w):
                dx = (x - cx) / rx
                dist = math.sqrt(dx * dx + dy * dy)  # 0 at centre, 1 at edge

                if dist <= inner_ratio:
                    alpha = 0
                elif dist >= 1.0:
                    alpha = max_alpha
                else:
                    # Smooth fade between inner_ratio and 1.0
                    t = (dist - inner_ratio) / (1.0 - inner_ratio)
                    # Ease-in curve for a natural vignette feel
                    t = t * t
                    alpha = int(t * max_alpha)

                pixels[x, y] = (0, 0, 0, alpha)

        self._cache_key = cache_key
        self._cache_img = gradient
        return gradient

    def preview_on_frame(
        self,
        frame: Image.Image,
        opacity: int = 80,
        gradient_size: int = 40,
    ) -> Image.Image:
        """Composite the gradient over a single frame for preview.

        Args:
            frame: Source RGBA frame.
            opacity: Gradient edge opacity 0-100.
            gradient_size: Transparent-centre extent 0-100.

        Returns:
            New RGBA image with gradient composited on top.
        """
        rgba = frame.convert("RGBA")
        gradient = self.generate_gradient(rgba.size, opacity, gradient_size)
        composite = Image.alpha_composite(rgba, gradient)
        return composite

    def bake_gradient(
        self,
        input_path: str,
        output_path: str,
        opacity: int = 80,
        gradient_size: int = 40,
    ) -> bool:
        """Apply gradient to every frame of an animation and save.

        Args:
            input_path: Source animated file.
            output_path: Destination file (.webp or .gif).
            opacity: Gradient edge opacity 0-100.
            gradient_size: Transparent-centre extent 0-100.

        Returns:
            ``True`` on success.
        """
        try:
            frames = _extract_frames(input_path)
            if not frames:
                logger.error("No frames extracted from %s", input_path)
                return False

            baked: list[tuple[Image.Image, int]] = []
            gradient: Optional[Image.Image] = None

            for img, dur in frames:
                rgba = img.convert("RGBA")
                # Generate gradient once (all frames same size) or per-frame
                if gradient is None or gradient.size != rgba.size:
                    gradient = self.generate_gradient(rgba.size, opacity, gradient_size)
                composite = Image.alpha_composite(rgba, gradient)
                baked.append((composite, dur))

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(baked, output_path)
            elif ext == ".gif":
                _save_animated_gif(baked, output_path)
            else:
                logger.error("Unsupported output format: %s", ext)
                return False

            logger.info(
                "Baked gradient (opacity=%d, size=%d) on %s -> %s",
                opacity,
                gradient_size,
                input_path,
                output_path,
            )
            return True

        except Exception:
            logger.exception("Failed to bake gradient on %s", input_path)
            return False
