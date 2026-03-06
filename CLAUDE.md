# DV3 — Claude Code Project Rules

> Extends ~/.claude/CLAUDE.md (user-level rules always apply here too).
> Voice-activated home companion: wake word → Gemini Live API → emotion-tagged animated visualizer.

---

## STARTUP SEQUENCE

```bash
bd status 2>/dev/null || bd server start   # BEADS first, always
bd ready                                    # What needs doing
```

Do not ask "what should we work on?" — check BEADS and proceed.

---

## PROJECT STACK

- **Runtime**: Python 3.12, asyncio, Ubuntu/WSL2 on NUC
- **Web Editor**: React 18 + TypeScript + Tailwind + Vite (`editor-web/`) — PRIMARY EDITOR
- **Legacy Editor**: Pygame (`editor/`) — headless batch ops only via `converter.py`
- **Test framework**: pytest

---

## COMMANDS

```bash
# Companion
python main.py                              # run companion
python main.py --debug                      # verbose logging
python main.py --windowed                   # no fullscreen

# Web editor (PRIMARY)
cd editor-web && npm run dev               # dev server → http://localhost:5173
cd editor-web && npm run build             # production build
cd editor-web && npm run typecheck         # TS check (no emit)
cd editor-web && npm run lint              # ESLint

# Legacy editor (batch ops only)
python -m editor.main                      # Pygame editor
python -m editor.converter                 # headless batch conversion

# Tests
pytest tests/                              # all tests
pytest tests/test_emotion_parser.py -v     # specific suite
pytest tests/test_emotion_parser.py::TestParseTag::test_basic_tag  # single test

# BEADS
bd ready                                   # ready tasks
bd create "Title" -p 1                     # new task
bd update <id> --claim                     # claim it
bd update <id> --status done               # only after testing passes
```

---

## ARCHITECTURE

**Single process, asyncio event loop.** Pygame render loop in main thread; background tasks yield via `await asyncio.sleep(0)`.

**State machine:** `IDLE → LISTENING → CONVERSATION → IDLE`

**Voice pipeline** (`core/voice_pipeline/base.py`): Abstract `VoicePipelineBase` + `ToolCallRequest`. Concrete backends (`gemini_live`, `modular`) selected in `main.py` via `settings.yaml`. Nothing imports implementations except `main.py`.

**Communication**: Three asyncio.Queue channels — `emotion_queue` (str), `tool_queue` (ToolCallRequest), `text_queue` (str). `_InlineEmotionAdapter` wraps `EmotionParser` with sync `feed()/reset()` API.

**Emotion detection cascade** (`core/emotion_parser.py`):
1. Contextual triggers — pattern match against `emotion_map.yaml`
2. Regex tag — `[emotion]` in first 30 tokens of Gemini response
3. Keyword fallback — sentiment keywords from `emotion_map.yaml`
4. Default — `"neutral"`

**Animation engine** (`visualizer/animation_engine.py`): Loads WebP/GIF via Pillow, Pygame surfaces with look-ahead cache, crossfade transitions.

**Tool dispatch** (`tools/tool_dispatcher.py`): Routes Gemini function calls to handlers (Spotify, timer, system). Failed tools gracefully disabled.

**Web Editor** (`editor-web/`) — PRIMARY EDITOR. Replaced previous web editor build.
- **State**: IndexedDB (`lib/db.ts`) — persists across sessions
- **Export**: FFmpeg WASM (`@ffmpeg/ffmpeg`) — fully in-browser, no server
- **Edit stack**: Non-destructive undo/redo, edits stored as action history
- **Asset model**: `emotion`, `context`, `title`, `notes`, `editStack`, `historyIndex`, `linkedVariantId`
- **Features**: brightness/contrast/hue/saturation, flip H/V, crop-to-square, vignette bake, speed/reverse, batch rename, batch export, compare mode, DV3 preview mode
- **Export path**: `{exportRoot}/emotions/{emotion}/` or `{exportRoot}/contextual/{context}/`
- **Components**: `GalleryPanel`, `TopToolbar`, `EditorPanel`, `SettingsModal`, `ErrorBoundary`

**Legacy Editor** (`editor/`) — HEADLESS BATCH OPS ONLY. Pygame, destructive edits. Do not use for new editor work — all animation asset editing happens in `editor-web/`. The only valid use is `converter.py` for headless batch WebP conversion.

---

## KEY PATTERNS

- **Audio in WSL2**: `sounddevice` (not PyAudio), PulseAudio over ALSA, threaded stream open with timeout
- **Config**: `.env` for user-specific, `config/settings.yaml` for app config, `config/emotion_map.yaml` for emotion mapping
- **Animation resolution**: `EmotionMapper` → directory from `emotion_map.yaml` with fallback chains (e.g. `excited → happy → neutral`), random file selection within directory

---

## TESTING — NOTHING IS DONE UNTIL TESTED

### Available tools — use them, in this order

**For web editor UI (`editor-web/`):**
1. **Playwright** (`/playwright-skill`) — navigate to http://localhost:5173, interact, screenshot, assert
   - `browser_navigate` → `browser_snapshot` → `browser_take_screenshot` → `browser_click` → `browser_evaluate`
   - Must confirm: gallery renders, asset selection works, edits apply, export triggers
