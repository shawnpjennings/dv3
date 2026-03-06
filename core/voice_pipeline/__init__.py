"""DV3 voice pipeline abstraction layer.

Import the base class for type hints and the concrete implementations
for instantiation in main.py:

    from core.voice_pipeline import VoicePipelineBase, GeminiLivePipeline

Consumer code (visualizer, tools, emotion parser) should depend only
on VoicePipelineBase. The active backend is selected at startup based
on the ``voice.backend`` setting in config/settings.yaml.
"""

from .base import VoicePipelineBase

__all__ = [
    "VoicePipelineBase",
    "GeminiLivePipeline",
]


def __getattr__(name: str):
    """Lazy-import GeminiLivePipeline to avoid hard dependency on google-genai."""
    if name == "GeminiLivePipeline":
        from .gemini_live import GeminiLivePipeline
        return GeminiLivePipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
