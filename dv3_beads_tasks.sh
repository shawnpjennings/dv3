#!/usr/bin/env bash
# DV3 BEADS Task Creation Script
# Run from ~/projects/dv3/
# Creates all PRD tasks with verification requirements.
# Nothing marked complete without tests.

set -e
cd ~/projects/dv3

echo "=== Cleaning up junk test tasks ==="
bd delete dv-7l8 2>/dev/null || true
bd delete dv-7fq 2>/dev/null || true
bd delete dv-kly 2>/dev/null || true
bd delete dv-2zg 2>/dev/null || true

echo "=== VOICE PIPELINE ==="

bd create --type task -p 1 \
  --title "REQ-01: OpenWakeWord gate with configurable model path" \
  --description "Implement OpenWakeWord gate. Model file path loaded from settings.yaml, never hardcoded. Wake word detection triggers Gemini Live session to begin receiving audio." \
  --acceptance "VERIFY: Run scripts/test_wake_word.py. Speak wake word. Confirm in console output that session was triggered within 500ms. Paste terminal output as evidence. No pass without log."

bd create --type task -p 1 \
  --title "REQ-02: Gemini Live API WebSocket session (VAD/STT/LLM/TTS)" \
  --description "Gemini Live API (gemini-2.5-flash-native-audio-latest) handles VAD, STT, LLM, and TTS in single persistent WebSocket session via native google-genai Python SDK." \
  --acceptance "VERIFY: Run scripts/test_gemini_live.py. Confirm text response printed to console within 1500ms of wake word. Paste terminal output as evidence. No pass without log."

bd create --type task -p 1 \
  --title "REQ-03: Audio input — PCM 16kHz mono 16-bit via sounddevice" \
  --description "Audio input captured as PCM 16kHz mono 16-bit from default mic device (configurable in settings.yaml). Uses sounddevice library with PulseAudio bridge per thumper project approach." \
  --acceptance "VERIFY: Run scripts/test_audio_io.py. Confirm sounddevice opens mic successfully, prints device info and sample rate. Paste output as evidence."

bd create --type task -p 1 \
  --title "REQ-04: Audio output — stream Gemini TTS to speakers" \
  --description "Stream Gemini audio response to speakers with minimal buffering. Audio begins playing as chunks arrive, not after full response." \
  --acceptance "VERIFY: Trigger a response. Confirm audio plays. Record subjective latency. Confirm streaming (not batched) by checking audio starts before full response completes."

bd create --type task -p 1 \
  --title "REQ-05: Session reconnection with exponential backoff" \
  --description "If WebSocket drops, automatically attempt reconnect with exponential backoff, max 5 retries. Log the failure. Resume from neutral state after reconnect." \
  --acceptance "VERIFY: Run scripts/test_reconnect.py which kills the WebSocket mid-session. Confirm reconnect attempt logged, reconnect succeeds within 10 seconds. Paste log output."

bd create --type task -p 1 \
  --title "REQ-06: API key fallback on 429 rate limit" \
  --description "Primary and secondary Google API keys configurable in .env. On 429 rate limit error, automatically switch to fallback key and reconnect. No user action required." \
  --acceptance "VERIFY: Simulate 429 by temporarily invalidating primary key. Confirm system switches to fallback key automatically. Paste log output showing key switch."

bd create --type task -p 1 \
  --title "REQ-07: WSL2 audio — sounddevice + PulseAudio bridge" \
  --description "WSL2 audio uses sounddevice (not PyAudio) with PulseAudio bridge. Match approach in ~/projects/thumper/. Confirm mic and speaker work before any other audio work proceeds." \
  --acceptance "VERIFY: Run scripts/test_audio_io.py. Confirm sounddevice opens both mic and speakers without errors. Paste output. This gate must pass before REQ-03 or REQ-04 are marked complete."

echo "=== EMOTION SYSTEM ==="

