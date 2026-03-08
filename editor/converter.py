"""Batch GIF to WebP conversion and frame manipulation tools.

Provides all file-level operations for the animation editor: format conversion,
cropping, watermark fill, padding, and speed adjustment. Uses Pillow exclusively
-- no Pygame dependency so it can run headless or in background threads.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


def _extract_frames(path: str) -> list[tuple[Image.Image, int]]:
    """Extract all frames and their durations (ms) from an animated image.

    Args:
        path: Path to a GIF or animated WebP file.

    Returns:
        List of (RGBA PIL Image, duration_ms) tuples.  Duration defaults to
        100 ms when the source file omits it.

    Raises:
        FileNotFoundError: If *path* does not exist.
        PIL.UnidentifiedImageError: If the file is not a recognised image.
    """
    img = Image.open(path)
    frames: list[tuple[Image.Image, int]] = []

    try:
        while True:
            # Always convert to RGBA so compositing is consistent
            frame = img.convert("RGBA")
            duration = img.info.get("duration", 100)
            if duration <= 0:
                duration = 100
            frames.append((frame.copy(), int(duration)))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    if not frames:
        # Single-frame image -- still usable
        frames.append((img.convert("RGBA").copy(), 100))

    return frames


def _save_animated_webp(
    frames: list[tuple[Image.Image, int]],
    output_path: str,
    *,
    lossless: bool = False,
    quality: int = 90,
) -> None:
    """Save a list of (frame, duration_ms) pairs as an animated WebP.

    Args:
        frames: Non-empty list of (PIL RGBA Image, duration_ms).
        output_path: Destination file path.
        lossless: Use lossless compression (larger files).
        quality: Lossy quality 1-100 when *lossless* is ``False``.
    """
    if not frames:
        raise ValueError("Cannot save empty frame list")

    images = [f for f, _ in frames]
    durations = [d for _, d in frames]

    # Pillow animated WebP save: first frame as base, rest via append_images
    images[0].save(
        output_path,
        format="WEBP",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        lossless=lossless,
        quality=quality,
    )


def _save_animated_gif(
    frames: list[tuple[Image.Image, int]],
    output_path: str,
) -> None:
    """Save a list of (frame, duration_ms) pairs as an animated GIF.

    Converts RGBA frames to palette mode with transparency preserved.
    """
    if not frames:
        raise ValueError("Cannot save empty frame list")

    gif_frames: list[Image.Image] = []
    durations: list[int] = []

    for frame, dur in frames:
        # GIF needs palette mode -- convert via RGB, keeping alpha as transparency
        rgba = frame.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, (0, 0, 0))
        rgb.paste(rgba, mask=rgba.split()[3])
        quantised = rgb.quantize(colors=256)
        gif_frames.append(quantised)
        durations.append(dur)

    gif_frames[0].save(
        output_path,
        format="GIF",
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=0,
    )


class BatchConverter:
    """Batch GIF/WebP conversion and frame-level manipulation.

    All public methods are self-contained: they read an input file, process
    every frame, and write the result.  Each returns ``True`` on success and
    ``False`` on failure (logging the error).
    """

    # ------------------------------------------------------------------
    # Format conversion
    # ------------------------------------------------------------------

    def convert_file(
        self,
        input_path: str,
        output_path: str,
        speed_multiplier: float = 1.0,
    ) -> bool:
        """Convert a single GIF to animated WebP (or vice-versa).

        The output format is inferred from *output_path*'s extension.

        Args:
            input_path: Source animation file.
            output_path: Destination path (.webp or .gif).
            speed_multiplier: Multiply playback speed (2.0 = twice as fast).

        Returns:
            ``True`` if the conversion succeeded.
        """
        try:
            frames = _extract_frames(input_path)
            if speed_multiplier != 1.0 and speed_multiplier > 0:
                frames = [
                    (img, max(1, int(dur / speed_multiplier)))
                    for img, dur in frames
                ]

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(frames, output_path)
            elif ext == ".gif":
                _save_animated_gif(frames, output_path)
            else:
                logger.error("Unsupported output format: %s", ext)
                return False

            logger.info("Converted %s -> %s (%d frames)", input_path, output_path, len(frames))
            return True

        except Exception:
            logger.exception("Failed to convert %s", input_path)
            return False

    def batch_convert(
        self,
        input_dir: str,
        output_dir: str,
        speed_multiplier: float = 1.0,
    ) -> dict[str, bool]:
        """Convert every GIF in *input_dir* to animated WebP in *output_dir*.

        Args:
            input_dir: Folder containing source GIF files.
            output_dir: Destination folder (created if necessary).
            speed_multiplier: Playback speed factor applied to all files.

        Returns:
            Dict mapping each source filename to ``True``/``False``.
        """
        results: dict[str, bool] = {}
        input_path = Path(input_dir)

        if not input_path.is_dir():
            logger.error("Input directory does not exist: %s", input_dir)
            return results

        os.makedirs(output_dir, exist_ok=True)

        for gif_file in sorted(input_path.glob("*.gif")):
            out_name = gif_file.stem + ".webp"
            out_path = os.path.join(output_dir, out_name)
            results[gif_file.name] = self.convert_file(
                str(gif_file), out_path, speed_multiplier
            )

        logger.info(
            "Batch convert: %d/%d succeeded",
            sum(results.values()),
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Crop
    # ------------------------------------------------------------------

    def apply_crop(
        self,
        path: str,
        crop_rect: tuple[int, int, int, int],
        output_path: str,
    ) -> bool:
        """Crop all frames to *crop_rect* and save.

        Args:
            path: Source animation file.
            crop_rect: (left, top, right, bottom) in pixel coordinates.
            output_path: Destination file.

        Returns:
            ``True`` on success.
        """
        try:
            left, top, right, bottom = crop_rect
            if right <= left or bottom <= top:
                logger.error("Invalid crop rect: %s", crop_rect)
                return False

            frames = _extract_frames(path)
            cropped: list[tuple[Image.Image, int]] = []
            for img, dur in frames:
                cropped.append((img.crop((left, top, right, bottom)), dur))

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(cropped, output_path)
            else:
                _save_animated_gif(cropped, output_path)

            logger.info("Cropped %s -> %s", path, output_path)
            return True

        except Exception:
            logger.exception("Failed to crop %s", path)
            return False

    # ------------------------------------------------------------------
    # Black fill (watermark removal)
    # ------------------------------------------------------------------

    def apply_fill(
        self,
        path: str,
        fill_rect: tuple[int, int, int, int],
        fill_color: tuple[int, int, int, int],
        output_path: str,
    ) -> bool:
        """Paint a rectangle across every frame (e.g. to remove a watermark).

        Args:
            path: Source animation file.
            fill_rect: (left, top, right, bottom) region to fill.
            fill_color: RGBA colour tuple.
            output_path: Destination file.

        Returns:
            ``True`` on success.
        """
        try:
            left, top, right, bottom = fill_rect
            frames = _extract_frames(path)
            filled: list[tuple[Image.Image, int]] = []

            for img, dur in frames:
                working = img.copy()
                overlay = Image.new("RGBA", (right - left, bottom - top), fill_color)
                working.paste(overlay, (left, top))
                filled.append((working, dur))

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(filled, output_path)
            else:
                _save_animated_gif(filled, output_path)

            logger.info("Filled region %s on %s -> %s", fill_rect, path, output_path)
            return True

        except Exception:
            logger.exception("Failed to fill %s", path)
            return False

    # ------------------------------------------------------------------
    # Padding
    # ------------------------------------------------------------------

    def apply_padding(
        self,
        path: str,
        padding: int,
        pad_color: tuple[int, int, int, int],
        output_path: str,
    ) -> bool:
        """Add uniform padding around every frame.

        Args:
            path: Source animation file.
            padding: Number of pixels to add on each side.
            pad_color: RGBA fill colour for the padding area.
            output_path: Destination file.

        Returns:
            ``True`` on success.
        """
        try:
            if padding < 0:
                logger.error("Padding must be non-negative, got %d", padding)
                return False

            frames = _extract_frames(path)
            padded: list[tuple[Image.Image, int]] = []

            for img, dur in frames:
                new_w = img.width + padding * 2
                new_h = img.height + padding * 2
                canvas = Image.new("RGBA", (new_w, new_h), pad_color)
                canvas.paste(img, (padding, padding))
                padded.append((canvas, dur))

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(padded, output_path)
            else:
                _save_animated_gif(padded, output_path)

            logger.info("Padded %s (%dpx) -> %s", path, padding, output_path)
            return True

        except Exception:
            logger.exception("Failed to pad %s", path)
            return False

    # ------------------------------------------------------------------
    # Speed adjustment
    # ------------------------------------------------------------------

    def adjust_speed(
        self,
        path: str,
        multiplier: float,
        output_path: str,
    ) -> bool:
        """Change animation speed by adjusting frame durations.

        Args:
            path: Source animation file.
            multiplier: Speed factor (2.0 = twice as fast, 0.5 = half speed).
            output_path: Destination file.

        Returns:
            ``True`` on success.
        """
        try:
            if multiplier <= 0:
                logger.error("Speed multiplier must be positive, got %f", multiplier)
                return False

            frames = _extract_frames(path)
            adjusted: list[tuple[Image.Image, int]] = [
                (img, max(1, int(dur / multiplier)))
                for img, dur in frames
            ]

            ext = Path(output_path).suffix.lower()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            if ext == ".webp":
                _save_animated_webp(adjusted, output_path)
            else:
                _save_animated_gif(adjusted, output_path)

            logger.info("Speed %.2fx on %s -> %s", multiplier, path, output_path)
            return True

        except Exception:
            logger.exception("Failed to adjust speed for %s", path)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_file_info(path: str) -> Optional[dict]:
        """Return metadata about an animation file.

        Uses Pillow's ``n_frames`` attribute instead of seeking through every
        frame, which avoids a multi-second freeze on large animations.

        Returns:
            Dict with keys: name, width, height, frame_count, file_size,
            format, durations.  ``None`` if the file cannot be read.
        """
        try:
            p = Path(path)
            img = Image.open(path)

            # Fast frame count -- avoids iterating all frames
            frame_count = getattr(img, "n_frames", 1)
            first_dur = img.info.get("duration", 100) or 100

            return {
                "name": p.name,
                "width": img.width,
                "height": img.height,
                "frame_count": frame_count,
                "file_size": p.stat().st_size,
                "format": img.format or p.suffix.lstrip(".").upper(),
                "durations": [first_dur],
            }
        except Exception:
            logger.exception("Failed to read info for %s", path)
            return None
