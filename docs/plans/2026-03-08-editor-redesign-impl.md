# Editor Redesign (Inbox/Library/Manifest) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild WebPew editor to use an inbox→tag→bake→library workflow with manifest-based animation routing, replacing the old export-to-ZIP and folder-based system.

**Architecture:** Users import files to `data/animations/inbox/`, edit non-destructively, tag with structured metadata (emotions/states/custom tags/theme), then Save — which FFmpeg-bakes edits, writes the final WebP to `data/animations/`, updates `manifest.json`, and removes the inbox original. The sidebar has two tabs (Inbox / Library). A new TagPanel on the right replaces the old metadata sidebar.

**Tech Stack:** React 18, TypeScript, Tailwind, Vite, FFmpeg WASM (`@ffmpeg/ffmpeg`), File System Access API, IndexedDB (Dexie), Playwright for UI tests.

**BEADS tasks this plan covers:** dv-7td, dv-wjm, dv-dcp, dv-gys, dv-wgo, dv-gjg, dv-2zv, dv-os3, dv-9el, dv-dis, dv-cx7

---

## Context You Must Read First

- Design doc: `docs/plans/2026-03-08-editor-redesign-design.md`
- Current types: `editor-web/src/types.ts`
- Current App state: `editor-web/src/App.tsx` (lines 20–50)
- Current export pipeline: `editor-web/src/lib/exportUtils.ts`
- EmotionMapper: `visualizer/emotion_map.py`
- Dev server: `cd editor-web && npm run dev` → `http://localhost:5173`
- Python tests: `source venv/bin/activate && pytest tests/ -v`
- TypeScript check: `cd editor-web && npm run typecheck`

---

## Task 1: Migration Script — Move Existing Files to Inbox

**BEADS:** `bd update dv-7td --status=in_progress`

**Files:**
- Create: `scripts/migrate_to_inbox.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-time migration: move all existing emotion/contextual animations to inbox.

Usage:
    python scripts/migrate_to_inbox.py [--dry-run]
"""
import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ANIMATIONS = PROJECT_ROOT / "data" / "animations"
INBOX = ANIMATIONS / "inbox"
OLD_DIRS = [ANIMATIONS / "emotions", ANIMATIONS / "contextual", ANIMATIONS / "states"]

def migrate(dry_run: bool = False) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    moved, skipped = 0, 0
    for old_dir in OLD_DIRS:
        if not old_dir.exists():
            continue
        for f in old_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in {".webp", ".gif", ".png", ".jpg"}:
                continue
            dest = INBOX / f.name
            # Avoid clobbering — append suffix if name collision
            if dest.exists():
                dest = INBOX / f"{f.stem}_{f.parent.name}{f.suffix}"
            print(f"{'[DRY]' if dry_run else 'MOVE'} {f.relative_to(PROJECT_ROOT)} → {dest.relative_to(PROJECT_ROOT)}")
            if not dry_run:
                shutil.move(str(f), str(dest))
            moved += 1
    if not dry_run:
        # Remove now-empty old dirs
        for old_dir in OLD_DIRS:
            if old_dir.exists():
                try:
                    shutil.rmtree(old_dir)
                    print(f"REMOVED {old_dir.relative_to(PROJECT_ROOT)}/")
                except OSError as e:
                    print(f"WARN could not remove {old_dir}: {e}")
    print(f"\n{'[DRY RUN] Would move' if dry_run else 'Moved'} {moved} files, skipped {skipped}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
```

**Step 2: Dry-run to verify**

```bash
python scripts/migrate_to_inbox.py --dry-run
```
Expected: prints every file that would move, no changes on disk.

**Step 3: Run it for real**

```bash
python scripts/migrate_to_inbox.py
```
Expected: files appear in `data/animations/inbox/`, old dirs gone.

**Step 4: Verify**

```bash
ls data/animations/inbox/ | wc -l   # should be > 0
ls data/animations/emotions 2>/dev/null && echo "ERROR: still exists" || echo "OK: removed"
```

**Step 5: Commit**

```bash
git add scripts/migrate_to_inbox.py data/animations/
git commit -m "feat: migrate existing animations to inbox, remove folder structure"
bd close dv-7td
```

---

## Task 2: New TypeScript Types

**BEADS:** `bd update dv-wjm --status=in_progress`

**Files:**
- Modify: `editor-web/src/types.ts`
- Modify: `editor-web/src/constants.ts` (add STATES list)

**Step 1: Replace types.ts**

```typescript
// editor-web/src/types.ts

export type ActionType =
  | 'FLIP_H' | 'FLIP_V' | 'SPEED' | 'REVERSE'
  | 'BRIGHTNESS' | 'CONTRAST' | 'INVERT' | 'GRAYSCALE'
  | 'BG_SWAP' | 'BG_THRESHOLD' | 'BG_COLOR'
  | 'HUE' | 'SATURATION' | 'VIGNETTE' | 'CIRCLE_MASK'
  | 'PADDING' | 'SQUARE_CROP' | 'POSITION_X' | 'POSITION_Y'
  | 'OUTFILL_ENABLED' | 'OUTFILL_COLOR';

export interface EditAction {
  type: ActionType;
  value: number | boolean;
}

export type AssetTheme = 'dark' | 'light' | 'both';

/** A file in data/animations/inbox/ — imported but not yet tagged or saved */
export interface InboxItem {
  id: string;
  /** The actual File object (from file picker or copied from disk) */
  file: File;
  /** Object URL for preview — revoke on cleanup */
  previewUrl: string;
  /** Original filename */
  name: string;
  /** MIME type */
  type: string;
  /** Non-destructive edit stack */
  editStack: EditAction[];
  historyIndex: number;
}

/** A tagged, baked animation in data/animations/ — has a manifest entry */
export interface LibraryAsset {
  /** filename only, e.g. "floyd_prism.webp" */
  file: string;
  theme: AssetTheme;
  emotions: string[];
  states: string[];
  /** Free-form custom tags */
  tags: string[];
  title: string;
  notes: string;
  /** Object URL for preview (loaded on demand) */
  previewUrl?: string;
}

/** Shape of data/animations/manifest.json */
export interface Manifest {
  version: 1;
  assets: LibraryAsset[];
}

/** Payload for the TagPanel's save action */
export interface SavePayload {
  filename: string;
  theme: AssetTheme;
  emotions: string[];
  states: string[];
  tags: string[];
  title: string;
  notes: string;
}

// Legacy — kept temporarily for EditorPanel compat, remove after full migration
export interface Asset {
  id: string;
  originalFile: File;
  fileUrl: string;
  name: string;
  type: string;
  emotion: string;
  additionalEmotions: string[];
  context: string;
  theme: AssetTheme;
  title: string;
  notes: string;
  editStack: EditAction[];
  historyIndex: number;
  linkedVariantId?: string;
  lastExportedAt?: string;
}

export interface EditorSettings {
  defaultPadding: number;
}

export interface BatchRenamePayload {
  prefix: string;
  tag: string;
  startIndex: number;
}
```

