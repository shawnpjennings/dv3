# DV3 Editor

Browser-based animation editor for the DV3 voice companion project. Handles the full pipeline from raw import through metadata tagging to baked, ready-to-use WebP animations.

Built with React + TypeScript + Vite. All data persists locally in IndexedDB. Export runs entirely in-browser via `ffmpeg.wasm` — no server required.

---

## DV3 Integration

DV3 Editor is the **primary tool** for building the DV3 animation library. It replaces the legacy Pygame editor (`editor/`), which is now restricted to headless batch GIF→WebP conversion only.

The editor manages the full asset lifecycle:

1. **Import** → raw files land in `data/animations/inbox/`
2. **Edit + Tag + Save** → baked WebP goes to `data/animations/library/`, entry added to `manifest.json`
3. The DV3 companion's `EmotionMapper` reads `manifest.json` at startup to route animations by emotion, state, and tag

---

## Workflow

### 1. Import

Click **Import** (top toolbar) to open a file picker. Accepts GIF, WebP, PNG, JPG.

Files are copied to `data/animations/inbox/` via the File System Access API. The browser prompts for folder permission the first time — grant it and the connection persists for the session. GIFs are converted to WebP during import.

Select a connected folder in **Settings** (gear icon) to set the export root. This determines where `library/` and `manifest.json` are written.

### 2. Edit

Select an asset from the Inbox gallery. Edit controls appear in the center panel:

**Tone & Filters**
- Brightness, Contrast, Hue, Saturation
- Grayscale, Invert

**Transform**
- Flip Horizontal / Vertical
- Size/Zoom, Position X/Y (move within canvas)
- Crop to Square
- Outfill Background (add padding around animation)

**Mask / Effects**
- Circle Mask (baked on export — converts to circular crop)
- Vignette

**Animation**
- Speed Multiplier (0.1x–4x)
- Reverse Frames

**Preview**
- Visualizer Preview — shows how the animation will look with DV3's radial gradient mask applied
- Compare Mode — side-by-side before/after

All edits are non-destructive. The original file is never modified. Edits are stored as an action stack in IndexedDB and baked by FFmpeg WASM only when you save.

### 3. Tag

In the **Tag Panel** (right sidebar), enter:

- **Emotions** — check all emotions this animation fits (e.g., happy, excited, curious)
- **States** — check applicable states (idle, listening, processing)
- **Tags** — freeform custom tags for contextual routing
- **Theme** — dark, light, or both
- **Title** — human-readable name
- **Notes** — any notes about the asset

Tags are what the DV3 companion uses to select the right animation at runtime.

### 4. Save

Click **SAVE** in the Tag Panel. This:

1. Bakes all edits via FFmpeg WASM into a final WebP
2. Writes the WebP to `data/animations/library/`
3. Updates `data/animations/manifest.json` with the asset's full metadata

### 5. Library

Switch to the **Library** tab (left sidebar) to see all saved assets. From the Library you can:

- Re-edit an asset (loads the baked file back into the editor with pre-populated tags)
- Duplicate an asset
- Remove an asset

### 6. Export (Backup / Transfer)

Use the **Export** function to download a ZIP of all library assets + `manifest.json`. Useful for backup or moving the library between machines.

---

## Features

**Editing**
- Brightness, contrast, hue, saturation, grayscale, invert
- Flip horizontal/vertical
- Size/zoom, position X/Y
- Crop to square
- Outfill background (color fill or transparent padding)
- Circle mask (baked on export)
- Vignette

**Animation**
- Speed multiplier (0.1x–4x)
- Reverse frames
- Visualizer Preview mode (shows DV3 gradient mask)
- Compare mode (side-by-side)

**Organization**
- Inbox/Library split — separate raw imports from finished assets
- Multi-selection: Shift+click (range), Ctrl+click (toggle)
- Duplicate and Remove assets
- Batch export and batch rename
- Undo/redo with labeled buttons

**Export**
- FFmpeg WASM bake — fully in-browser, no server
- Writes WebP + manifest entry on Save
- ZIP export of full library for backup

---

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- `@ffmpeg/ffmpeg` and `@ffmpeg/util`
- IndexedDB (via browser API)
- File System Access API (folder connect)
- JSZip + file-saver

---

## Requirements

- Node.js 18+
- Modern browser with WebAssembly and File System Access API support
- Chrome/Edge latest recommended (best `ImageDecoder` and animation compatibility)

---

## Getting Started

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

First run: click the folder icon or go to Settings (gear icon) to connect your DV3 project folder. This grants the browser permission to read from `inbox/` and write to `library/` and `manifest.json`.

