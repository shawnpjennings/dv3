"""Pygame fullscreen window manager for the DV3 visualizer.

Handles display initialization, resolution detection, frame compositing,
and clean shutdown. All rendering flows through this module: the main loop
asks AnimationEngine for a frame, GradientOverlay for a mask, and hands
both to DisplayManager.render_frame() which composites them onto a black
background.

The display is resolution-agnostic -- it queries the monitor at startup and
scales everything proportionally using animation_height_pct from settings.
"""

from __future__ import annotations

import logging
from typing import Optional

import pygame

logger = logging.getLogger(__name__)


class DisplayManager:
    """Manages the Pygame display surface, scaling, and frame compositing.

    Typical lifecycle::

        dm = DisplayManager(config)
        screen = dm.init_display()
        # ... main loop ...
        dm.render_frame(screen, anim_frame, gradient_surface)
        # ...
        dm.cleanup()

    Attributes:
        screen_width: Detected horizontal resolution in pixels.
        screen_height: Detected vertical resolution in pixels.
        clock: Pygame clock used to cap the frame rate.
    """

    def __init__(self, config: dict) -> None:
        """Initialize display settings from configuration.

        Args:
            config: The ``visualizer`` section of settings.yaml.  Expected
                keys: ``fullscreen``, ``target_fps``, ``animation_height_pct``.
        """
        self._fullscreen: bool = config.get("fullscreen", True)
        self._target_fps: int = config.get("target_fps", 60)
        self._anim_height_pct: float = config.get("animation_height_pct", 0.45)

        self.screen_width: int = 0
        self.screen_height: int = 0
        self.clock: Optional[pygame.time.Clock] = None

        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_display(self) -> pygame.Surface:
        """Create the Pygame window and return the root surface.

        Initialises Pygame, queries monitor resolution, and opens a
        fullscreen (or windowed) display.  The mouse cursor is hidden in
        fullscreen mode.

        Returns:
            The root ``pygame.Surface`` to blit onto.

        Raises:
            pygame.error: If Pygame cannot initialize the display.
        """
        pygame.init()

        # Query native resolution *before* setting the mode so we get
        # the real monitor size rather than whatever Pygame defaults to.
        info = pygame.display.Info()
        self.screen_width = info.current_w
        self.screen_height = info.current_h

        if self._fullscreen:
            flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
            surface = pygame.display.set_mode(
                (self.screen_width, self.screen_height), flags
            )
            pygame.mouse.set_visible(False)
        else:
            # Windowed mode -- use 80% of screen for easier debugging.
            self.screen_width = int(self.screen_width * 0.8)
            self.screen_height = int(self.screen_height * 0.8)
            surface = pygame.display.set_mode(
                (self.screen_width, self.screen_height)
            )

        pygame.display.set_caption("DV3 Visualizer")
        self.clock = pygame.time.Clock()
        self._initialized = True

        logger.info(
            "Display initialized: %dx%d @ %d fps (fullscreen=%s)",
            self.screen_width,
            self.screen_height,
            self._target_fps,
            self._fullscreen,
        )
        return surface

    def cleanup(self) -> None:
        """Quit Pygame and release display resources.

        Safe to call multiple times or before ``init_display``.
        """
        if self._initialized:
            pygame.quit()
            self._initialized = False
            logger.info("Display cleaned up")

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def get_animation_rect(self, anim_size: tuple[int, int]) -> pygame.Rect:
        """Calculate a centered, aspect-ratio-correct rect for the animation.

        The animation is scaled so its height equals
        ``screen_height * animation_height_pct``.  Width is derived from
        the native aspect ratio of *anim_size* to avoid distortion.  The
        rect is then centered on screen.

        Args:
            anim_size: ``(width, height)`` of the source animation in
                pixels (before scaling).

        Returns:
            A ``pygame.Rect`` positioned and sized for blitting the
            scaled animation.
        """
        native_w, native_h = anim_size
        if native_h == 0:
            native_h = 1  # guard against degenerate input

        target_h = int(self.screen_height * self._anim_height_pct)
        aspect = native_w / native_h
        target_w = int(target_h * aspect)

        x = (self.screen_width - target_w) // 2
        y = (self.screen_height - target_h) // 2
        return pygame.Rect(x, y, target_w, target_h)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_frame(
        self,
        surface: pygame.Surface,
        animation_frame: pygame.Surface,
        gradient_surface: pygame.Surface,
    ) -> None:
        """Composite a single display frame: black bg -> animation -> gradient.

        This is called once per iteration of the main loop.  The caller
        should follow up with ``pygame.display.flip()`` and
        ``clock.tick(target_fps)``.

        Args:
            surface: The root display surface (from ``init_display``).
            animation_frame: The current animation frame, already scaled
                to the animation rect dimensions.
            gradient_surface: The pre-rendered radial gradient overlay,
                same size as *animation_frame*.
        """
        # 1. Clear to black
        surface.fill((0, 0, 0))

        # 2. Calculate placement and blit animation
        anim_rect = self.get_animation_rect(animation_frame.get_size())
        surface.blit(animation_frame, anim_rect)

        # 3. Overlay gradient mask at the same position
        surface.blit(gradient_surface, anim_rect)

    def tick(self) -> float:
        """Advance the clock and cap the frame rate.

        Returns:
            Delta time in seconds since the last call.

        Raises:
            RuntimeError: If called before ``init_display``.
        """
        if self.clock is None:
            raise RuntimeError("tick() called before init_display()")
        dt_ms = self.clock.tick(self._target_fps)
        return dt_ms / 1000.0

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    @staticmethod
    def should_quit() -> bool:
        """Process the Pygame event queue and return True if exit requested.

        Checks for ``pygame.QUIT`` (window close) and ``ESC`` key press.
        All other events are consumed and discarded.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return True
        return False

    @property
    def target_fps(self) -> int:
        """Configured target frame rate."""
        return self._target_fps

    @property
    def animation_height_pct(self) -> float:
        """Fraction of screen height allocated to the animation."""
        return self._anim_height_pct
