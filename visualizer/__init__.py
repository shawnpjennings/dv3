"""DV3 visualizer -- Pygame display, animation engine, gradient overlay.

Heavy modules (AnimationEngine, DisplayManager, GradientOverlay) depend on
PIL and Pygame, which are not available in headless mode.  They are imported
lazily — only when accessed via this package — so that headless code can
safely do ``from visualizer.emotion_map import EmotionMapper``.
"""

from .emotion_map import EmotionMapper

__all__ = [
    "DisplayManager",
    "AnimationEngine",
    "GradientOverlay",
    "EmotionMapper",
]


def __getattr__(name: str):
    if name == "DisplayManager":
        from .display import DisplayManager
        return DisplayManager
    if name == "AnimationEngine":
        from .animation_engine import AnimationEngine
        return AnimationEngine
    if name == "GradientOverlay":
        from .gradient_overlay import GradientOverlay
        return GradientOverlay
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
