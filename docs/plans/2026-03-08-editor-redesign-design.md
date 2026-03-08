# DV3 Editor Redesign — Design Document
**Date:** 2026-03-08
**Status:** Approved

---

## Overview

Redesign the web editor (`editor-web/`) to support a proper inbox-to-library workflow. Animations are imported, edited, tagged, and baked (destructive save) into a flat library. The Pygame visualizer switches from folder-based lookup to manifest-based lookup. `emotion_map.yaml` is deprecated.

---

## 1. Data Model & File Layout

### File system
```
data/animations/
  inbox/              ← raw imports, not yet tagged or baked
  manifest.json       ← single source of truth for all tagged animations
  b10_alert.webp      ← baked, tagged animations (flat directory)
  floyd_prism.webp
  neutral_idle.webp
  ...
```

All tagged animations live flat in `data/animations/`. Folder location is irrelevant — only the manifest matters. No `emotions/`, `contextual/`, `dark/`, or `light/` subdirectories.

### Manifest entry schema
```json
{
  "file": "floyd_prism.webp",
  "theme": "dark",
  "emotions": ["calm", "thinking"],
  "states": [],
  "tags": ["music", "pink_floyd", "psychedelic"],
  "title": "Pink Floyd prism",
  "notes": ""
}
```

| Field | Type | Notes |
|-------|------|-------|
| `file` | string | Filename only (no path), relative to `data/animations/` |
| `theme` | `"dark" \| "light" \| "both"` | Structured field, not a free-form tag |
| `emotions` | string[] | Predefined emotion set (happy, sad, alert, etc.) |
| `states` | string[] | Predefined state set (idle, listening, processing, etc.) |
| `tags` | string[] | Free-form custom triggers (music, pink_floyd, lights_on, etc.) |
| `title` | string | Human-readable label |
| `notes` | string | Optional notes |

### Tag groups
- **Emotions** — predefined set matching the companion's emotion parser output
- **States** — predefined set matching the companion's state machine (idle, listening, processing, thinking)
- **Tags** — free-form, used for contextual matching (music genres, smart home events, etc.)
- **Theme** — `dark` / `light` / `both` — structured toggle, not a tag

---

## 2. UI Layout

Three-panel layout. Sidebar widens to 380px. Tag panel added on the right.

```
┌─────────────────┬──────────────────────────────┬──────────────────┐
│ SIDEBAR (380px) │     EDITOR CANVAS            │  TAG PANEL       │
│                 │                              │  (320px)         │
│ [Inbox] [Lib]   │   animation preview          │                  │
│                 │   (centered, checkerboard)   │  ┌─ EMOTIONS ──┐ │
│ ┌─ inbox tab ─┐ │                              │  │ □ happy      │ │
│ │ thumbnail   │ │                              │  │ □ sad        │ │
│ │ thumbnail   │ ├──────────────────────────────┤  │ ☑ alert      │ │
│ └─────────────┘ │   EDIT CONTROLS              │  └─────────────┘ │
│                 │   brightness/contrast/flip/  │  ┌─ STATES ───┐ │
│                 │   speed/crop/hue/sat/etc      │  │ □ idle      │ │
│                 │                              │  │ □ listening │ │
│                 │                              │  └─────────────┘ │
│                 │                              │  ┌─ TAGS ─────┐ │
│                 │                              │  │ music  ×    │ │
│                 │                              │  │ + add tag   │ │
│                 │                              │  └─────────────┘ │
│                 │                              │  Filename: [___] │
│                 │                              │  Theme: ● dark   │
│                 │                              │         ○ light  │
│                 │                              │  [    SAVE    ]  │
└─────────────────┴──────────────────────────────┴──────────────────┘
```

### Sidebar tabs
- **Inbox tab** — shows files in `data/animations/inbox/` on disk. Badge count shows pending items.
- **Library tab** — shows all entries in `manifest.json`. Filterable by emotion/state/tag/theme.

### Tag panel
- Replaces the current right-side metadata panel
- Emotion checkboxes (predefined list, multi-select)
- State checkboxes (predefined list, multi-select)
- Custom tag chips with free-text input (type + Enter to add)
- Filename text field
- Dark / Light / Both theme toggle
- **Save button** — prominent, disabled until filename is set and at least one emotion or state is checked

