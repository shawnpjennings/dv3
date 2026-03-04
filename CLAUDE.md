# DV3 - Voice Companion with Emotional Visualizer

## Project Summary
Voice-activated home companion: wake word → Gemini Live API conversation → emotion-tagged animated visualizer. Runs on Ubuntu/WSL2 on a NUC.

## Architecture
- Single Python process, asyncio event loop
- Voice loop and visualizer communicate via `asyncio.Queue`
- Voice pipeline behind abstract interface (`core/voice_pipeline/base.py`)
- Nothing imports from backend implementations directly except `main.py`

## Key Patterns
- **Audio in WSL2**: Use `sounddevice` (not PyAudio), prefer PulseAudio backend over ALSA, threaded stream open with timeout. Pattern from `~/projects/thumper/`.
- **Config**: User-specific values in `.env`, app config in `config/settings.yaml`. Never hardcode personal data.
- **Emotion flow**: Gemini text → regex `\[(\w+)\]` on first 30 tokens → keyword fallback → default neutral. Events via asyncio.Queue.

## Commands
- `python main.py` — run the companion
- `python -m editor.main` — run the animation editor
- `pytest tests/` — run all tests
- `bd` — BEADS task tracking

## File Layout
- `core/voice_pipeline/` — abstract base + implementations
- `core/wake_word.py` — OpenWakeWord gate
- `core/emotion_parser.py` — tag extraction + keyword fallback
- `visualizer/` — Pygame display, animation engine, gradient overlay
- `editor/` — standalone animation editor (Pygame GUI)
- `tools/` — Spotify, timer, system tools
- `config/` — settings.yaml, emotion_map.yaml

## Rules
- NEVER commit `.env` or any API keys/secrets
- NEVER hardcode device names, account IDs, or personal data in source
- All features must be verified with functional tests, not code review alone
- Wake word model paths configured via settings.yaml, never hardcoded
- Prefer WebP over GIF for animations