bd create --type task -p 1 \
  --title "REQ-08: Gemini system prompt with bracketed emotion tags" \
  --description "Gemini instructed via system prompt to begin every text response with a bracketed emotion tag. Tag list: [excited][happy][sad][thinking][confused][laughing][surprised][calm][alert][tired][sarcastic][neutral][curious][proud][concerned][angry][roast]. Tag must be the very first content in the text stream." \
  --acceptance "VERIFY: Run pytest tests/test_emotion_system_prompt.py. Send 5 varied prompts, confirm every response begins with a valid bracketed tag. All assertions pass. Paste test output."

bd create --type task -p 1 \
  --title "REQ-09: Emotion parser — buffer 30 tokens, regex extract, fire event" \
  --description "Emotion parser buffers first 30 tokens of text stream. Extracts tag via regex \\[(\\w+)\\]. Fires visualizer event immediately on detection. Strips tag from any displayed text." \
  --acceptance "VERIFY: Run pytest tests/test_emotion_parser.py -v. All test cases pass: tag present, tag absent, tag in wrong position, malformed tag. Paste output."

bd create --type task -p 1 \
  --title "REQ-10: Emotion keyword fallback when no tag detected" \
  --description "If no tag detected in first 30 tokens, run keyword fallback on text stream. Rules: exclamation marks -> excited, 'hmm'/'interesting' -> thinking, 'sorry'/'unfortunately' -> concerned, etc." \
  --acceptance "VERIFY: pytest tests/test_emotion_parser.py — keyword fallback test cases all pass. Paste output."

bd create --type task -p 1 \
  --title "REQ-11: Default to [neutral] if no emotion detected" \
  --description "If neither regex tag extraction nor keyword fallback detects an emotion, default to [neutral] and trigger neutral animation." \
  --acceptance "VERIFY: pytest tests/test_emotion_parser.py — neutral fallback test case passes. Paste output."

bd create --type task -p 1 \
  --title "REQ-12: Contextual keyword detection on user speech in real-time" \
  --description "Contextual keyword detection runs on the user's transcribed speech in real time, NOT only on Gemini's response. Fires contextual animation immediately, before Gemini reply arrives. Gemini text still parsed for emotion tags in parallel." \
  --acceptance "VERIFY: Speak a phrase containing a contextual keyword (e.g. 'play Pink Floyd'). Confirm contextual animation fires BEFORE any audio response from Gemini. Log timestamp of speech transcription vs animation trigger vs audio start. Animation must fire first."

bd create --type task -p 1 \
  --title "REQ-13: Contextual triggers override emotion — priority system" \
  --description "Contextual keyword triggers override emotion triggers. Priority order: contextual > emotion > neutral. Defined in emotion_map.yaml with pattern lists, durations, and priorities." \
  --acceptance "VERIFY: pytest tests/test_emotion_parser.py — priority override test cases pass. Also manual test: speak contextual keyword mid-emotion sequence, confirm correct override behavior. Paste test output."

echo "=== VISUALIZER ==="

bd create --type task -p 1 \
  --title "REQ-14: Fullscreen Pygame window, black background" \
  --description "Fullscreen Pygame window on primary display. Background is pure black. Window must be fullscreen, not windowed." \
  --acceptance "VERIFY: Launch visualizer. Take screenshot via scrot or similar. Confirm fullscreen black background. Paste screenshot filename and confirm it was checked."

bd create --type task -p 1 \
  --title "REQ-15: Resolution-agnostic display, 65% height, centered, aspect preserved" \
  --description "Query display resolution at startup. Animation area sized at 65% of screen height by default, centered, native aspect ratio preserved. No hardcoded pixel values." \
  --acceptance "VERIFY: Launch on two different resolutions if possible, or change resolution in settings.yaml and relaunch. Confirm animation area scales proportionally. Screenshot as evidence."