2. **MCP_DOCKER browser tools** — fallback if Playwright unavailable
3. **`npm run typecheck`** via Bash — catches TS errors before runtime
4. **`npm run lint`** via Bash — catches code quality issues

**For Python companion / backend:**
1. **Bash** — run pytest, capture full output, paste summary line
2. **ssh-mcp** (`shawn@nuc-wsl`) — run processes, tail logs, check service health
3. **WebFetch / curl** — hit any HTTP endpoints

**For visual output (Pygame window, animations):**
1. Launch via Bash: `python main.py --windowed --debug`
2. Tail logs via ssh-mcp to confirm pipeline stages fired
3. Verify log output shows: wake word → session → text → emotion → animation

### UI testing — Claude Code tests it, not Shawn Paul

Never ask Shawn Paul to open a browser, click something, or verify UI.
Use Playwright. If Playwright is broken, use MCP_DOCKER browser tools.
If both are broken, say so explicitly with the error — then test everything else that isn't blocked.

Required Playwright checklist for every web editor change:
- [ ] `npm run dev` is running (start it via Bash if not)
- [ ] Navigate to http://localhost:5173
- [ ] Screenshot the initial state
- [ ] Perform the feature action
- [ ] Screenshot the result
- [ ] Assert expected outcome is present
- [ ] Test at least one error/edge case

### Completion criteria — ALL must pass before `bd update --status done`

- [ ] Relevant pytest suite run via Bash — paste the summary line (X passed, 0 failed)
- [ ] For web editor features: Playwright test run, screenshot taken, outcome confirmed
- [ ] For visual features: screenshot or log output pasted as evidence
- [ ] For file output features: file existence + nonzero size confirmed via Bash
- [ ] BEADS task updated

### Test matrix by feature type

**Web editor (any change):**
- `npm run typecheck` — zero errors
- `npm run lint` — zero warnings
- Playwright: navigate, interact with the changed feature, screenshot before/after

**Emotion parser:**
- `pytest tests/test_emotion_parser.py -v` — all pass, paste output

**Wake word:**
- Play audio sample from `temp/` through pipeline via Bash
- Confirm detection log line in output

**Gemini Live / conversation:**
- `python main.py --debug` via Bash
- Confirm in log: wake word → session start → text response → emotion parsed → animation triggered
- Each stage must appear. Missing stages = broken.

**Animation / visualizer:**
- `python main.py --windowed` via Bash
- Screenshot via Playwright or MCP browser (if windowed and accessible)
- Confirm animation playing — not black screen, not frozen frame

**Spotify:**
- Trigger play via tool dispatcher
- Hit Spotify `currently_playing` API endpoint via WebFetch
- Paste response confirming correct track

**Timer:**
- Set 10-second timer, wait, confirm alert fires in log
- Test two concurrent timers — both must fire at correct times

**Batch conversion:**
- Run converter on `temp_images/` via Bash
- Confirm every GIF produced a `.webp` — all nonzero size

### Banned phrases — if you're about to write one of these, go run the test first

- "should work"
- "appears to be working"
- "the implementation is complete"
- "tested successfully" (without pasted output or screenshot)
- "verified" (without pasted output or screenshot)
- "I believe this is correct"
- "this looks right"

### When a test fails

Fix it. Re-run. Do not move on. Do not say "this can be addressed later."
If genuinely blocked: state it explicitly with what you tried and what you need.

---

## AVAILABLE TOOLS & SKILLS

Use these actively. Don't default to basic Bash when a better tool exists.

| Tool / Skill | When to use |
|---|---|
| `/playwright-skill` | All web editor UI testing — primary tool |
| `browser_*` (MCP_DOCKER) | Playwright fallback |
| `ssh-mcp` (`shawn@nuc-wsl`) | Run processes, tail logs, check services in WSL |
| `systematic-debugging` skill | Hard bugs — structured approach before guessing |
| `test-driven-development` skill | New modules — write tests first |
| `dispatching-parallel-agents` skill | Independent work tracks — run simultaneously |
| `requesting-code-review` skill | Before marking features complete |
| `verification-before-completion` skill | Final check before marking done |
| `/mem-search` | Check if this problem was solved before |
| `/deep-plan` | Before tackling large features |
| `writing-plans` skill | Multi-step implementation plans |
| Notion MCP | Check/update project docs |
| `/commit-push-pr` | When feature is complete AND tested |
| `/simplify` | After implementation — clean up |
| `WebFetch` | Spotify API, health checks, external endpoints |

---

## PROACTIVE BEHAVIOR

1. Check `bd ready` before asking for direction
2. If blocked, try 2 alternatives before surfacing to Shawn Paul
3. Parallelize independent work tracks with subagents
4. Update BEADS tasks to reflect current state before ending session
5. Commit WIP to a branch — never leave uncommitted work stranded

---

## SECURITY

- NEVER commit `.env` or API keys
- NEVER hardcode device names, account IDs, personal data
- Wake word model paths via `settings.yaml` only
- Prefer WebP over GIF for animations
- The Pygame editor (`editor/`) is legacy. All new editor work happens in `editor-web/`
