"""WebP/GIF animation playback engine for the DV3 visualizer.

Loads animated WebP and GIF files via Pillow, extracts every frame and
its duration, converts them to Pygame surfaces on demand, and advances
playback based on real elapsed time.  A look-ahead cache converts the
next N frames to Pygame surfaces in advance so the per-frame render path
is a single dict lookup -- no PIL conversion on the hot path.

Crossfade transitions blend the outgoing animation into the incoming one
over a configurable duration, producing a smooth emotion-change effect.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import pygame
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Animation:
    """A fully-loaded animation ready for playback.

    Attributes:
        frames: Raw PIL Image objects for every frame (RGBA).
        durations: Per-frame display duration in milliseconds.
        frame_count: Total number of frames (cached for speed).
        path: Filesystem path the animation was loaded from.
    """

    frames: list[Image.Image]
    durations: list[int]
    frame_count: int = field(init=False)
    path: str = ""

    def __post_init__(self) -> None:
        self.frame_count = len(self.frames)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class AnimationEngine:
    """Drives animation playback, frame caching, and crossfade transitions.

    Usage::

        engine = AnimationEngine(config)
        anim = engine.load_animation("data/animations/emotions/happy/b1.webp")
        engine.set_animation(anim)

        # Each frame of the main loop:
        engine.update(dt)
        frame = engine.get_current_frame()

        # On emotion change:
        new_anim = engine.load_animation(new_path)
        engine.crossfade_to(new_anim, duration_ms=300)

    All Pygame surfaces returned by ``get_current_frame`` use ``SRCALPHA``
    so they can be composited with the gradient overlay via alpha blending.
    """

    # Fallback duration when a frame reports 0 ms (common in some GIFs).
    _DEFAULT_FRAME_MS: int = 100

    def __init__(self, config: dict) -> None:
        """Configure the engine from the ``visualizer`` section of settings.

        Args:
            config: Expects ``crossfade_ms`` and ``frame_cache_ahead``.
        """
        self._crossfade_default_ms: int = config.get("crossfade_ms", 300)
        self._cache_ahead: int = config.get("frame_cache_ahead", 30)

        # Current playback state
        self._animation: Optional[Animation] = None
        self._frame_idx: int = 0
        self._frame_elapsed_ms: float = 0.0

        # Pygame surface cache: frame index -> surface
        self._surface_cache: dict[int, pygame.Surface] = {}

        # Crossfade state
        self._crossfade_active: bool = False
        self._crossfade_elapsed_ms: float = 0.0
        self._crossfade_duration_ms: int = 0
        self._old_animation: Optional[Animation] = None
        self._old_frame_idx: int = 0
        self._old_frame_elapsed_ms: float = 0.0
        self._old_surface_cache: dict[int, pygame.Surface] = {}

        # Target size for surface output (set by caller via set_target_size)
        self._target_size: Optional[tuple[int, int]] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_animation(self, path: str) -> Animation:
        """Load an animated WebP or GIF from disk.

        Extracts every frame as an RGBA PIL Image and its display
        duration.  Frames with a reported duration of 0 ms get the
        engine default (100 ms).

        Args:
            path: Filesystem path to a ``.webp`` or ``.gif`` file.

        Returns:
            A populated :class:`Animation` instance.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If the file contains zero extractable frames.
        """
        t0 = time.monotonic()
        img = Image.open(path)

        frames: list[Image.Image] = []
        durations: list[int] = []

        try:
            while True:
                # Convert to RGBA immediately so every frame is
                # consistent regardless of source palette/mode.
                frame = img.convert("RGBA")
                frames.append(frame)

                dur = img.info.get("duration", self._DEFAULT_FRAME_MS)
                if dur <= 0:
                    dur = self._DEFAULT_FRAME_MS
                durations.append(int(dur))

                img.seek(img.tell() + 1)
        except EOFError:
            pass  # End of frames -- expected.

        if not frames:
            raise ValueError(f"No frames extracted from {path}")

        elapsed = (time.monotonic() - t0) * 1000
        logger.debug(
            "Loaded %d frames from %s in %.1f ms", len(frames), path, elapsed
        )
        return Animation(frames=frames, durations=durations, path=path)

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def set_animation(self, animation: Animation) -> None:
        """Immediately switch to *animation* (no crossfade).

        Resets frame index, clears caches, and pre-warms the look-ahead
        cache.

        Args:
            animation: The animation to play.
        """
        self._animation = animation
        self._frame_idx = 0
        self._frame_elapsed_ms = 0.0
        self._surface_cache.clear()
        self._cancel_crossfade()
        self._precache_surfaces(
            animation, 0, self._surface_cache
        )
        logger.debug("Set animation: %s (%d frames)", animation.path, animation.frame_count)

    def set_target_size(self, size: tuple[int, int]) -> None:
        """Set the output size for Pygame surfaces.

        Surfaces returned by ``get_current_frame`` will be scaled to
        this size.  Changing the target size flushes the surface cache.

        Args:
            size: ``(width, height)`` in pixels.
        """
        if size != self._target_size:
            self._target_size = size
            self._surface_cache.clear()
            self._old_surface_cache.clear()

    def crossfade_to(
        self, new_animation: Animation, duration_ms: Optional[int] = None
    ) -> None:
        """Begin a crossfade transition from the current animation.

        The old animation continues playing (and fading out) while the
        new one fades in.  If a crossfade is already in progress it is
        replaced -- the current blended state becomes the new "old" side.

        Args:
            new_animation: The animation to transition to.
            duration_ms: Crossfade length in milliseconds.  If *None*,
                uses the default from settings.
        """
        if self._animation is None:
            # Nothing playing yet -- just set directly.
            self.set_animation(new_animation)
            return

        if duration_ms is None:
            duration_ms = self._crossfade_default_ms

        # Preserve current playback as the "old" side.
        self._old_animation = self._animation
        self._old_frame_idx = self._frame_idx
        self._old_frame_elapsed_ms = self._frame_elapsed_ms
        self._old_surface_cache = self._surface_cache

        # New animation starts fresh.
        self._animation = new_animation
        self._frame_idx = 0
        self._frame_elapsed_ms = 0.0
        self._surface_cache = {}
        self._precache_surfaces(
            new_animation, 0, self._surface_cache
        )

        self._crossfade_active = True
        self._crossfade_elapsed_ms = 0.0
        self._crossfade_duration_ms = duration_ms

        logger.debug(
            "Crossfade started: %s -> %s (%d ms)",
            self._old_animation.path,
            new_animation.path,
            duration_ms,
        )

    def is_crossfading(self) -> bool:
        """Return True if a crossfade transition is in progress."""
        return self._crossfade_active

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance playback by *dt* seconds.

        Progresses the frame index of both the current and (if
        crossfading) old animation, and maintains the look-ahead cache.

        Args:
            dt: Elapsed time in **seconds** since the previous call.
        """
        dt_ms = dt * 1000.0

        if self._animation is not None:
            self._advance(
                self._animation,
                dt_ms,
                is_old=False,
            )

        if self._crossfade_active and self._old_animation is not None:
            self._advance(
                self._old_animation,
                dt_ms,
                is_old=True,
            )
            self._crossfade_elapsed_ms += dt_ms
            if self._crossfade_elapsed_ms >= self._crossfade_duration_ms:
                self._cancel_crossfade()

    def _advance(
        self,
        animation: Animation,
        dt_ms: float,
        *,
        is_old: bool,
    ) -> None:
        """Advance frame index for *animation* by *dt_ms* milliseconds."""
        if is_old:
            elapsed = self._old_frame_elapsed_ms + dt_ms
            idx = self._old_frame_idx
        else:
            elapsed = self._frame_elapsed_ms + dt_ms
            idx = self._frame_idx

        # Consume elapsed time against successive frame durations.
        while elapsed >= animation.durations[idx]:
            elapsed -= animation.durations[idx]
            idx = (idx + 1) % animation.frame_count

        if is_old:
            self._old_frame_elapsed_ms = elapsed
            self._old_frame_idx = idx
        else:
            self._frame_elapsed_ms = elapsed
            self._frame_idx = idx
            # Maintain look-ahead cache for the active animation.
            self._precache_surfaces(
                animation, idx, self._surface_cache
            )

    # ------------------------------------------------------------------
    # Frame output
    # ------------------------------------------------------------------

    def get_current_frame(self) -> Optional[pygame.Surface]:
        """Return the current display frame as a Pygame SRCALPHA surface.

        During a crossfade this returns an alpha-blended composite of
        the old and new animations.  Outside a crossfade it returns the
        plain current frame.

        Returns:
            A Pygame surface sized to *target_size*, or *None* if no
            animation is loaded.
        """
        if self._animation is None:
            return None

        new_surf = self._get_surface(
            self._animation, self._frame_idx, self._surface_cache
        )

        if not self._crossfade_active or self._old_animation is None:
            return new_surf

        old_surf = self._get_surface(
            self._old_animation, self._old_frame_idx, self._old_surface_cache
        )

        # Blend: old fades out, new fades in.
        progress = min(
            self._crossfade_elapsed_ms / self._crossfade_duration_ms, 1.0
        )
        return self._blend_surfaces(old_surf, new_surf, progress)

    # ------------------------------------------------------------------
    # Surface conversion & caching
    # ------------------------------------------------------------------

    def _pil_to_surface(
        self, pil_img: Image.Image
    ) -> pygame.Surface:
        """Convert a PIL RGBA Image to a Pygame SRCALPHA surface.

        If ``_target_size`` is set the surface is scaled (smooth) to
        that size.
        """
        raw = pil_img.tobytes()
        size = pil_img.size  # (w, h)
        surf = pygame.image.frombuffer(raw, size, "RGBA").convert_alpha()

        if self._target_size is not None and self._target_size != size:
            surf = pygame.transform.smoothscale(surf, self._target_size)

        return surf

    def _get_surface(
        self,
        animation: Animation,
        idx: int,
        cache: dict[int, pygame.Surface],
    ) -> pygame.Surface:
        """Return a cached Pygame surface for frame *idx*, creating it if needed."""
        if idx not in cache:
            cache[idx] = self._pil_to_surface(animation.frames[idx])
        return cache[idx]

    def _precache_surfaces(
        self,
        animation: Animation,
        start_idx: int,
        cache: dict[int, pygame.Surface],
    ) -> None:
        """Ensure the next ``_cache_ahead`` frames are in *cache*.

        Old entries beyond the look-ahead window are evicted to keep
        memory bounded.
        """
        keep: set[int] = set()
        for offset in range(self._cache_ahead):
            idx = (start_idx + offset) % animation.frame_count
            keep.add(idx)
            if idx not in cache:
                cache[idx] = self._pil_to_surface(animation.frames[idx])

        # Evict frames outside the window.
        stale = [k for k in cache if k not in keep]
        for k in stale:
            del cache[k]

    # ------------------------------------------------------------------
    # Crossfade blending
    # ------------------------------------------------------------------

    @staticmethod
    def _blend_surfaces(
        old: pygame.Surface,
        new: pygame.Surface,
        progress: float,
    ) -> pygame.Surface:
        """Alpha-blend *old* and *new* surfaces based on *progress* (0..1).

        At progress=0 only *old* is visible; at progress=1 only *new*.
        Both surfaces must be the same size.
        """
        # We composite onto a fresh surface to avoid mutating the cached
        # originals.  Using per-surface alpha is the cheapest blending
        # approach Pygame offers.
        result = old.copy()
        result.set_alpha(int(255 * (1.0 - progress)))

        composite = pygame.Surface(old.get_size(), pygame.SRCALPHA)
        composite.blit(result, (0, 0))

        new_copy = new.copy()
        new_copy.set_alpha(int(255 * progress))
        composite.blit(new_copy, (0, 0))

        return composite

    def _cancel_crossfade(self) -> None:
        """End any active crossfade and release old-animation resources."""
        self._crossfade_active = False
        self._crossfade_elapsed_ms = 0.0
        self._crossfade_duration_ms = 0
        self._old_animation = None
        self._old_frame_idx = 0
        self._old_frame_elapsed_ms = 0.0
        self._old_surface_cache.clear()
