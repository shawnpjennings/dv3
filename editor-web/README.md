# WebPew

WebPew is a browser-based editor for preparing still and animated assets for WebP export.

It is built with React + TypeScript + Vite, stores your work locally in IndexedDB, and exports with `ffmpeg.wasm` directly in the browser.

## DV3 Integration

WebPew is the **primary animation asset editor** for the DV3 voice companion project. It replaces the legacy Pygame-based editor (`editor/`), which is now restricted to headless batch conversion only.

- Assets are tagged with `emotion`, `context`, and theme metadata that maps directly to DV3's emotion detection cascade and `emotion_map.yaml` configuration.
- Export paths follow DV3 animation library conventions: `{exportRoot}/emotions/{emotion}/` or `{exportRoot}/contextual/{context}/`.
- All new animation asset work — editing, adjusting, and exporting — is done here. Do not use the Pygame editor for new work.

## Features

- Upload and manage image assets locally
- Edit controls:
  - Flip horizontal/vertical
  - Size/zoom
  - Crop to square
  - Circle mask (baked on export)
  - Brightness, contrast, hue, saturation
  - Grayscale, invert, vignette
  - Background swap (beta)
- Temporal controls for animated assets:
  - Speed multiplier
  - Reverse frames
- Undo/redo history
- Duplicate and remove assets
- Batch export and batch rename
- Numeric inputs for precise slider values
- Reset all adjustments for the active asset

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- `@ffmpeg/ffmpeg` and `@ffmpeg/util`
- IndexedDB (via browser API)
- JSZip + file-saver

## Requirements

- Node.js 18+
- Modern browser with WebAssembly support
- For best animation handling: Chrome/Edge latest

## Getting Started

```bash
npm install
npm run dev
```

Then open the local URL shown by Vite (usually `http://localhost:5173`).

## Scripts

```bash
npm run dev        # Start dev server
npm run build      # TypeScript build + Vite production build
npm run preview    # Preview production build
npm run lint       # ESLint
npm run typecheck  # TypeScript check only
```

## Usage

1. Upload one or more image/WebP/GIF assets.
2. Select an asset from the gallery.
3. Adjust settings in the right editor panel.
4. Use typed numeric fields or sliders for precise values.
5. Export a single asset from the toolbar or batch export from the gallery.

## Data Storage

All asset and settings data is stored in the browser using IndexedDB:

- DB name: `DV3EditorDB`
- Stores:
  - `assets`
  - `settings`

Clearing site data in the browser will remove saved assets/settings.

## Notes and Current Limitations

- Export runs in-browser, so large animated files can take time.
- Color parity between CSS preview and FFmpeg export is close but may still vary on stronger hue values.
- Background replacement is marked beta and may need threshold tuning by asset.

## Troubleshooting

- Export fails with FFmpeg parser errors:
  - Use the latest code in this repo. Several FFmpeg filter expression issues were fixed (notably circle-mask export expressions).
  - If you see a new parser error, copy the full error log from the app alert and check the final `Parsed_*` filter line.

- Exported animation is missing or becomes a still frame:
  - This usually indicates browser/codec path differences in `ffmpeg.wasm`.
  - Retry export after a fresh page load.
  - Prefer Chrome/Edge latest for best `ImageDecoder` and animation compatibility.

- Colors look different between editor and export:
  - Small differences are expected because preview uses CSS filters while export uses FFmpeg math.
  - Strong hue shifts can diverge more than low/moderate shifts.
  - For critical color matching, validate using sampled hex values in your target viewer.

- Export takes a long time:
  - Export is local and CPU-heavy. Large animated files can take significant time.
  - Keep the tab open and avoid throttling the browser process.

- Assets disappear after browser cleanup:
  - All data is stored in IndexedDB. Clearing site data removes assets/settings.

- Dev server behaves oddly after many dependency/runtime changes:
  - Stop and restart the dev server.
  - If needed, clear Vite cache and relaunch:

```bash
rm -rf node_modules/.vite
npm run dev
```

## Known Good Test Cases

Use this quick checklist when validating new changes to preview/export parity:

1. Baseline parity:
  - Fresh asset, no edits.
  - Verify preview and export are visually identical.

2. Grayscale parity:
  - Enable `Grayscale` only.
  - Compare sampled background values between preview and export.

3. Grayscale + contrast/brightness stress:
  - Test combinations like:
    - `Brightness 100, Contrast 100`
    - `Brightness 300, Contrast 300`
    - `Brightness 300, Contrast 500`
  - Confirm hand line art and background tone remain close in preview/export.

4. Circle mask bake:
  - Enable `Apply Baked Black Mask` only.
  - Confirm export succeeds and baked mask is applied.

5. Hue parity sweep:
  - Keep other controls at baseline.
  - Test at `Hue -25`, `Hue +25`, and `Hue +75`.
  - Expect low/mid shifts to be close; high positive shifts may show larger deltas.

6. Undo/redo behavior:
  - Perform multiple control changes in sequence.
  - Verify undo/redo steps through changes predictably.

Recommended method:

- Compare preview and export in the same browser.
- Sample colors in an external tool when needed.
- Record both preview/export values for regression tracking.

### Regression Log Template

Use this table for quick pass/fail tracking when testing preview vs export parity.

| Date | Scenario | Settings | Preview Sample | Export Sample | Delta Notes | Pass/Fail |
| --- | --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD | Hue +25 | `Brightness 100, Contrast 100, Hue +25, Saturation 100` | `#b4bd32` | `#c1c52d` | Slight shift, acceptable | Pass |
| YYYY-MM-DD | Hue +75 | `Brightness 100, Contrast 100, Hue +75, Saturation 100` | `#52d65d` | `#aad02b` | Noticeable shift, investigate | Fail |

Suggested notes format in `Delta Notes`:

- `none`
- `barely noticeable`
- `noticeable`
- `major mismatch`

## Project Structure

```text
src/
  components/
  lib/
  constants.ts
  types.ts
```

## License