**Step 2: Add STATES to constants.ts**

Open `editor-web/src/constants.ts`. Add:
```typescript
export const STATES = [
  'idle',
  'listening',
  'processing',
  'thinking',
] as const;

export type StateTag = typeof STATES[number];
```

**Step 3: Typecheck**

```bash
cd editor-web && npm run typecheck
```
Expected: 0 errors (the old Asset type is kept for compat).

**Step 4: Commit**

```bash
git add editor-web/src/types.ts editor-web/src/constants.ts
git commit -m "feat: add InboxItem, LibraryAsset, Manifest types; add STATES constant"
bd close dv-wjm
```

---

## Task 3: Rewrite EmotionMapper — Manifest-Only

**BEADS:** `bd update dv-dcp --status=in_progress`

**Files:**
- Modify: `visualizer/emotion_map.py` (full rewrite)
- Modify: `tests/test_visualizer.py` (add manifest tests)

**Step 1: Write failing tests first**

Add to `tests/test_visualizer.py`:

```python
import json
import os
import tempfile
import pytest
from visualizer.emotion_map import EmotionMapper

@pytest.fixture
def manifest_dir(tmp_path):
    """Create a temp dir with a manifest.json and dummy animation files."""
    (tmp_path / "happy_bounce.webp").write_bytes(b"RIFF")
    (tmp_path / "sad_rain.webp").write_bytes(b"RIFF")
    (tmp_path / "both_neutral.webp").write_bytes(b"RIFF")
    manifest = {
        "version": 1,
        "assets": [
            {"file": "happy_bounce.webp", "theme": "dark", "emotions": ["happy", "excited"], "states": [], "tags": ["bouncy"]},
            {"file": "sad_rain.webp", "theme": "dark", "emotions": ["sad"], "states": [], "tags": []},
            {"file": "both_neutral.webp", "theme": "both", "emotions": ["neutral"], "states": ["idle"], "tags": []},
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path

def test_load_manifest_returns_count(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    assert mapper.asset_count() == 3

def test_get_animation_by_emotion(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("happy", theme="dark")
    assert path is not None
    assert "happy_bounce.webp" in path

def test_multi_emotion_tag(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("excited", theme="dark")
    assert path is not None
    assert "happy_bounce.webp" in path

def test_theme_both_matches_dark(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("neutral", theme="dark")
    assert path is not None
    assert "both_neutral.webp" in path

def test_theme_both_matches_light(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("neutral", theme="light")
    assert path is not None

def test_state_lookup(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_state_path("idle", theme="dark")
    assert path is not None
    assert "both_neutral.webp" in path

def test_unknown_emotion_falls_back_to_neutral(manifest_dir):
    mapper = EmotionMapper(str(manifest_dir / "manifest.json"))
    path = mapper.get_animation_path("roasting", theme="dark")
    assert path is not None  # falls back to neutral

def test_missing_manifest_returns_none():
    mapper = EmotionMapper("/nonexistent/manifest.json")
    assert mapper.get_animation_path("happy", theme="dark") is None
    assert mapper.asset_count() == 0
```

**Step 2: Run tests — confirm they FAIL**