bd create --type task -p 2 \
  --title "REQ-16: Animation area size/position configurable via settings.yaml" \
  --description "Animation area dimensions and screen position are configurable in settings.yaml at runtime. Changes take effect on next launch." \
  --acceptance "VERIFY: Edit settings.yaml to change size percentage and position. Relaunch. Confirm changes reflected visually. Screenshot before/after."

bd create --type task -p 1 \
  --title "REQ-17: Animated WebP primary format, GIF fallback" \
  --description "Animated WebP files are primary playback format. GIF playback also supported natively as fallback for unconverted files. Both formats must play correctly in the visualizer." \
  --acceptance "VERIFY: Launch visualizer with a WebP file. Confirm animation plays. Launch with a GIF file. Confirm animation plays. Screenshot or screen capture as evidence."

bd create --type task -p 1 \
  --title "REQ-18: Radial black gradient mask over animation area" \
  --description "Radial black gradient mask applied over animation area, fading edges to black. Opacity adjustable 0-100%. Size (inward extent of gradient) adjustable as percentage of animation area. Both adjustable in settings.yaml. Animation appears to float in black space with no visible hard edge." \
  --acceptance "VERIFY: Launch visualizer with gradient enabled. Screenshot must show no hard rectangular border around animation — edges must fade to black. Test opacity 0 (no fade) and opacity 100 (heavy fade). Screenshot both states as evidence."

bd create --type task -p 2 \
  --title "REQ-18b: Ctrl+Shift+V opens visualizer settings panel" \
  --description "Runtime keyboard shortcut Ctrl+Shift+V opens an overlay settings panel inside the Pygame window. Panel allows adjusting gradient opacity, gradient size, and crossfade duration without restarting." \
  --acceptance "VERIFY: Launch visualizer. Press Ctrl+Shift+V. Confirm settings panel opens. Adjust gradient opacity slider. Confirm gradient changes in real time. Screenshot panel open as evidence."

bd create --type task -p 1 \
  --title "REQ-19: Crossfade transition between animations, 300ms default" \
  --description "Alpha blend crossfade between animations when emotion changes. Duration configurable (default 300ms). Transition must be smooth with no visible stutter." \
  --acceptance "VERIFY: Launch visualizer. Programmatically emit a sequence of 5 emotion changes via the asyncio queue. Record screen or observe: crossfade must be visible and smooth at 60fps. No stutter. Log FPS during transitions."

bd create --type task -p 1 \
  --title "REQ-20: Random animation selection from manifest.json tagged set" \
  --description "Animation selected randomly from the set of assets tagged with the matching emotion in manifest.json. Not random from a directory — must use manifest." \
  --acceptance "VERIFY: Run test that emits the same emotion 10 times. Confirm at least 2 different animations were selected from the tagged set. Paste test output."

bd create --type task -p 1 \
  --title "REQ-21: Seamless animation looping" \
  --description "Animations loop seamlessly. First and last frame must not produce a visible jump on loop. Loop continues until emotion change or contextual trigger." \
  --acceptance "VERIFY: Launch visualizer with a test animation. Observe 3+ loop cycles visually. No visible jump at loop point. Note: animations in the library should be verified to be true seamless loops during editor workflow."

bd create --type task -p 1 \
  --title "REQ-22: 60fps playback with 30-frame pre-cache" \
  --description "Target 60fps animation playback. Pre-cache next 30 frames during playback to prevent frame drops. Log FPS during testing." \
  --acceptance "VERIFY: Launch visualizer. Run scripts/test_visualizer_fps.py which measures FPS over 30 seconds. Must maintain 55+ fps average with no drops below 40. Paste FPS log."

bd create --type task -p 1 \
  --title "REQ-23: Contextual animations play for configured duration then return" \
  --description "Contextual animations (triggered by keyword match) play for a configured duration (set in emotion_map.yaml per trigger), then return to emotion-based animation automatically." \
  --acceptance "VERIFY: Trigger a contextual animation. Confirm it plays for the correct duration. Confirm system returns to emotion-based animation after. Log timestamps as evidence."

