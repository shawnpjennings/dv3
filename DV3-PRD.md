# DV3 - Product Requirements Document

**Project**: DV3 (Voice Companion with Emotional Visualizer)
**Platform**: Ubuntu/WSL2 on Windows NUC
**Status**: Ready for Claude Code build
**Build approach**: Claude Code multi-agent / sub-agent execution

---

## Goal

A voice-activated home companion that listens for a wake word, conducts natural conversation via the Gemini Live API, and drives a fullscreen ambient visualizer that responds to emotional context extracted from the conversation. The visualizer plays animated WebP files organized by emotion bucket, with a black radial gradient mask that makes animations appear to float in space rather than sit in a box.

---

## Users

Single user, home environment. The system runs persistently and is used for natural conversation, music control, web search, timers, and ambient visual companionship.

---

## System Overview

Two separate applications:

1. **DV3 Voice Companion** — the always-on agent (this document's primary focus)
2. **DV3 Animation Editor** — standalone tool for preparing and organizing animation files

Both live at `~/projects/dv3/` in WSL2.

---

## Architecture

### Voice Pipeline

```
[Microphone]
    |
[OpenWakeWord] — local, CPU, lightweight gate
    |
[Gemini Live API] — single persistent WebSocket session
    |-- Built-in VAD (no Silero needed)
    |-- Built-in STT
    |-- LLM reasoning (gemini-2.5-flash-native-audio-preview)
    |-- Native TTS audio output
    |
[Audio output] — speakers
[Text output]  — parsed for emotion tags → visualizer event
```

### Abstraction Layer (Required from day one)

The voice pipeline must be implemented behind an abstract interface so the backend can be swapped without touching the visualizer, tools, or config.

```
core/voice_pipeline/
    base.py          # Abstract interface — emit_emotion(), emit_tool_request(), etc.
    gemini_live.py   # Gemini Live API implementation (build this first)
    modular.py       # Stub — future: OpenWakeWord + Whisper + ElevenLabs
```

The visualizer and all tools import from `base.py` only. Nothing imports from `gemini_live.py` directly except `main.py`.

### IPC: Voice Loop to Visualizer

Both systems run in the same Python process using asyncio. The voice loop puts emotion events on an `asyncio.Queue`. The visualizer coroutine reads from that queue and triggers animation transitions. No sockets, no separate processes needed for v1.

### Project Structure

```
~/projects/dv3/
├── main.py
├── core/
│   ├── voice_pipeline/
│   │   ├── base.py
│   │   ├── gemini_live.py
│   │   └── modular.py          # stub
│   ├── wake_word.py            # OpenWakeWord gate
│   └── emotion_parser.py       # tag extraction + keyword fallback
├── tools/
│   ├── spotify_tool.py
│   ├── timer_tool.py
│   └── system_tools.py         # time, date
├── visualizer/
│   ├── display.py              # Pygame window manager
│   ├── animation_engine.py     # WebP/GIF playback
│   ├── gradient_overlay.py     # radial edge fade
│   └── emotion_map.py          # emotion string → animation bucket path
├── editor/                     # standalone animation editor app
│   ├── main.py
│   ├── gallery.py
│   ├── editor_panel.py
│   ├── preview.py
│   ├── converter.py            # GIF → WebP batch conversion
│   └── gradient_tool.py
├── data/
│   └── animations/
│       ├── emotions/
│       │   ├── happy/
│       │   ├── excited/
│       │   ├── sad/
│       │   ├── thinking/
│       │   ├── confused/
│       │   ├── laughing/
│       │   ├── surprised/
│       │   ├── calm/
│       │   ├── alert/
│       │   ├── tired/
│       │   ├── sarcastic/
│       │   ├── neutral/
│       │   ├── concerned/
│       │   ├── curious/
│       │   └── proud/
│       └── contextual/
│           ├── music/
│           ├── weather/
│           └── special/
├── wakeword/
│   └── [.onnx and .tflite model files — configured via settings.yaml, never hardcoded]
├── config/
│   ├── settings.yaml
│   └── emotion_map.yaml
└── requirements.txt
```

---

## Requirements

### Must-Have (v1)

**Voice Pipeline**

1. OpenWakeWord gate using a configurable model file (path set in `settings.yaml`). Wake word detection triggers the Gemini Live session to begin receiving audio.
2. Gemini Live API (`gemini-2.5-flash-native-audio-preview`) handles VAD, STT, LLM, and TTS in a single persistent WebSocket session using the native `google-genai` Python SDK.
3. Audio input: PCM 16kHz mono 16-bit captured from default mic device (configurable).
4. Audio output: stream Gemini's audio response to speakers with minimal buffering.
5. Session reconnection: if the WebSocket drops, automatically attempt reconnect with exponential backoff (max 5 retries). Log the failure. Resume from neutral state.
6. API key fallback: primary and secondary Google API keys configurable in settings. On 429 rate limit, automatically switch to fallback key and reconnect.
7. WSL2 audio: check how existing Thumper project handles PyAudio in WSL2 and replicate that approach. Path: `~/projects/thumper/`.

**Emotion System**

8. Gemini is instructed via system prompt to begin every text response with a bracketed emotion tag: `[emotion]`. Example: `[curious] That's an interesting question...`
9. Emotion parser buffers the first 30 tokens of the text stream. Extracts tag using regex `\[(\w+)\]`. Fires visualizer event immediately on detection. Strips tag from any displayed text.
10. If no tag detected in first 30 tokens, run keyword fallback analysis on the text stream (exclamation marks → excited, "hmm"/"interesting" → thinking, "sorry"/"unfortunately" → concerned, etc.).
11. If neither method detects an emotion, default to `[neutral]`.
12. Contextual keyword detection runs on the user's transcribed speech in real time, not just on Gemini's response. This allows contextual animations to trigger the moment the user makes a request. Example: user says "play Dark Side of the Moon by Pink Floyd" → Pink Floyd animation fires immediately, before Gemini's reply arrives. Gemini's text response is still parsed for emotion tags in parallel.
13. Contextual keyword triggers override emotion triggers. If either the user's speech or Gemini's text stream contains specific keywords (music genre names, weather terms, etc.) a contextual animation is played instead. Priority: contextual > emotion > neutral.

**Visualizer**

13. Fullscreen Pygame window on the primary display. Black background.
14. Resolution-agnostic: query display resolution at startup. Animation area sized as a percentage of screen dimensions (default: 45% of screen height, maintaining animation's native aspect ratio, centered).
15. Animation area size and position are configurable at runtime (via admin controls or config).
16. Animated WebP files are the primary format. GIF playback also supported natively (for files not yet converted).
17. Radial black gradient mask applied over the animation area, fading edges to black. Opacity adjustable 0-100%. Size (how far the gradient extends inward) adjustable as percentage of animation area. Both adjustable at runtime.
18. Crossfade transition between animations: configurable duration (default 300ms), alpha blend.
19. Animation selected randomly from the matching emotion bucket directory.
20. Animations loop seamlessly.
21. Target 60fps playback. Pre-cache next 30 frames during playback.
22. Contextual animations: specific keyword matches (e.g., Pink Floyd → specific file, "jazz" → random from jazz folder) play for a configured duration then return to emotion-based animation.

**Tools (v1)**

23. **Spotify**: play, pause, skip, previous, volume, search by track/artist/album, get now playing. Use `spotipy` library with OAuth. Credentials in `.env`, never in code or config files committed to git.
24. **Web search**: use Gemini Live API's built-in Google Search grounding tool (`google_search` in setup config). No external search API needed.
25. **Timer**: set a timer by duration (e.g., "set a 10 minute timer"). On completion, play an audio alert and announce via TTS. Multiple concurrent timers supported.
26. **Time/date**: return current time and date. Native Python, no API.

**Gemini Tool Calling**

27. Tools declared as `function_declarations` in the Live API setup config. When Gemini emits a `tool_call` message mid-stream, the code executes the function and returns a `tool_response` message. Gemini resumes audio output after receiving the result.
28. Tool execution is async and non-blocking. Audio stream continues (or pauses gracefully) while the tool executes.

**Animation Editor (v1 — required to prepare animation library)**

29. Load and display animated WebP and GIF files from a directory.
30. Animated thumbnail gallery (grid layout, all thumbnails playing simultaneously).
31. Batch convert GIF files to animated WebP.
32. Crop tool: freeform crop, center crop, preset aspect ratios. Applies to all frames.
33. Watermark/region removal: paint-fill a rectangular region with black (or a sampled color) across all frames. This handles watermarks and logos in animation corners.
34. Add black border/padding: add configurable padding around the animation to push content away from edges ("outfill"). Creates breathing room for the gradient mask.
35. Gradient mask preview and export: apply and preview the radial black gradient directly in the editor. Export the processed WebP with gradient baked in, or export clean and let the visualizer apply it live.
36. Speed control: adjust frame delays to change playback speed (0.25x to 4x).
37. Dark UI theme.
38. Keyboard shortcuts for common operations.

**Configuration**

39. All user-specific values (API keys, voice model paths, wake word model paths, device preferences) live in `.env` or `settings.yaml`. Nothing sensitive or user-specific is hardcoded in source files, README, or documentation.
40. `settings.yaml` includes: wake word model path, primary/fallback API keys, audio device indices, animation directory path, gradient defaults, animation area size defaults, Spotify credentials path.

---

### Nice-to-Have (v1.5+)

- TAPO smart bulb control via `python-tapo` (local LAN, no Home Assistant required)
- Govee light control via Govee cloud API
- TV control via ADB
- OpenMemory integration for persistent cross-session memory (once configured at `~/OpenMemory`)
- Multiple animation layers (background + foreground)
- Admin web panel for runtime config adjustments

---

## Technical Constraints

- **Gemini Live API requires native SDK**: `google-genai` Python SDK with async WebSocket. Not accessible via the OpenAI-compatible Gemini endpoint. All voice pipeline code must use `google.genai` types.
- **Gemini tool calling differs from OpenAI**: tools are declared in setup config, not per-request. Tool calls come as mid-stream WebSocket messages, not in a final response object.
- **WebP is preferred over GIF**: better compression, smoother playback in Pygame. All GIFs in the animation library should be converted via the editor before deployment. The visualizer supports GIF as fallback only.
- **WSL2 audio**: PyAudio in WSL2 requires PulseAudio or PipeWire bridging. Check and replicate the approach used in `~/projects/thumper/` before implementing from scratch.
- **No hardcoded personal data**: wake word names, voice IDs, device names, account details must never appear in source files, README, or documentation. Reference via config keys only.
- **Single process, async**: voice loop and visualizer run as coroutines in the same asyncio event loop. Communication via `asyncio.Queue`.

---

## Emotion Tag System Prompt (Required in Gemini system instruction)

```
Before every response, begin with a single emotion tag in brackets that describes 
your current tone. Choose from this list only:
[excited] [happy] [sad] [thinking] [confused] [laughing] [surprised] [calm] 
[alert] [tired] [sarcastic] [neutral] [curious] [proud] [concerned]

The tag must be the very first thing in your text response, before any other content.
Example: [curious] That's an interesting question...
```

---

## Emotion to Animation Bucket Mapping

Defined in `config/emotion_map.yaml`. Structure:

```yaml
emotions:
  happy:
    directory: data/animations/emotions/happy
    fallback: neutral
  excited:
    directory: data/animations/emotions/excited
    fallback: happy
  # ... all 15 emotions

contextual_triggers:
  music:
    - patterns: [pink floyd, dark side of the moon]
      file: data/animations/contextual/music/pink_floyd_prism.webp
      duration: 8.0
      priority: 10
    - patterns: [jazz]
      directory: data/animations/contextual/music/jazz
      duration: 10.0
      priority: 8
  weather:
    - patterns: [sunny, sunshine]
      directory: data/animations/contextual/weather/sun
      priority: 7
  # ... etc
```

---

## Visualizer Display Spec

```
[FULLSCREEN — black background]

         [RADIAL GRADIENT MASK — fades edges to black]
    +------------------------------------------+
    |                                          |
    |     [ANIMATED WEBP — centered,           |
    |      sized to % of screen height,        |
    |      aspect ratio preserved]             |
    |                                          |
    +------------------------------------------+
         [gradient opacity: 0-100%, adjustable]
         [gradient size: % of animation area, adjustable]
```

The animation content should appear to float in black space, not sit in a visible box. The gradient must be strong enough at the edges to eliminate any visible hard boundary from the animation file itself. If an animation has content too close to its edges, the editor's outfill (padding) tool should be used to create space for the gradient to work.

---

## Acceptance Criteria

- [ ] Wake word detection triggers Gemini Live session within 500ms
- [ ] Gemini Live session produces first audio within 1500ms of wake word on local network
- [ ] Emotion tag detected and visualizer animation triggered before or as audio begins playing
- [ ] Animation crossfade completes without visible stutter at 60fps
- [ ] Gradient mask eliminates visible hard edges on all prepared animation files
- [ ] Spotify play command executes and music starts within 2 seconds of tool call
- [ ] Timer fires audio alert at correct time
- [ ] On WebSocket drop, system reconnects automatically and resumes within 10 seconds
- [ ] On primary API key 429, system switches to fallback key and continues without user action
- [ ] No personal names, account IDs, device names, or sensitive values appear in any source file or documentation
- [ ] Animation editor successfully batch converts GIF files to WebP
- [ ] Animation editor crop and outfill tools apply correctly across all frames of a multi-frame file
- [ ] Watermark removal tool paints selected region black across all frames

---

## Build Verification Requirements

Claude Code agents must verify completion using functional tests, not just code review:

- **Audio pipeline**: run a test script that opens the mic, detects a spoken test phrase via wake word, sends to Gemini Live, and prints the text response to console. Confirm with output log.
- **Emotion parsing**: unit test with mock text streams containing tags, missing tags, and edge cases. All cases must pass before integration.
- **Visualizer**: launch the visualizer window, programmatically emit a sequence of emotion events, and use a screenshot or frame capture to confirm animations are changing. Do not mark visualizer complete based on code review alone.
- **Spotify tool**: execute a test play command and confirm via Spotify API `currently_playing` endpoint that the correct track is playing.
- **Editor tools**: run batch conversion on the temp_images directory, confirm all GIFs produce valid WebP output. Run crop and outfill on a sample file and inspect output frames.
- **WSL2 audio**: confirm PyAudio can open mic and speakers before any other audio work proceeds. If it cannot, resolve the PulseAudio/PipeWire bridge before continuing.

---

## Existing Assets

Animation files (mixed WebP and GIF, unsorted) are located at:
`~/projects/dv3/temp_images/`

These need to be sorted into emotion buckets and contextual folders as part of setup. The editor's gallery view is the tool for doing this.

Wake word model files (.onnx and .tflite) are located at:
`~/projects/thumper/wakeword/`

Reference these via `settings.yaml` path config. Do not copy or rename them — use the existing files.

---

## Setup and Infrastructure

**GitHub**
Repository: `shawnpjennings/dv3` — not yet synced at time of writing. Claude Code should initialize git, set the remote, and push initial structure.

**BEADS**
BEADS (`bd`) is already installed. Run `bd init` in the project root before starting any build work. Claude Code should use `bd` for all task tracking, dependency management, and progress throughout the build. This gives agents persistent structured memory across the entire build. Reference: https://github.com/steveyegge/beads

**Folder Structure**
Claude Code creates the full folder structure from scratch based on the structure defined in this PRD. Do not assume any folders exist beyond what is already present in `~/projects/dv3/`.

**.gitignore — Required entries (add before first push)**
```
.env
temp_images/
temp/
__pycache__/
*.pyc
venv/
.pytest_cache/
*.onnx
*.tflite
```

**Temp folder (`~/projects/dv3/temp/`)**
Contains test assets for development and verification — do not commit. Contents:
- Audio samples for testing wake word detection, VAD, and STT
- Sample WebP and GIF image files for visualizer testing
- OpenWakeWord model files (.onnx and .tflite)

Claude Code should use these assets for the verification steps outlined in the Acceptance Criteria section rather than requiring live mic/speaker testing for every run.

**.env**
A `.env` file already exists in the project root containing the two Gemini API keys (primary and fallback). This file must never be committed. Confirm `.env` is in `.gitignore` before any `git push`.

**Verification and Testing**
All features must be verified with Playwright or equivalent functional testing before being marked complete. Code review alone is not sufficient. See the Acceptance Criteria section for specific verification requirements per feature. No task is done until it is tested and confirmed working.

---

## Open Questions (Decide before or during build)

1. Does the Gemini Live API voice quality satisfy the use case, or is a TTS swap needed? Evaluate during first working prototype.
2. Should the visualizer support multiple simultaneous animation layers (e.g., background ambient loop + foreground emotion burst)? Defer to v1.5 unless trivial to add.
3. GIF-to-WebP conversion: does it preserve animation quality acceptably for all source files? Verify with the batch converter before committing to WebP-only.
4. Should the visualizer support multiple simultaneous animation layers (e.g., background ambient loop + foreground emotion burst)? Defer to v1.5 unless trivial to add.
