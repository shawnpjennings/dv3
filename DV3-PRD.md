# DV3 - Product Requirements Document

**Project**: DV3 (Voice Companion with Emotional Visualizer)
**Platform**: Ubuntu/WSL2 on Windows NUC
**Status**: Active Development — voice pipeline operational, web editor shipped, animation library migration in progress
**Build approach**: Claude Code multi-agent / sub-agent execution

---

## Goal

A voice-activated home companion that listens for a wake word, conducts natural conversation via the Gemini Live API, and drives a fullscreen ambient visualizer that responds to emotional context extracted from the conversation. The visualizer plays animated WebP files selected by emotion tag, with a black radial gradient mask that makes animations appear to float in space rather than sit in a box.

---

## Users

Single user, home environment. The system runs persistently and is used for natural conversation, music control, web search, timers, and ambient visual companionship.

---

## System Overview

Two separate applications:

1. **DV3 Voice Companion** — the always-on agent (this document's primary focus)
2. **DV3 Editor** — browser-based tool for preparing, adjusting, and tagging animation files (`editor-web/`). Replaced the legacy Pygame editor.

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
    |-- LLM reasoning (gemini-2.5-flash-native-audio-latest)
    |-- Native TTS audio output
    |
[Audio output] — speakers
[Text output]  — parsed for emotion tags → visualizer event
```

### Abstraction Layer

The voice pipeline is implemented behind an abstract interface so the backend can be swapped without touching the visualizer, tools, or config.

```
core/voice_pipeline/
    base.py          # Abstract interface — emit_emotion(), emit_tool_request(), etc.
    gemini_live.py   # Gemini Live API implementation (active)
    modular.py       # Stub — future: OpenWakeWord + Whisper + ElevenLabs
```

The visualizer and all tools import from `base.py` only. Nothing imports from `gemini_live.py` directly except `main.py`.

### IPC: Voice Loop to Visualizer

Both systems run in the same Python process using asyncio. The voice loop puts emotion events on an `asyncio.Queue`. The visualizer coroutine reads from that queue and triggers animation transitions. No sockets, no separate processes needed for v1.

### WebSocket Server

An aiohttp WebSocket server (`core/visualizer_ws.py`) runs on port 8765 and broadcasts emotion/state/tag events to optional web visualizer clients (`visualizer-web/`).

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
│   ├── emotion_parser.py       # tag extraction + keyword fallback + contextual
│   └── visualizer_ws.py        # WebSocket server for web visualizer clients
├── tools/
│   ├── tool_dispatcher.py
│   ├── spotify_tool.py
│   ├── timer_tool.py
│   └── system_tools.py         # time, date
├── visualizer/
│   ├── display.py              # Pygame window manager
│   ├── animation_engine.py     # WebP/GIF playback, crossfade, frame cache
│   ├── gradient_overlay.py     # radial edge fade
│   └── emotion_map.py          # manifest-based animation resolver
├── editor/                     # LEGACY — headless batch conversion only
│   └── converter.py            # GIF → WebP batch conversion (CLI use only)
├── editor-web/                 # PRIMARY animation editor (DV3 Editor)
│   ├── src/
│   │   ├── App.tsx             # root app, state management, inbox/library tabs
│   │   ├── types.ts            # InboxItem, LibraryAsset, Manifest, EditAction, SavePayload
│   │   ├── components/
│   │   │   ├── GalleryPanel.tsx      # asset grid, thumbnails, selection
│   │   │   ├── EditorPanel.tsx       # edit controls (brightness, flip, crop, speed, etc.)
│   │   │   ├── TagPanel.tsx          # metadata: emotions, states, custom tags, theme, title, notes
│   │   │   ├── InboxPanel.tsx        # import untagged assets via File System Access API
│   │   │   ├── LibraryPanel.tsx      # browse and re-edit tagged/baked assets
│   │   │   ├── TopToolbar.tsx        # global header, folder status, settings
│   │   │   ├── SidebarPanel.tsx      # inbox/library tab switcher
│   │   │   ├── SettingsModal.tsx     # app preferences, export root folder
│   │   │   ├── ErrorBoundary.tsx     # error handling wrapper
│   │   │   ├── VariantComparison.tsx # side-by-side compare mode
│   │   │   └── CircleCheck.tsx       # shared checkbox component
│   │   └── lib/
│   │       ├── bakeUtils.ts          # FFmpeg WASM integration, render pipeline
│   │       ├── exportUtils.ts        # ZIP export, manifest generation
│   │       ├── db.ts                 # IndexedDB CRUD
│   │       ├── inboxUtils.ts         # file copy/convert to inbox
│   │       ├── thumbStyles.ts        # thumbnail preview styling
│   │       └── validation.ts         # file type validation
│   └── package.json
├── visualizer-web/             # Optional web visualizer (early stage)
├── data/
│   └── animations/
│       ├── manifest.json       # generated by editor on save — asset index (single source of truth)
│       ├── inbox/              # raw imported files, awaiting tagging
│       └── library/            # baked animations (flat dir), ready for runtime use
├── wakeword/                   # model files — configured via settings.yaml, never hardcoded
├── config/
│   ├── settings.yaml
│   └── emotion_map.yaml
├── tests/
└── requirements.txt
```

---

## Requirements

### Must-Have (v1)

**Voice Pipeline** 

1. OpenWakeWord gate using a configurable model file (path set in `settings.yaml`). Wake word detection triggers the Gemini Live session to begin receiving audio.
2. Gemini Live API (`gemini-2.5-flash-native-audio-latest`) handles VAD, STT, LLM, and TTS in a single persistent WebSocket session using the native `google-genai` Python SDK.
3. Audio input: PCM 16kHz mono 16-bit captured from default mic device (configurable).
4. Audio output: stream Gemini's audio response to speakers with minimal buffering.
5. Session reconnection: if the WebSocket drops, automatically attempt reconnect with exponential backoff (max 5 retries). Log the failure. Resume from neutral state.
6. API key fallback: primary and secondary Google API keys configurable in `.env`. On 429 rate limit, automatically switch to fallback key and reconnect.
7. WSL2 audio: use `sounddevice` (not PyAudio) with PulseAudio bridge. Matches approach in `~/projects/thumper/`.

**Emotion System** 

8. Gemini is instructed via system prompt to begin every text response with a bracketed emotion tag: `[emotion]`. Example: `[curious] That's an interesting question...`
9. Emotion parser buffers the first 30 tokens of the text stream. Extracts tag using regex `\[(\w+)\]`. Fires visualizer event immediately on detection. Strips tag from any displayed text.
10. If no tag detected in first 30 tokens, run keyword fallback analysis on the text stream.
11. If neither method detects an emotion, default to `[neutral]`.
12. Contextual keyword detection runs on the user's transcribed speech in real time. Fires the contextual animation immediately, before Gemini's reply arrives. Gemini's text response is still parsed for emotion tags in parallel.
13. Contextual keyword triggers override emotion triggers. Priority: contextual > emotion > neutral.

**Visualizer** 

14. Fullscreen Pygame window on the primary display. Black background.
15. Resolution-agnostic: query display resolution at startup. Animation area sized as a percentage of screen dimensions (default: 65% of screen height), centered, aspect ratio preserved.
16. Animation area size and position configurable via `settings.yaml`.
17. Animated WebP files are the primary format. GIF playback also supported natively.
18. Radial black gradient mask applied over the animation area, fading edges to black. Opacity and size adjustable in `settings.yaml`.
19. Crossfade transition between animations: configurable duration (default 300ms), alpha blend.
20. Animation selected randomly from the matching tagged asset set (via `manifest.json`).
21. Animations loop seamlessly.
22. Target 60fps playback. Pre-cache next 30 frames during playback.
23. Contextual animations: play for configured duration then return to emotion-based animation.

**Tools (v1)** 

24. **Spotify**: play, pause, skip, previous, volume, search by track/artist/album, get now playing. Via `spotipy` library with OAuth. Credentials in `.env`.
25. **Web search**: Gemini Live API's built-in Google Search grounding (`google_search` in setup config). No external search API needed.
26. **Timer**: set a timer by duration. On completion, play an audio alert and announce via TTS. Multiple concurrent timers supported.
27. **Time/date**: return current time and date. Native Python, no API.

**Gemini Tool Calling** 

28. Tools declared as `function_declarations` in the Live API setup config. Tool calls executed and responses returned while audio stream continues.
29. Tool execution is async and non-blocking.

**DV3 Editor (browser-based — PRIMARY)** 

30. React + TypeScript + Vite app at `editor-web/`. Runs at `http://localhost:5173`.
31. All asset data persisted in browser IndexedDB (`DV3EditorDB`). No server required.
32. Upload GIF, WebP, PNG, JPG via File System Access API. Files copied to `data/animations/inbox/`.
33. Non-destructive edit stack: adjustments stored per-asset, original file never modified. Save = FFmpeg WASM render with all edits applied.
34. Edit tools: Flip H/V, Size/Zoom, Position X/Y, Outfill background color, Crop to square, Circle mask, Brightness, Contrast, Hue, Saturation, Grayscale, Invert, Vignette, Background swap (beta), Speed multiplier (0.1x–4x), Reverse frames.
35. Multi-selection with Shift+click (range) and Ctrl+click (toggle). Batch export and batch rename.
36. Each asset tagged with: emotions (primary + additional), states, custom tags, theme (dark/light/both), title, notes. Tags drive DV3 animation routing.
37. Save bakes edits via FFmpeg WASM, writes final WebP to `animations/library/`, and updates `manifest.json`.
38. Library tab allows browsing saved assets, re-editing, duplicating, or removing.
39. Export produces a ZIP containing all library WebPs + `manifest.json` for backup or transfer.
40. Undo/redo history with labeled Undo/Redo text buttons.
41. Visualizer Preview mode shows how animation will look with the DV3 gradient mask.
42. Compare mode for side-by-side before/after.

**Animation Asset Model** 

43. `manifest.json` is the single source of truth for the animation library. Flat structure — all baked assets live in `animations/library/`, indexed by manifest.
44. `EmotionMapper` loads `manifest.json` at startup. Queries by emotion, state, or custom tag. Fallback chains defined in `emotion_map.yaml`.
45. Old folder-based structure (`emotions/`, `contextual/`, `states/`) is deprecated. Migration to inbox→library workflow is the current active work item.

**Emotion/Context/State model**

- **Emotion**: how DV3 feels/expresses (`neutral`, `happy`, `excited`, etc.)
- **Context/State**: what the agent is doing (`idle`, `listening`, `processing`)
- Default resting state: `neutral` emotion + `idle` state. These are separate axes.

**Configuration** 

46. All runtime values in `settings.yaml`. Sensitive values (API keys, credentials) in `.env` only. Nothing sensitive is hardcoded.
47. `emotion_map.yaml` defines all emotion/state/contextual trigger mappings, fallback chains, and keyword lists.

---

### Nice-to-Have (v1.5+)

- TAPO smart bulb control via `python-tapo` (local LAN, no Home Assistant required)
- Govee light control via Govee cloud API
- TV control via ADB
- OpenMemory integration for persistent cross-session memory
- Multiple animation layers (background + foreground)
- Admin web panel for runtime config adjustments
- Light theme variant (dark/light/both asset tagging already supported — add light-themed animations)

---

## Technical Constraints

- **Gemini Live API requires native SDK**: `google-genai` Python SDK with async WebSocket. Not accessible via the OpenAI-compatible Gemini endpoint.
- **Gemini tool calling differs from OpenAI**: tools declared in setup config, not per-request. Tool calls come as mid-stream WebSocket messages.
- **WebP is preferred over GIF**: better compression, smoother playback. All GIFs should be converted via the editor before deployment. GIF is supported as fallback only.
- **WSL2 audio**: use `sounddevice` (not PyAudio) with PulseAudio bridge. See `core/wake_word.py` for implementation.
- **No hardcoded personal data**: wake word names, voice IDs, device names, account details must never appear in source files, README, or documentation.
- **Single process, async**: voice loop and visualizer run as coroutines in the same asyncio event loop. Communication via `asyncio.Queue`.

---

## Emotion Tag System Prompt (Required in Gemini system instruction)

```
Before every response, begin with a single emotion tag in brackets that describes
your current tone. Choose from this list only:
[excited] [happy] [sad] [thinking] [confused] [laughing] [surprised] [calm]
[alert] [tired] [sarcastic] [neutral] [curious] [proud] [concerned] [angry] [roast]

The tag must be the very first thing in your text response, before any other content.
Example: [curious] That's an interesting question...
```

---

## Emotion to Animation Mapping

Defined in `config/emotion_map.yaml`. Runtime resolution:

1. `EmotionMapper.query(emotion)` → scans `manifest.json` for assets tagged with that emotion
2. If no match, follows fallback chain from `emotion_map.yaml` (e.g., `excited → happy → neutral`)
3. Returns a random asset from the matching set

Contextual triggers also defined in `emotion_map.yaml` — pattern lists, durations, and priorities.

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

The animation content should appear to float in black space. The gradient must be strong enough at the edges to eliminate any visible hard boundary. If an animation has content too close to its edges, use the editor's outfill tool to create space for the gradient.

---

## Acceptance Criteria

**Voice Pipeline**
- [ ] Wake word detection triggers Gemini Live session within 500ms
- [ ] Gemini Live session produces first audio within 1500ms of wake word on local network
- [ ] On WebSocket drop, system reconnects automatically and resumes within 10 seconds
- [ ] On primary API key 429, system switches to fallback key and continues without user action
- [ ] VAD Interrupt tested and working with Shawn Paul
- [ ] Wake word detection tested and working with Shawn Paul

**Visualizer**
- [ ] Emotion tag detected and visualizer animation triggered before or as audio begins playing
- [ ] Animation crossfade completes without visible stutter at 60fps
- [ ] Gradient mask eliminates visible hard edges on all prepared animation files
- [ ] Ctrl + shift + v opens visualizer settings panel
- [ ] Gradient opacity: 0-100%, adjustable in Visualizer settings panel
- [ ] Gradient size: % of animation area, adjustable in Visualizer settings panel
- [ ] Animation crossfade, adjustable in Visualizer settings panel

**Tools**
- [ ] Spotify play command executes and music starts within 2 seconds of tool call
- [ ] Timer fires audio alert at correct time
- [ ] Triggers animations with default music controls, and artist name, song title
- [ ] Spotify tool calls and animation triggers tested in preview or playwright


**Editor**
- [ ] Upload GIF/WebP, apply edits, save renders correct WebP via FFmpeg WASM
- [ ] Baked WebP and manifest entry appear in `data/animations/library/` after save
- [ ] Re-editing a library item loads the baked file with pre-populated tags
- [ ] Manifest.json contains correct emotion/state/tag/theme metadata

**Security**
- [ ] No personal names, account IDs, device names, or sensitive values appear in any source file or documentation

---

## Build Verification Requirements

Claude Code agents must verify completion using functional tests, not just code review:

- **Audio pipeline**: run a test script that opens the mic, detects a spoken test phrase via wake word, sends to Gemini Live, and prints the text response to console. Confirm with output log.
- **Emotion parsing**: `pytest tests/test_emotion_parser.py -v` — all cases pass.
- **Visualizer**: launch the visualizer window, programmatically emit a sequence of emotion events, confirm animations are changing. Do not mark visualizer complete based on code review alone.
- **Spotify tool**: execute a test play command and confirm via Spotify API `currently_playing` endpoint.
- **DV3 Editor**: `npm run dev` in `editor-web/`, navigate to localhost:5173 via Playwright, import a test file, apply edits, save, confirm WebP + manifest.json are written correctly.
- **WSL2 audio**: confirm `sounddevice` can open mic and speakers before any other audio work proceeds.

---

## Current Work Queue

From BEADS (`bd ready`):

| ID | Priority | Type | Title |
|----|----------|------|-------|
| dv-n9a | P1 | bug | Fix remove action |
| dv-1tv | P2 | task | Update tags/triggers in emotion_map.yaml |
| dv-4vw | P2 | feature | Event tags |
| dv-m48 | P2 | feature | Add Paint Feature |
| dv-xst | P2 | bug | Error trying to save image |
| dv-3lb | P2 | bug | Error trying to save image (duplicate) |
| dv-5ew | P2 | task | Improve UX |
| dv-67b | P2 | feature | Add Delete to inbox and library galleries |
| dv-p12 | P2 | bug | Popout notifications should say DV3 EDITOR |

**Next major milestone**: Animation library migration — run `scripts/migrate_to_inbox.py` to import old assets into the inbox, re-tag via DV3 Editor, and clean up the old folder structure.

---

## Setup and Infrastructure

**GitHub**: `shawnpjennings/dv3`

**BEADS**: `bd` is installed. Run `bd ready` to see available work. All task tracking is done via BEADS — do not create markdown TODO lists.

**.gitignore entries (required):**
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
node_modules/
editor-web/dist/
```

**Wake word models**: `.onnx` files are in `temp/wakeword/`. Path configured in `settings.yaml`. Not committed to git.

**.env**: Contains Gemini API keys (primary + fallback) and Spotify credentials. Never commit.

---

## Open Questions

1. Does the Gemini Live API voice quality satisfy the use case, or is a TTS swap needed? — *Deferred: evaluate with first full end-to-end test on hardware.*
2. Should the visualizer support multiple simultaneous animation layers? — *Deferred to v1.5.*
3. GIF-to-WebP conversion quality: acceptable for all source files? — *Verified: acceptable via batch converter. Prefer WebP-native sources where possible.*
4. Contextual trigger patterns in `emotion_map.yaml` need a full pass after animation library migration is complete (tracked in dv-1tv).