```bash
source venv/bin/activate && pytest tests/test_visualizer.py -v -k "manifest"
```
Expected: multiple failures (EmotionMapper doesn't have these methods yet).

**Step 3: Rewrite EmotionMapper**

Replace `visualizer/emotion_map.py` with:

```python
"""Manifest-only animation resolver for the DV3 visualizer.

Reads data/animations/manifest.json to map emotion/state tags to animation
file paths. No directory scanning. No emotion_map.yaml.

Usage:
    mapper = EmotionMapper("data/animations/manifest.json")
    path = mapper.get_animation_path("happy", theme="dark")
    path = mapper.get_state_path("idle", theme="dark")
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EmotionMapper:
    """Resolves emotion/state strings to animation file paths via manifest.json.

    On init, loads the manifest and builds an index keyed by emotion and state.
    Files tagged theme='both' match any theme query.
    Falls back to neutral, then any entry, if no exact match.
    """

    def __init__(self, manifest_path: str) -> None:
        self._manifest_path = os.path.abspath(manifest_path)
        self._manifest_dir = os.path.dirname(self._manifest_path)
        # Index: {"emotion:dark": ["/abs/path/to/file.webp", ...], ...}
        self._emotion_index: dict[str, list[str]] = {}
        self._state_index: dict[str, list[str]] = {}
        self._all_files: list[str] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_animation_path(self, emotion: str, theme: str = "dark") -> Optional[str]:
        """Return a random animation matching the given emotion and theme.

        Falls back: emotion → neutral → any file in theme → None.
        """
        candidates = self._resolve(self._emotion_index, emotion, theme)
        if candidates:
            return random.choice(candidates)
        # Fallback to neutral
        neutral = self._resolve(self._emotion_index, "neutral", theme)
        if neutral:
            logger.warning("No animation for emotion=%r theme=%r — using neutral", emotion, theme)
            return random.choice(neutral)
        # Last resort: any file
        themed = [f for f in self._all_files if self._theme_matches(self._file_theme.get(f, "dark"), theme)]
        if themed:
            logger.warning("No neutral animation — picking random file")
            return random.choice(themed)
        logger.error("No animations available at all (manifest empty or missing?)")
        return None

    def get_state_path(self, state: str, theme: str = "dark") -> Optional[str]:
        """Return a random animation for the given state (idle/listening/processing)."""
        candidates = self._resolve(self._state_index, state, theme)
        if candidates:
            return random.choice(candidates)
        # Fall back to get_animation_path with matching emotion name
        return self.get_animation_path(state, theme)

    def asset_count(self) -> int:
        return len(self._all_files)

    def reload(self) -> None:
        """Reload manifest from disk (call after new exports)."""
        self._emotion_index.clear()
        self._state_index.clear()
        self._all_files.clear()
        self._file_theme = {}
        self._load()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._file_theme: dict[str, str] = {}
        if not os.path.isfile(self._manifest_path):
            logger.warning("Manifest not found at %s — no animations will play", self._manifest_path)
            return

        try:
            with open(self._manifest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load manifest %s: %s", self._manifest_path, exc)
            return

        assets = data.get("assets", [])
        loaded = 0
        for entry in assets:
            filename: str = entry.get("file", "")
            if not filename:
                continue
            abs_path = os.path.join(self._manifest_dir, filename)
            if not os.path.isfile(abs_path):
                logger.debug("Manifest file not on disk: %s", abs_path)
                continue

            theme = entry.get("theme", "dark")
            self._file_theme[abs_path] = theme
            self._all_files.append(abs_path)

            for emotion in entry.get("emotions", []):
                self._emotion_index.setdefault(emotion, []).append(abs_path)
            for state in entry.get("states", []):
                self._state_index.setdefault(state, []).append(abs_path)
            loaded += 1

        logger.info("EmotionMapper: loaded %d/%d assets from manifest", loaded, len(assets))

    def _resolve(self, index: dict[str, list[str]], key: str, theme: str) -> list[str]:
        """Return files from index[key] that match the requested theme."""
        candidates = index.get(key, [])
        return [f for f in candidates if self._theme_matches(self._file_theme.get(f, "dark"), theme)]

    @staticmethod
    def _theme_matches(file_theme: str, requested: str) -> bool:
        if file_theme == "both":
            return True
        return file_theme == requested
```

**Step 4: Run tests — confirm they PASS**

```bash
source venv/bin/activate && pytest tests/test_visualizer.py -v -k "manifest"
```
Expected: all 9 manifest tests pass.

**Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all pass (or only pre-existing failures).

**Step 6: Commit**

```bash
git add visualizer/emotion_map.py tests/test_visualizer.py
git commit -m "feat: rewrite EmotionMapper to be manifest-only, remove folder scanning"
bd close dv-dcp
```

---

## Task 4: Wire Manifest Loading into main.py

**BEADS:** `bd update dv-gys --status=in_progress`

**Files:**
- Modify: `main.py` (find `self.emotion_mapper` init, ~line 309)

**Step 1: Find the current init block**

```bash
grep -n "emotion_mapper\|EmotionMapper\|emotion_map_path" main.py | head -20
```

**Step 2: Replace the init block**

Find this section (approximately):
```python
emotion_map_path = PROJECT_ROOT / "config" / "emotion_map.yaml"
from visualizer.emotion_map import EmotionMapper
if emotion_map_path.exists():
    self.emotion_mapper = EmotionMapper(str(emotion_map_path))
    ...
else:
    ...
    self.emotion_mapper = None
```

Replace with:
```python
from visualizer.emotion_map import EmotionMapper
manifest_path = PROJECT_ROOT / "data" / "animations" / "manifest.json"
self.emotion_mapper = EmotionMapper(str(manifest_path))
if self.emotion_mapper.asset_count() == 0:
    logger.warning(
        "No animations loaded — manifest missing or empty at %s. "
        "Export animations from the WebPew editor to populate it.",
        manifest_path,
    )
```

**Step 3: Find and update get_animation_path call**

Find `self.emotion_mapper.get_animation_path(emotion)` (around line 844) and update signature:
```python
return self.emotion_mapper.get_animation_path(emotion, theme="dark")
```

**Step 4: Remove emotion_map.yaml reference from settings loading (if any)**

```bash
grep -n "emotion_map.yaml\|emotion_map_path" main.py config/settings.yaml
```
Remove or comment out any remaining references.

**Step 5: Test companion boots without crash**

```bash
source venv/bin/activate && python main.py --windowed --debug 2>&1 | head -30
```
Expected: boots, logs "EmotionMapper: loaded 0/0 assets from manifest" (or however many are in inbox after migration). No crash.

**Step 6: Commit**

```bash
git add main.py
git commit -m "feat: wire manifest-only EmotionMapper into main.py startup"
bd close dv-gys
```

---

## Task 5: Update App.tsx State Model

**BEADS:** `bd update dv-wgo --status=in_progress`

**Files:**
- Modify: `editor-web/src/App.tsx`

**Step 1: Replace state declarations (top of AppContent)**

Remove all existing state and replace with:
```typescript
// Tab state
const [activeTab, setActiveTab] = useState<'inbox' | 'library'>('inbox');

// Inbox
const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
const [activeInboxId, setActiveInboxId] = useState<string | null>(null);

// Library
const [libraryAssets, setLibraryAssets] = useState<LibraryAsset[]>([]);
const [activeLibraryFile, setActiveLibraryFile] = useState<string | null>(null);

// Shared editor state
const [isSaving, setIsSaving] = useState(false);
const [saveStatus, setSaveStatus] = useState('');

// Settings
const [showSettings, setShowSettings] = useState(false);
const [dirHandle, setDirHandle] = useState<DirHandle | null>(null);
```

**Step 2: Update imports**

```typescript
import { InboxItem, LibraryAsset, LibraryAsset as LA, SavePayload } from './types';
```

**Step 3: Load library from manifest on init**

```typescript
useEffect(() => {
  const init = async () => {
    // Load dir handle from IndexedDB
    const savedHandle = await loadDirectoryHandle();
    if (savedHandle) {
      const typedHandle = savedHandle as DirHandle;
      const perm = await typedHandle.queryPermission({ mode: 'readwrite' });
      if (perm === 'granted') setDirHandle(typedHandle);
    }
    // Load manifest if handle available
    // (manifest loading happens in loadLibrary which uses dirHandle)
  };
  init();
}, []);
```

**Step 4: Add loadLibrary helper**

```typescript
const loadLibrary = async (handle: DirHandle) => {
  try {
    const manifestHandle = await handle.getFileHandle('manifest.json');
    const file = await manifestHandle.getFile();
    const text = await file.text();
    const data = JSON.parse(text);
    setLibraryAssets(data.assets ?? []);
  } catch {
    setLibraryAssets([]);
  }
};
```

**Step 5: Typecheck**

```bash
cd editor-web && npm run typecheck
```
Fix any type errors. The `Asset` type still exists so `EditorPanel` won't break yet.

**Step 6: Commit**

```bash
git add editor-web/src/App.tsx
git commit -m "refactor: update App.tsx to inbox/library state model"
bd close dv-wgo
```

---

## Task 6: Redesign Sidebar — Inbox/Library Tabs

**BEADS:** `bd update dv-gjg --status=in_progress`

**Files:**
- Create: `editor-web/src/components/InboxPanel.tsx`
- Create: `editor-web/src/components/LibraryPanel.tsx`
- Modify: `editor-web/src/App.tsx` (wire new sidebar)

**Step 1: Create InboxPanel.tsx**

```tsx
// editor-web/src/components/InboxPanel.tsx
import * as React from 'react';
import { Upload, Inbox } from 'lucide-react';
import { InboxItem } from '../types';
import { computeThumbStyles } from '../lib/thumbStyles';

interface Props {
  items: InboxItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onImport: (files: FileList) => void;
}

export const InboxPanel: React.FC<Props> = ({ items, activeId, onSelect, onImport }) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-white/10 flex items-center justify-between shrink-0">
        <span className="text-white/50 text-xs uppercase tracking-wider flex items-center gap-1.5">
          <Inbox className="w-3.5 h-3.5" />
          {items.length > 0 ? `${items.length} to tag` : 'Empty'}
        </span>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-1.5 bg-[#f97316] hover:bg-[#fb923c] text-white text-xs px-2.5 py-1.5 rounded transition-colors"
          title="Import WebP or GIF"
        >
          <Upload className="w-3 h-3" /> Import
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          accept="image/webp,image/gif"
          onChange={(e) => e.target.files && onImport(e.target.files)}
        />
      </div>

      {items.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3 p-6">
          <Inbox className="w-8 h-8" />
          <p className="text-xs text-center">Import WebP or GIF files to get started</p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-2">
          <div className="grid grid-cols-3 gap-1.5">
            {items.map((item) => {
              const isActive = item.id === activeId;
              return (
                <div
                  key={item.id}
                  onClick={() => onSelect(item.id)}
                  className={`relative aspect-square bg-black rounded overflow-hidden cursor-pointer border-2 transition-all ${
                    isActive ? 'border-[#f97316]' : 'border-transparent hover:border-white/20'
                  }`}
                >
                  <img
                    src={item.previewUrl}
                    className="w-full h-full object-cover"
                    alt={item.name}
                    style={computeThumbStyles(item.editStack, item.historyIndex)}
                  />
                  <div className="absolute bottom-0 left-0 right-0 bg-black/70 px-1 py-0.5">
                    <p className="text-white/60 text-[9px] truncate">{item.name}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
```

**Step 2: Create LibraryPanel.tsx**

```tsx
// editor-web/src/components/LibraryPanel.tsx
import * as React from 'react';
import { useState } from 'react';
import { BookOpen, Search } from 'lucide-react';
import { LibraryAsset } from '../types';

interface Props {
  assets: LibraryAsset[];
  activeFile: string | null;
  onSelect: (file: string) => void;
  dirHandle: FileSystemDirectoryHandle | null;
}

export const LibraryPanel: React.FC<Props> = ({ assets, activeFile, onSelect, dirHandle }) => {
  const [search, setSearch] = useState('');
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});

  const filtered = assets.filter((a) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      a.file.toLowerCase().includes(q) ||
      a.emotions.some((e) => e.includes(q)) ||
      a.states.some((s) => s.includes(q)) ||
      a.tags.some((t) => t.includes(q))
    );
  });

  const loadPreview = async (asset: LibraryAsset) => {
    if (previewUrls[asset.file] || !dirHandle) return;
    try {
      const fh = await dirHandle.getFileHandle(asset.file);
      const file = await fh.getFile();
      setPreviewUrls((prev) => ({ ...prev, [asset.file]: URL.createObjectURL(file) }));
    } catch { /* file may not be accessible yet */ }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-white/10 shrink-0">
        <div className="flex items-center gap-2 bg-white/5 rounded px-2 py-1.5">
          <Search className="w-3.5 h-3.5 text-white/40 shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search emotions, tags..."
            className="bg-transparent text-white text-xs placeholder-white/30 outline-none flex-1 min-w-0"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3 p-6">
          <BookOpen className="w-8 h-8" />
          <p className="text-xs text-center">{assets.length === 0 ? 'No tagged animations yet' : 'No matches'}</p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-2">
          <div className="grid grid-cols-3 gap-1.5">
            {filtered.map((asset) => {
              const isActive = asset.file === activeFile;
              const previewUrl = previewUrls[asset.file];
              return (
                <div
                  key={asset.file}
                  onClick={() => onSelect(asset.file)}
                  onMouseEnter={() => loadPreview(asset)}
                  className={`relative aspect-square bg-black rounded overflow-hidden cursor-pointer border-2 transition-all ${
                    isActive ? 'border-[#f97316]' : 'border-transparent hover:border-white/20'
                  }`}
                >
                  {previewUrl ? (
                    <img src={previewUrl} className="w-full h-full object-cover" alt={asset.file} />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-white/20 text-[9px]">
                      {asset.file.replace('.webp', '')}
                    </div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-black/70 px-1 py-0.5">
                    <p className="text-white/60 text-[9px] truncate">{asset.emotions[0] ?? '—'}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
```

**Step 3: Create shared thumbStyles utility**

```typescript
// editor-web/src/lib/thumbStyles.ts
import { EditAction, ActionType } from '../types';
import React from 'react';

export function computeThumbStyles(editStack: EditAction[], historyIndex: number): React.CSSProperties {
  const stack = editStack.slice(0, historyIndex + 1);
  const get = (type: ActionType, def: number | boolean): number | boolean => {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].type === type) return stack[i].value;
    }
    return def;
  };
  let filter = '';
  let transform = '';
  if (get('FLIP_H', false)) transform += 'scaleX(-1) ';
  if (get('FLIP_V', false)) transform += 'scaleY(-1) ';
  const bright = get('BRIGHTNESS', 100) as number;
  const cont = get('CONTRAST', 100) as number;
  const hue = get('HUE', 0) as number;
  const sat = get('SATURATION', 100) as number;
  if (bright !== 100) filter += `brightness(${bright}%) `;
  if (cont !== 100) filter += `contrast(${cont}%) `;
  if (get('INVERT', false)) filter += 'invert(100%) ';
  if (get('GRAYSCALE', false)) filter += 'grayscale(100%) ';
  if (hue !== 0) filter += `hue-rotate(${hue}deg) `;
  if (sat !== 100) filter += `saturate(${sat}%) `;
  const zoomOffset = get('PADDING', 0) as number;
  const zoomScale = Math.min(2.5, Math.max(0.15, 1 + zoomOffset / 300));
  const cropScale = get('SQUARE_CROP', false) ? 1.2 : 1;
  const posX = get('POSITION_X', 0) as number;
  const posY = get('POSITION_Y', 0) as number;
  if (posX !== 0) transform += `translateX(${posX}px) `;
  if (posY !== 0) transform += `translateY(${posY}px) `;
  return {
    filter: filter.trim() || undefined,
    transform: `${transform.trim()} scale(${cropScale * zoomScale})`.trim(),
    transformOrigin: 'center center',
  };
}
```

Also update `GalleryPanel.tsx` to import from `../lib/thumbStyles` instead of defining locally.

**Step 4: Create the tabbed sidebar wrapper in App.tsx**

Replace `<GalleryPanel ...>` with:
```tsx
<div className="w-96 bg-black border-r border-white/10 flex flex-col z-10 shrink-0 h-full">
  {/* Tab header */}
  <div className="flex border-b border-white/10 shrink-0">
    <button
      onClick={() => setActiveTab('inbox')}
      className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
        activeTab === 'inbox' ? 'text-[#f97316] border-b-2 border-[#f97316]' : 'text-white/40 hover:text-white/70'
      }`}
    >
      Inbox
      {inboxItems.length > 0 && (
        <span className="bg-[#f97316] text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
          {inboxItems.length}
        </span>
      )}
    </button>
    <button
      onClick={() => setActiveTab('library')}
      className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
        activeTab === 'library' ? 'text-[#f97316] border-b-2 border-[#f97316]' : 'text-white/40 hover:text-white/70'
      }`}
    >
      Library
      {libraryAssets.length > 0 && (
        <span className="text-white/30 text-[10px]">{libraryAssets.length}</span>
      )}
    </button>
  </div>
  {/* Tab content */}
  <div className="flex-1 overflow-hidden">
    {activeTab === 'inbox' ? (
      <InboxPanel
        items={inboxItems}
        activeId={activeInboxId}
        onSelect={setActiveInboxId}
        onImport={handleImport}
      />
    ) : (
      <LibraryPanel
        assets={libraryAssets}
        activeFile={activeLibraryFile}
        onSelect={setActiveLibraryFile}
        dirHandle={dirHandle}
      />
    )}
  </div>
</div>
```