echo "=== TOOLS ==="

bd create --type task -p 1 \
  --title "REQ-24: Spotify tool — play/pause/skip/volume/search via spotipy" \
  --description "Spotify control: play, pause, skip, previous, volume, search by track/artist/album, get now playing. Uses spotipy library with OAuth. Credentials in .env only, never in source or config committed to git." \
  --acceptance "VERIFY: Run scripts/test_spotify_tool.py. Execute play command. Confirm via Spotify API currently_playing endpoint that correct track is playing within 2 seconds. Paste API response as evidence."

bd create --type task -p 1 \
  --title "REQ-24b: Spotify triggers contextual animations on music keywords" \
  --description "Spotify tool calls and artist/track names in speech trigger contextual animations. e.g. 'play Pink Floyd' triggers Pink Floyd animation. Requires REQ-12 and REQ-24 complete." \
  --acceptance "VERIFY: Say 'play [artist name]'. Confirm animation matching that artist/genre fires immediately on speech detection. Confirm Spotify also starts playing. Screenshot or log as evidence."

bd create --type task -p 1 \
  --title "REQ-25: Web search via Gemini built-in Google Search grounding" \
  --description "Web search uses Gemini Live API built-in google_search grounding tool declared in setup config. No external search API or additional library needed." \
  --acceptance "VERIFY: Ask DV3 a question requiring current information (e.g. 'what's the weather today'). Confirm Gemini uses search grounding and returns a current answer. Log the tool_call event confirming google_search was invoked."

bd create --type task -p 1 \
  --title "REQ-26: Timer tool — set by duration, audio alert, TTS, concurrent" \
  --description "Set a timer by duration ('set a 10 minute timer'). On completion: play audio alert and announce via TTS. Multiple concurrent timers supported." \
  --acceptance "VERIFY: Set a 10-second timer. Confirm audio alert fires at correct time (+/- 1 second). Set two concurrent timers (15s and 20s). Confirm both fire at correct times independently. Log timestamps."

bd create --type task -p 1 \
  --title "REQ-27: Time/date tool — native Python, no API" \
  --description "Return current time and date using native Python (datetime module). No external API. Included as Gemini function_declaration." \
  --acceptance "VERIFY: Ask DV3 'what time is it'. Confirm correct time returned. Run pytest tests/test_system_tools.py. All assertions pass."

echo "=== GEMINI TOOL CALLING ==="

bd create --type task -p 1 \
  --title "REQ-28: Tools declared as function_declarations in Live API setup config" \
  --description "All tools (Spotify, timer, time/date, search) declared as function_declarations in Gemini Live API setup config. Tool calls come as mid-stream WebSocket messages. Code executes function and returns tool_response. Gemini resumes audio output after result." \
  --acceptance "VERIFY: Trigger a tool call (e.g. ask for time). Inspect logs to confirm tool_call message received mid-stream, tool_response sent, audio resumed. Paste log excerpt showing the tool_call -> execute -> tool_response -> audio flow."

bd create --type task -p 1 \
  --title "REQ-29: Tool execution is async and non-blocking" \
  --description "Tool execution must not block the audio stream. Audio stream continues (or pauses gracefully) while tool executes. No freezing or stalling of the voice pipeline during tool calls." \
  --acceptance "VERIFY: Trigger a tool call that has a measurable delay (e.g. Spotify search). Confirm voice pipeline does not freeze. Log tool execution time vs audio stream continuity."

echo "=== DV3 EDITOR ==="

bd create --type task -p 1 \
  --title "REQ-30: DV3 Editor — React/TS/Vite app at localhost:5173" \
  --description "Browser-based editor at editor-web/. Runs via npm run dev at http://localhost:5173. React + TypeScript + Vite stack." \
  --acceptance "VERIFY: npm run dev in editor-web/. Playwright navigates to localhost:5173. Confirm app loads without errors. Playwright screenshot as evidence."