### Edit controls
- Stay below the canvas (unchanged from current layout)
- Brightness, contrast, hue, saturation, flip H/V, speed, reverse, crop-to-square, padding/zoom, vignette

---

## 3. Workflow

### Import
1. Click **Import** in the Inbox tab header
2. File picker opens — accepts `.webp` and `.gif`
3. **WebP**: copied directly to `data/animations/inbox/` via File System Access API
4. **GIF**: auto-converted to WebP using FFmpeg WASM (progress shown inline), saved to `inbox/`. Original GIF not kept.
5. No manual convert step — conversion is automatic on import.

### Edit → Tag → Save
1. Click inbox thumbnail → loads into editor canvas, clears tag panel
2. Apply edits (live preview, non-destructive during editing session)
3. In tag panel: check emotions/states, add custom tags, set filename, pick theme
4. Click **Save**:
   - FFmpeg WASM bakes edits into a new WebP
   - File written to `data/animations/{filename}.webp` via File System Access API
   - `manifest.json` updated with new entry
   - Original deleted from `inbox/`
   - Thumbnail moves from Inbox tab to Library tab
5. If save fails: inbox file preserved, manifest not updated — no data loss

### Re-edit from Library
1. Click any Library thumbnail → loads baked file into editor (no edit history — it's baked)
2. Tags and filename pre-populated from manifest
3. Edit, retag, rename → Save → overwrites file in `data/animations/`, updates manifest entry

### Crash / close before save
- Inbox files live on disk — they're still there next session. Nothing lost.

---

## 4. Visualizer Changes

### EmotionMapper — manifest-only
- Loads `data/animations/manifest.json` at startup
- Builds index: `emotion → [file paths]`, `state → [file paths]`, filterable by theme
- No directory scanning, no `emotion_map.yaml`

### Query signature
```python
get_animation_path(emotion: str, theme: str = 'dark') -> str | None
```
- Finds all manifest entries where `emotion` is in `emotions` AND `theme` in (`entry.theme`, `'both'`)
- Picks random from matches
- Falls back to `neutral` entries → then any `dark` entry → then `None` (logged as warning)

### Theme
- Companion defaults to `dark` (configured in `settings.yaml`)
- Entries tagged `both` match either theme query
- Theme-switching (time of day, command) is out of scope — future task

### No manifest present
- Companion logs a warning and plays nothing rather than crashing
- Fix: run migration script

### Migration
- Move all files from `data/animations/emotions/*/` and `data/animations/contextual/*/` to `data/animations/inbox/`
- Remove now-empty subdirectories
- No manifest entries generated — user tags everything through the editor
- `emotion_map.yaml` deprecated (kept in repo temporarily, ignored at runtime)

---

## 5. Out of Scope (future tasks)
- Theme-switching at runtime based on time of day or voice command
- Light theme animation creation workflow
- Hot-reload of manifest without companion restart
- Inbox visible from outside the browser (e.g. drag files in via file manager)
- Multi-select bulk tagging in inbox

---

## Affected Files

| File | Change |
|------|--------|
| `editor-web/src/App.tsx` | New state model, import/save flow, tab switching |
| `editor-web/src/components/GalleryPanel.tsx` | Replace with tabbed Inbox/Library sidebar |
| `editor-web/src/components/TagPanel.tsx` | New component — emotions, states, tags, save |
| `editor-web/src/components/TopToolbar.tsx` | Remove export/status indicators (replaced by Save) |
| `editor-web/src/components/SettingsModal.tsx` | Minimal changes |
| `editor-web/src/lib/db.ts` | Update asset model, remove old export tracking |
| `editor-web/src/lib/exportUtils.ts` | Rename/repurpose as `bakeUtils.ts` — bake + write to library |
| `editor-web/src/types.ts` | New `InboxItem`, `LibraryAsset` types replacing `Asset` |
| `visualizer/emotion_map.py` | Rewrite to manifest-only |
| `config/emotion_map.yaml` | Deprecated |
| `main.py` | Load manifest on startup |
| `scripts/migrate_to_inbox.py` | One-time migration script |