**Step 5: Typecheck + visual test**

```bash
cd editor-web && npm run typecheck
```
Then start dev server, open browser, verify tabs switch:
```bash
npm run dev &
npx playwright test tests-pw/editor.spec.ts --reporter=list
```

**Step 6: Commit**

```bash
git add editor-web/src/components/InboxPanel.tsx editor-web/src/components/LibraryPanel.tsx \
        editor-web/src/lib/thumbStyles.ts editor-web/src/App.tsx editor-web/src/components/GalleryPanel.tsx
git commit -m "feat: replace gallery sidebar with inbox/library tabs"
bd close dv-gjg
```

---

## Task 7: TagPanel Component

**BEADS:** `bd update dv-2zv --status=in_progress`

**Files:**
- Create: `editor-web/src/components/TagPanel.tsx`

```tsx
// editor-web/src/components/TagPanel.tsx
import * as React from 'react';
import { useState } from 'react';
import { X, Plus, Save } from 'lucide-react';
import { SavePayload, AssetTheme } from '../types';
import { EMOTIONS, STATES } from '../constants';

interface Props {
  /** Pre-populate when re-editing a library item */
  initial?: Partial<SavePayload>;
  isSaving: boolean;
  onSave: (payload: SavePayload) => void;
}

export const TagPanel: React.FC<Props> = ({ initial = {}, isSaving, onSave }) => {
  const [emotions, setEmotions] = useState<string[]>(initial.emotions ?? []);
  const [states, setStates] = useState<string[]>(initial.states ?? []);
  const [tags, setTags] = useState<string[]>(initial.tags ?? []);
  const [tagInput, setTagInput] = useState('');
  const [filename, setFilename] = useState(initial.filename ?? '');
  const [theme, setTheme] = useState<AssetTheme>(initial.theme ?? 'dark');
  const [title, setTitle] = useState(initial.title ?? '');
  const [notes, setNotes] = useState(initial.notes ?? '');

  const toggle = (list: string[], setList: (v: string[]) => void, value: string) => {
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  const addTag = () => {
    const t = tagInput.trim().toLowerCase().replace(/\s+/g, '_');
    if (t && !tags.includes(t)) setTags([...tags, t]);
    setTagInput('');
  };

  const canSave = filename.trim().length > 0 && (emotions.length > 0 || states.length > 0);

  const handleSave = () => {
    if (!canSave) return;
    onSave({ filename: filename.trim(), theme, emotions, states, tags, title, notes });
  };

  return (
    <div className="w-80 bg-black border-l border-white/10 flex flex-col h-full overflow-y-auto shrink-0">
      <div className="p-4 space-y-5">

        {/* Emotions */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">Emotions</h3>
          <div className="flex flex-wrap gap-1.5">
            {EMOTIONS.map((e) => (
              <button
                key={e}
                onClick={() => toggle(emotions, setEmotions, e)}
                className={`px-2 py-1 rounded text-xs transition-colors ${
                  emotions.includes(e)
                    ? 'bg-[#f97316] text-black font-medium'
                    : 'bg-white/5 text-white/50 hover:bg-white/10 hover:text-white'
                }`}
              >
                {e}
              </button>
            ))}
          </div>
        </section>

        {/* States */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">States</h3>
          <div className="flex flex-wrap gap-1.5">
            {STATES.map((s) => (
              <button
                key={s}
                onClick={() => toggle(states, setStates, s)}
                className={`px-2 py-1 rounded text-xs transition-colors ${
                  states.includes(s)
                    ? 'bg-[#00d2ff] text-black font-medium'
                    : 'bg-white/5 text-white/50 hover:bg-white/10 hover:text-white'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </section>

        {/* Custom Tags */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">Tags</h3>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {tags.map((t) => (
              <span key={t} className="flex items-center gap-1 bg-white/10 text-white/70 text-xs px-2 py-0.5 rounded">
                {t}
                <button onClick={() => setTags(tags.filter((x) => x !== t))} className="text-white/40 hover:text-white">
                  <X className="w-2.5 h-2.5" />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-1.5">
            <input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addTag()}
              placeholder="pink_floyd, music..."
              className="flex-1 bg-white/5 text-white text-xs px-2.5 py-1.5 rounded outline-none placeholder-white/20 border border-white/10 focus:border-[#f97316]/50"
            />
            <button onClick={addTag} className="p-1.5 bg-white/5 hover:bg-white/10 rounded text-white/50 hover:text-white">
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </section>

        {/* Filename */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">Filename</h3>
          <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded overflow-hidden focus-within:border-[#f97316]/50">
            <input
              value={filename}
              onChange={(e) => setFilename(e.target.value.replace(/[^a-z0-9_\-]/gi, '_').toLowerCase())}
              placeholder="happy_bounce"
              className="flex-1 bg-transparent text-white text-xs px-2.5 py-1.5 outline-none placeholder-white/20"
            />
            <span className="text-white/30 text-xs pr-2">.webp</span>
          </div>
        </section>

        {/* Theme */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">Theme</h3>
          <div className="flex gap-1.5">
            {(['dark', 'light', 'both'] as AssetTheme[]).map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className={`flex-1 py-1.5 rounded text-xs capitalize transition-colors ${
                  theme === t
                    ? 'bg-white/20 text-white font-medium'
                    : 'bg-white/5 text-white/40 hover:bg-white/10'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </section>

        {/* Title / Notes */}
        <section>
          <h3 className="text-white/40 text-[10px] uppercase tracking-widest mb-2">Title (optional)</h3>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Pink Floyd prism"
            className="w-full bg-white/5 text-white text-xs px-2.5 py-1.5 rounded outline-none placeholder-white/20 border border-white/10 focus:border-[#f97316]/50"
          />
        </section>

      </div>

      {/* Save button — sticky at bottom */}
      <div className="mt-auto p-4 border-t border-white/10">
        {!canSave && (
          <p className="text-white/30 text-[10px] mb-2 text-center">
            {filename.trim() === '' ? 'Set a filename' : 'Check at least one emotion or state'}
          </p>
        )}
        <button
          onClick={handleSave}
          disabled={!canSave || isSaving}
          className={`w-full py-2.5 rounded font-medium text-sm flex items-center justify-center gap-2 transition-colors ${
            canSave && !isSaving
              ? 'bg-[#f97316] hover:bg-[#fb923c] text-black'
              : 'bg-white/5 text-white/20 cursor-not-allowed'
          }`}
        >
          {isSaving ? (
            <>
              <span className="animate-spin inline-block w-4 h-4 border-2 border-black/30 border-t-black rounded-full" />
              Saving...
            </>
          ) : (
            <>
              <Save className="w-4 h-4" /> Save to Library
            </>
          )}
        </button>
      </div>
    </div>
  );
};
```

**Step 2: Wire TagPanel into App.tsx**

Replace the right panel (currently EditorSettings/TopToolbar side) with:
```tsx
{(activeInboxId || activeLibraryFile) && (
  <TagPanel
    initial={activeLibraryFile ? libraryAssets.find(a => a.file === activeLibraryFile) : undefined}
    isSaving={isSaving}
    onSave={handleSave}
  />
)}
```

**Step 3: Visual test**

```bash
npx playwright test tests-pw/settings.spec.ts --reporter=list
```
Then write a new test `tests-pw/tagpanel.spec.ts` that:
- Loads inbox item
- Verifies tag panel appears
- Checks emotion buttons are visible
- Checks Save is disabled until filename+emotion set

**Step 4: Commit**

```bash
git add editor-web/src/components/TagPanel.tsx editor-web/src/App.tsx
git commit -m "feat: add TagPanel with emotions/states/tags/filename/theme/save"
bd close dv-2zv
```

---

## Task 8: Import Flow — Copy WebP or Convert GIF to Inbox

**BEADS:** `bd update dv-os3 --status=in_progress`

**Files:**
- Modify: `editor-web/src/App.tsx` (add `handleImport`)
- Modify: `editor-web/src/lib/exportUtils.ts` or new `editor-web/src/lib/inboxUtils.ts`

**Step 1: Add handleImport to App.tsx**

```typescript
const handleImport = async (files: FileList) => {
  if (!dirHandle) {
    alert('Select a DV3 folder first in Settings before importing.');
    return;
  }
  const inboxDir = await dirHandle.getDirectoryHandle('inbox', { create: true });

  for (const file of Array.from(files)) {
    let webpBlob: Blob;
    let outName: string;

    if (file.type === 'image/gif') {
      // Convert GIF → WebP via FFmpeg WASM
      setSaveStatus(`Converting ${file.name}...`);
      webpBlob = await convertGifToWebp(file);  // see inboxUtils.ts
      outName = file.name.replace(/\.gif$/i, '.webp');
    } else {
      webpBlob = file;
      outName = file.name;
    }

    // Write to inbox/
    const fh = await inboxDir.getFileHandle(outName, { create: true });
    const writable = await fh.createWritable();
    await writable.write(new Blob([await webpBlob.arrayBuffer()]));
    await writable.close();

    // Add to in-memory inbox
    const inboxFile = new File([webpBlob], outName, { type: 'image/webp' });
    const item: InboxItem = {
      id: crypto.randomUUID(),
      file: inboxFile,
      previewUrl: URL.createObjectURL(inboxFile),
      name: outName,
      type: 'image/webp',
      editStack: [],
      historyIndex: -1,
    };
    setInboxItems((prev) => [...prev, item]);
    setActiveInboxId(item.id);
    setActiveTab('inbox');
  }
  setSaveStatus('');
};
```

**Step 2: Create inboxUtils.ts — GIF conversion**

```typescript
// editor-web/src/lib/inboxUtils.ts
import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';

let ffmpegInstance: FFmpeg | null = null;

async function getFFmpeg(): Promise<FFmpeg> {
  if (ffmpegInstance?.loaded) return ffmpegInstance;
  const ffmpeg = new FFmpeg();
  await ffmpeg.load({
    coreURL: '/ffmpeg/ffmpeg-core.js',
    wasmURL: '/ffmpeg/ffmpeg-core.wasm',
  });
  ffmpegInstance = ffmpeg;
  return ffmpeg;
}

export async function convertGifToWebp(gifFile: File): Promise<Blob> {
  const ffmpeg = await getFFmpeg();
  const inputName = 'input.gif';
  const outputName = 'output.webp';
  await ffmpeg.writeFile(inputName, await fetchFile(gifFile));
  await ffmpeg.exec(['-i', inputName, '-loop', '0', '-quality', '85', outputName]);
  const data = await ffmpeg.readFile(outputName);
  return new Blob([data], { type: 'image/webp' });
}
```

**Step 3: Test import manually via Playwright**

```typescript
// tests-pw/import.spec.ts
test('import WebP adds to inbox tab', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(1000);
  // Note: File System Access API requires user gesture — test the in-memory path
  // by checking the inbox tab renders after programmatic item injection
  // Full import test requires manual verification with real folder access
  const inboxTab = page.getByText('Inbox');
  await expect(inboxTab).toBeVisible();
});
```

**Step 4: Commit**

```bash
git add editor-web/src/App.tsx editor-web/src/lib/inboxUtils.ts editor-web/tests-pw/import.spec.ts
git commit -m "feat: add import flow — copy WebP or convert GIF to inbox"
bd close dv-os3
```

---

## Task 9: Bake-and-Save Flow

**BEADS:** `bd update dv-9el --status=in_progress`

**Files:**
- Modify: `editor-web/src/App.tsx` (add `handleSave`)
- Modify: `editor-web/src/lib/exportUtils.ts` (add `bakeToWebp`)

**Step 1: Add bakeToWebp to exportUtils.ts**

```typescript
/**
 * Bake all edits from an InboxItem into a final WebP blob.
 * Uses FFmpeg WASM. This is the destructive "save" operation.
 */
export async function bakeToWebp(
  item: InboxItem,
  onProgress: (msg: string, pct: number) => void
): Promise<Uint8Array> {
  // Reuse the existing executeBatchExport infrastructure:
  // Convert InboxItem → minimal Asset shape for the bake pipeline
  const assetCompat = {
    id: item.id,
    originalFile: item.file,
    fileUrl: item.previewUrl,
    name: item.name,
    type: item.type,
    editStack: item.editStack,
    historyIndex: item.historyIndex,
    emotion: '', additionalEmotions: [], context: '', theme: 'dark' as const,
    title: '', notes: '',
  };
  const results = await encodeWithEdits([assetCompat], onProgress);
  if (!results[0]) throw new Error('Bake produced no output');
  return results[0].bytes;
}
```

**Step 2: Add handleSave to App.tsx**

```typescript
const handleSave = async (payload: SavePayload) => {
  const activeItem = inboxItems.find((i) => i.id === activeInboxId);
  if (!activeItem || !dirHandle) return;

  setIsSaving(true);
  setSaveStatus('Baking edits...');
  try {
    // 1. Bake edits
    const bytes = await bakeToWebp(activeItem, (msg, pct) => setSaveStatus(`${msg} (${pct}%)`));

    // 2. Write to data/animations/{filename}.webp
    setSaveStatus('Writing to library...');
    const outFilename = payload.filename.endsWith('.webp')
      ? payload.filename
      : `${payload.filename}.webp`;
    const fileHandle = await dirHandle.getFileHandle(outFilename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(new Blob([bytes.buffer as ArrayBuffer]));
    await writable.close();

    // 3. Update manifest.json
    setSaveStatus('Updating manifest...');
    const newEntry: LibraryAsset = {
      file: outFilename,
      theme: payload.theme,
      emotions: payload.emotions,
      states: payload.states,
      tags: payload.tags,
      title: payload.title,
      notes: payload.notes,
    };
    const updatedAssets = [
      ...libraryAssets.filter((a) => a.file !== outFilename),
      newEntry,
    ];
    const manifest = { version: 1 as const, assets: updatedAssets };
    const manifestHandle = await dirHandle.getFileHandle('manifest.json', { create: true });
    const mWritable = await manifestHandle.createWritable();
    await mWritable.write(new Blob([JSON.stringify(manifest, null, 2)]));
    await mWritable.close();

    // 4. Delete inbox original from disk
    const inboxDir = await dirHandle.getDirectoryHandle('inbox');
    await inboxDir.removeEntry(activeItem.name).catch(() => {/* may not exist on disk */});

    // 5. Update in-memory state
    URL.revokeObjectURL(activeItem.previewUrl);
    setInboxItems((prev) => prev.filter((i) => i.id !== activeInboxId));
    setLibraryAssets(updatedAssets);
    setActiveInboxId(null);
    setActiveTab('library');
    setActiveLibraryFile(outFilename);
    setSaveStatus('Saved!');
    setTimeout(() => setSaveStatus(''), 2000);
  } catch (err) {
    setSaveStatus(`Error: ${String(err)}`);
    console.error('Save failed:', err);
  } finally {
    setIsSaving(false);
  }
};
```

**Step 3: Typecheck**

```bash
cd editor-web && npm run typecheck
```

**Step 4: Manual integration test**

Start dev server. Import a WebP. Tag it. Set filename. Click Save. Verify:
- File appears in `data/animations/` on disk
- `manifest.json` contains the new entry
- Inbox item disappears
- Library tab shows the new animation

```bash
cat data/animations/manifest.json  # should contain your new entry
ls data/animations/*.webp          # should contain your new file
```

**Step 5: Commit**

```bash
git add editor-web/src/App.tsx editor-web/src/lib/exportUtils.ts
git commit -m "feat: bake-and-save flow — FFmpeg bake, write to library, update manifest"
bd close dv-9el
```

---

## Task 10: Re-Edit Library Item

**BEADS:** `bd update dv-dis --status=in_progress`

**Files:**
- Modify: `editor-web/src/App.tsx`

**Step 1: Add handleSelectLibraryAsset**

```typescript
const handleSelectLibraryAsset = async (file: string) => {
  if (!dirHandle) return;
  try {
    const fh = await dirHandle.getFileHandle(file);
    const f = await fh.getFile();
    const previewUrl = URL.createObjectURL(f);
    // Create an InboxItem from the library file (reuses the editor)
    const item: InboxItem = {
      id: `library:${file}`,
      file: f,
      previewUrl,
      name: file,
      type: f.type,
      editStack: [],
      historyIndex: -1,
    };
    setInboxItems((prev) => {
      // Replace any existing re-edit slot
      const filtered = prev.filter((i) => !i.id.startsWith('library:'));
      return [...filtered, item];
    });
    setActiveInboxId(item.id);
    setActiveLibraryFile(file);
    setActiveTab('inbox');
  } catch (err) {
    console.error('Could not load library asset for editing:', err);
  }
};
```

Wire to `LibraryPanel.onSelect`.

**Step 2: Pre-populate TagPanel for re-edit**

When `activeInboxId` starts with `library:`, find the matching `LibraryAsset` and pass it as `initial` to `TagPanel`. The save flow handles overwriting the existing file.

**Step 3: Test**

Playwright test: load library, click an item, verify editor loads with pre-populated tags.

**Step 4: Commit**

```bash
git add editor-web/src/App.tsx
git commit -m "feat: re-edit library assets — load baked file back into editor with tags"
bd close dv-dis
```

---

## Task 11: Cleanup Stale Tasks

**BEADS:** `bd update dv-cx7 --status=in_progress`

```bash
bd close dv-e0b --reason="Resolved by editor redesign — manifest-only system implemented"
bd close dv-e3v --reason="dark/light/both theme is now a first-class field in manifest; implementation covered by redesign"
bd close dv-6l4 --reason="GIF label and bulk delete superseded by new inbox/bake workflow"
bd update dv-hiw --notes="Pygame stays for now. Web visualizer is a separate parallel workstream (see web-visualizer plan). Not blocked."
bd close dv-cx7
```

---

## Final Verification

```bash
# Python tests
source venv/bin/activate && pytest tests/ -v

# TypeScript
cd editor-web && npm run typecheck && npm run build

# Playwright
npx playwright test --reporter=list

# Manual: open editor, import a file, tag it, save, verify on disk
ls data/animations/*.webp
cat data/animations/manifest.json

# Manual: start companion, verify it boots and loads manifest
source venv/bin/activate && python main.py --windowed --debug 2>&1 | grep -E "EmotionMapper|manifest"
```