bd create --type task -p 1 \
  --title "REQ-31: Editor — IndexedDB persistence (DV3EditorDB)" \
  --description "All asset data persisted in browser IndexedDB (DV3EditorDB). No server required. Data survives page reload." \
  --acceptance "VERIFY: Playwright: import a file, reload page, confirm file still present in gallery. Pass only if data survives reload. Playwright test output as evidence."

bd create --type task -p 1 \
  --title "REQ-32: Editor — File upload via File System Access API to inbox/" \
  --description "Upload GIF, WebP, PNG, JPG via File System Access API. Files copied to data/animations/inbox/ on the filesystem." \
  --acceptance "VERIFY: Playwright: trigger file import of a test GIF. Confirm file appears in data/animations/inbox/ on filesystem. Playwright + filesystem check as evidence."

bd create --type task -p 1 \
  --title "REQ-33: Editor — Non-destructive edit stack" \
  --description "All adjustments stored per-asset as an edit stack. Original file is never modified. Save = FFmpeg WASM render with all edits applied to produce final WebP." \
  --acceptance "VERIFY: Import a file. Apply edits. Confirm original file in inbox/ is unchanged. Save. Confirm baked WebP in library/ is different from original. Playwright + file hash comparison as evidence."

bd create --type task -p 1 \
  --title "REQ-34: Editor — Full edit tool suite" \
  --description "Edit tools: Flip H/V, Size/Zoom, Position X/Y, Outfill background color, Crop to square, Circle mask, Brightness, Contrast, Hue, Saturation, Grayscale, Invert, Vignette, Background swap (beta), Speed multiplier (0.1x-4x), Reverse frames. All tools apply across all frames of animated files." \
  --acceptance "VERIFY: Playwright: apply each edit tool to a test animation. Confirm each tool produces a visible change in the preview. Save and confirm the baked WebP reflects the edits. Playwright screenshots per tool as evidence."

bd create --type task -p 1 \
  --title "REQ-35: Editor — Multi-select (Shift+click range, Ctrl+click toggle), batch export, batch rename" \
  --description "Multi-selection with Shift+click for range and Ctrl+click for toggle. Batch export and batch rename operations apply to all selected items." \
  --acceptance "VERIFY: Playwright: import 3+ files. Shift+click to range-select. Confirm all selected. Ctrl+click to deselect one. Confirm selection. Trigger batch export. Confirm ZIP contains correct files. Playwright test output."

bd create --type task -p 1 \
  --title "REQ-36: Editor — Asset tagging (emotions, states, tags, theme, title, notes)" \
  --description "Each asset tagged with: emotions (primary + additional), states, custom tags, theme (dark/light/both), title, notes. Tags drive DV3 animation routing via manifest.json." \
  --acceptance "VERIFY: Playwright: import a file. Open TagPanel. Set primary emotion, add a state, add custom tag, set theme. Save. Open manifest.json. Confirm all tags present in the manifest entry. File content check as evidence."

bd create --type task -p 1 \
  --title "REQ-37: Editor — Save bakes via FFmpeg WASM, writes to library/, updates manifest.json" \
  --description "Save bakes edits via FFmpeg WASM. Writes final WebP to data/animations/library/. Updates manifest.json with asset metadata. This is the core output pipeline." \
  --acceptance "VERIFY: Playwright: import file, apply at least one edit, add tags, save. Confirm: (1) WebP exists in library/, (2) manifest.json updated with correct entry including filename and tags, (3) baked file differs from original. All three checks must pass."

bd create --type task -p 1 \
  --title "REQ-38: Editor — Library tab: browse, re-edit, duplicate, remove saved assets" \
  --description "Library tab shows all saved (baked) assets. User can select a saved asset, re-edit it (loads baked file with pre-populated tags), duplicate it, or remove it." \
  --acceptance "VERIFY: Playwright: save an asset. Switch to Library tab. Confirm asset appears. Click re-edit. Confirm tags pre-populated. Confirm edit controls load correctly. Playwright screenshot as evidence."