---

## Scripts

```bash
npm run dev        # Start dev server
npm run build      # TypeScript build + Vite production build
npm run preview    # Preview production build
npm run lint       # ESLint
npm run typecheck  # TypeScript check only (no emit)
```

---

## Data Storage

All asset data is stored in the browser using IndexedDB:

- DB name: `DV3EditorDB`
- Stores: `assets`, `settings`

Baked files are written to the filesystem via the File System Access API (requires folder connection).

Clearing site data in the browser removes IndexedDB assets/settings but does **not** remove files already written to `data/animations/library/`.

---

## Notes and Known Limitations

- Export is CPU-heavy. Large animated files can take significant time. Keep the tab open.
- Color parity between CSS preview and FFmpeg export is close but may vary on strong hue values — expected behavior.
- Background replacement (outfill) is beta and may need threshold tuning per asset.
- File System Access API is supported in Chrome/Edge; Firefox support is limited.

---

## Troubleshooting

**Export fails with FFmpeg parser errors**
- Ensure you're on the latest code — several FFmpeg filter expression bugs have been fixed.
- Copy the full error from the app alert and check the final `Parsed_*` filter line for the specific issue.

**Exported animation becomes a still frame**
- Usually a browser/codec path issue in `ffmpeg.wasm`.
- Retry after a fresh page load.
- Prefer Chrome/Edge latest.

**Colors look different between editor and export**
- Small differences are expected (CSS filters vs FFmpeg math).
- Strong hue shifts can diverge more. Validate with sampled hex values in your target viewer.

**Assets disappear after browser cleanup**
- IndexedDB is cleared when you clear site data. Baked files in `data/animations/library/` are NOT affected.
- Re-import from the library folder if needed.

**Dev server behaves oddly**
- Stop and restart the dev server.
- If needed, clear Vite cache:
  ```bash
  rm -rf node_modules/.vite
  npm run dev
  ```

**Folder connection lost after page reload**
- Re-connect the folder via Settings. The browser requires re-granting access per session (File System Access API limitation).

---

## Known Good Test Cases

Use this checklist when validating changes to preview/export parity:

1. **Baseline parity** — Fresh asset, no edits. Preview and export visually identical.
2. **Grayscale parity** — Enable Grayscale only. Compare sampled background values.
3. **Brightness + contrast stress** — `Brightness 100, Contrast 100` / `Brightness 300, Contrast 300`. Confirm hand line art and background tone remain close.
4. **Circle mask bake** — Enable circle mask only. Confirm export succeeds with baked mask applied.
5. **Hue parity sweep** — Test at Hue -25, +25, +75. Low/mid shifts should be close; high positive shifts may diverge.
6. **Undo/redo** — Multiple control changes in sequence. Verify undo/redo steps through changes predictably.
7. **Save and re-edit** — Save an asset, switch to Library tab, re-open the asset. Tags and title should be pre-populated.

### Regression Log Template

| Date | Scenario | Settings | Preview Sample | Export Sample | Delta Notes | Pass/Fail |
|------|----------|----------|----------------|---------------|-------------|-----------|
| YYYY-MM-DD | Hue +25 | `Hue +25` | `#b4bd32` | `#c1c52d` | Slight shift, acceptable | Pass |

Delta notes: `none` / `barely noticeable` / `noticeable` / `major mismatch`

---

## Project Structure

```
src/
  App.tsx                   # Root — state management, inbox/library tabs
  types.ts                  # InboxItem, LibraryAsset, Manifest, EditAction, SavePayload
  constants.ts
  components/
    GalleryPanel.tsx         # Asset grid, thumbnails, multi-selection
    EditorPanel.tsx          # Edit controls — all adjustments and tools
    TagPanel.tsx             # Metadata: emotions, states, tags, theme, title, notes
    InboxPanel.tsx           # Import UI — File System Access API
    LibraryPanel.tsx         # Browse and manage saved assets
    TopToolbar.tsx           # Global header — folder status, undo/redo, settings
    SidebarPanel.tsx         # Inbox/Library tab switcher
    SettingsModal.tsx        # App preferences, export root folder
    ErrorBoundary.tsx        # Error handling
    VariantComparison.tsx    # Compare mode
    CircleCheck.tsx          # Shared circular checkbox component
  lib/
    bakeUtils.ts             # FFmpeg WASM integration — render pipeline
    exportUtils.ts           # ZIP export, manifest generation
    db.ts                    # IndexedDB CRUD
    inboxUtils.ts            # File copy/convert to inbox
    thumbStyles.ts           # Thumbnail preview styling
    validation.ts            # File type validation
```