bd create --type task -p 1 \
  --title "REQ-39: Editor — ZIP export of full library + manifest.json" \
  --description "Export produces a ZIP file containing all library WebPs and manifest.json. For backup or transfer to another machine." \
  --acceptance "VERIFY: Playwright: with 2+ assets in library, trigger export. Confirm ZIP download. Unzip and confirm WebP files and manifest.json present. Content check as evidence."

bd create --type task -p 2 \
  --title "REQ-40: Editor — Undo/redo with labeled buttons" \
  --description "Undo/redo history for edit actions. Undo and Redo text buttons (labeled with action name). State must revert/reapply correctly." \
  --acceptance "VERIFY: Playwright: apply 3 edits. Click Undo 3 times. Confirm state returns to original. Click Redo. Confirm edit reapplied. Playwright screenshot each state as evidence."

bd create --type task -p 2 \
  --title "REQ-41: Editor — Visualizer Preview mode (gradient mask preview)" \
  --description "Preview mode shows how the animation will look with the DV3 radial gradient mask applied. Allows user to check edge blending before saving." \
  --acceptance "VERIFY: Playwright: load an animation. Enable Visualizer Preview mode. Confirm gradient mask visible in preview panel. Playwright screenshot before/after toggle as evidence."

bd create --type task -p 2 \
  --title "REQ-42: Editor — Compare mode (side-by-side before/after)" \
  --description "Compare mode for side-by-side before/after view of edits applied vs original animation." \
  --acceptance "VERIFY: Playwright: import file, apply edits, open compare mode. Confirm two panels visible side by side. Playwright screenshot as evidence."

echo "=== ASSET MODEL & CONFIG ==="

bd create --type task -p 1 \
  --title "REQ-43: manifest.json as single source of truth, flat library/" \
  --description "manifest.json is the single source of truth for the animation library. All baked assets live flat in animations/library/, indexed by manifest. Old folder-based structure (emotions/, contextual/, states/) is deprecated." \
  --acceptance "VERIFY: Confirm manifest.json exists and is valid JSON. Confirm all library/ assets are referenced in manifest. Run scripts/validate_manifest.py. All assertions pass."

bd create --type task -p 1 \
  --title "REQ-44: EmotionMapper loads manifest.json at startup, queries by tag" \
  --description "EmotionMapper loads manifest.json at startup. Queries by emotion, state, or custom tag. Fallback chains defined in emotion_map.yaml (e.g. excited -> happy -> neutral)." \
  --acceptance "VERIFY: pytest tests/test_emotion_mapper.py -v. Test: query by emotion, query by state, fallback chain traversal, no-match case. All assertions pass. Paste output."

bd create --type task -p 1 \
  --title "REQ-45: Animation library migration — inbox/library workflow" \
  --description "Old folder-based structure (emotions/, contextual/, states/) migrated to inbox->library workflow via manifest.json. Run scripts/migrate_to_inbox.py to import old assets into inbox. Re-tag via DV3 Editor. Clean up old folder structure after migration confirmed." \
  --acceptance "VERIFY: Run migrate_to_inbox.py. Confirm all old assets appear in inbox/ and show in DV3 Editor gallery. Re-tag a sample. Confirm manifest.json updated. Old folder structure can then be archived."

bd create --type task -p 1 \
  --title "REQ-46: All config in settings.yaml; all secrets in .env only" \
  --description "All runtime values in settings.yaml. Sensitive values (API keys, credentials, device names, account IDs) in .env only. Nothing sensitive hardcoded in any source file, README, or documentation." \
  --acceptance "VERIFY: Run scripts/check_secrets.py which greps all source files for hardcoded keys/tokens/names. Must return zero matches. Paste output."

bd create --type task -p 1 \
  --title "REQ-47: emotion_map.yaml — all mappings, fallback chains, keyword triggers" \
  --description "emotion_map.yaml defines: all emotion/state/contextual trigger mappings, fallback chains per emotion, and keyword pattern lists for contextual triggers. This is the config layer for the EmotionMapper." \
  --acceptance "VERIFY: pytest tests/test_emotion_mapper.py — all 15+ emotions have fallback chains defined. All contextual trigger patterns match expected keywords. Run validate_emotion_map.py. No missing entries. Paste output."

echo "=== ACCEPTANCE CRITERIA (INTEGRATION TESTS) ==="

bd create --type task -p 1 \
  --title "AC-01: Wake word triggers Gemini session within 500ms" \
  --description "End-to-end timing test: speak wake word, measure time to Gemini Live session open. Must be under 500ms." \
  --acceptance "VERIFY: Run scripts/test_latency.py. Speak wake word 5 times. Log timestamps. All 5 must be under 500ms. Paste timing log."

bd create --type task -p 1 \
  --title "AC-02: First audio response within 1500ms of wake word" \
  --description "End-to-end latency: time from wake word detection to first audio output from Gemini. Must be under 1500ms on local network." \
  --acceptance "VERIFY: Run scripts/test_latency.py. Speak wake word and ask a short question. Measure time to first audio chunk. Must be under 1500ms. Paste timing log."

bd create --type task -p 1 \
  --title "AC-03: WebSocket reconnect within 10 seconds of drop" \
  --description "On WebSocket disconnect, system reconnects and is operational again within 10 seconds." \
  --acceptance "VERIFY: Run scripts/test_reconnect.py. Kill WebSocket mid-session. Confirm reconnect completes and system responds to voice within 10 seconds. Paste log with timestamps."

bd create --type task -p 1 \
  --title "AC-04: 429 fallback key switch requires no user action" \
  --description "On primary API key 429 response, system silently switches to fallback key and continues. No user intervention required." \
  --acceptance "VERIFY: Force 429 by depleting primary key quota or temporarily replacing it with an invalid key. Confirm automatic switch in logs. Confirm voice interaction continues without interruption. Paste log."

bd create --type task -p 1 \
  --title "AC-05: VAD interrupt tested with Shawn Paul" \
  --description "VAD interrupt (user speaks to interrupt DV3 while it is speaking) tested and working in live session with Shawn Paul." \
  --acceptance "VERIFY: Live test only. Shawn Paul speaks while DV3 is responding. DV3 must stop speaking within 500ms. Shawn Paul confirms in writing: 'VAD interrupt confirmed working [date]'."

bd create --type task -p 1 \
  --title "AC-06: Wake word tested with Shawn Paul in real conditions" \
  --description "Wake word detection tested in real home environment with Shawn Paul. Must work at normal speaking distance, normal home noise level." \
  --acceptance "VERIFY: Live test only. Shawn Paul speaks wake word from across the room. Must trigger within 500ms. Shawn Paul confirms in writing: 'Wake word confirmed working [date]'."

bd create --type task -p 1 \
  --title "AC-07: Emotion triggers visualizer before or as audio begins" \
  --description "Emotion tag detected in text stream and animation triggered before or simultaneously as audio output begins playing. Not after." \
  --acceptance "VERIFY: Run scripts/test_emotion_timing.py. Measure timestamp of animation trigger vs timestamp of first audio chunk. Animation must fire first or within 50ms of audio start. Paste timing log."

bd create --type task -p 1 \
  --title "AC-08: No sensitive values in source files or documentation" \
  --description "No personal names, account IDs, device names, API keys, or credentials appear in any source file, README, or documentation." \
  --acceptance "VERIFY: Run scripts/check_secrets.py. Must return zero matches. Also run: git log --all --oneline | xargs git show | grep -E '(sk-|AIza|secret|password)' to check git history. Paste both outputs."

echo ""
echo "=== DONE ==="
echo "All tasks created. Run 'bd list' to verify."
echo "Run 'bd ready' to see unblocked P1 tasks."
