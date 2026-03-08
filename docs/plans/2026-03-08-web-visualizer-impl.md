# Web Visualizer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Pygame visualizer with a browser-based fullscreen visualizer that plays manifest-tagged WebP animations, applies a radial gradient mask so animations float in black space, and receives emotion/state events from the companion via WebSocket.

**Architecture:** Python companion adds an `aiohttp` WebSocket server. A React/Vite app (`visualizer-web/`) connects to the WS, reads `manifest.json` via the Vite static file server, and renders the current animation with CSS radial gradient masking and crossfade transitions. Animations appear to float on a black background — no visible box or hard edge.

**Tech Stack:** React 18, TypeScript, Tailwind, Vite, aiohttp WebSocket server, Web Animations API for crossfade.

**Display target:** Ultrawide monitor. Fullscreen browser window. Animation centered, sized as configurable % of screen height.

**BEADS:** Create tasks for each step before starting (see Task 0).

---

## Context You Must Read First

- Mockups: `temp/mockups/bw_edges.png` (floating effect goal), `temp/mockups/bw_mask_gradiant.png` (gradient mask diagram), `temp/mockups/bw_mask_image-sizes.png` (size variation)
- PRD visualizer spec: `DV3-PRD.md` lines 152–164 and 273–291
- Current Pygame visualizer: `visualizer/animation_engine.py`, `visualizer/display.py`
- Main entry: `main.py`
- Manifest structure: `docs/plans/2026-03-08-editor-redesign-design.md`
- Python venv: `source venv/bin/activate`
- Dev server: `cd visualizer-web && npm run dev` → `http://localhost:5174`

---

## Task 0: Create BEADS Tasks

```bash
bd create --title="WebSocket event server in Python companion" --description="Add aiohttp WS server to main.py that broadcasts emotion/state/tag events to connected visualizer clients." --type=feature --priority=0

bd create --title="Scaffold visualizer-web React app" --description="Create visualizer-web/ Vite+React+TS+Tailwind app. Serves animations from data/animations/ as static files. Fullscreen black background." --type=task --priority=0

bd create --title="Manifest loader + animation index in visualizer" --description="Fetch manifest.json at startup. Build emotion→[files] index. Serve animation files from /animations/ path on Vite dev server." --type=task --priority=1

bd create --title="Animation player with crossfade transitions" --description="Play WebP animation in centered container. CSS radial gradient mask makes edges fade to black (floating effect). Crossfade on emotion change (300ms default). Configurable size (% of screen height) and gradient opacity." --type=feature --priority=1

bd create --title="WebSocket client + emotion event handling" --description="Connect to companion WS server. On emotion/state events, look up manifest index and play matching animation. Reconnect with backoff on disconnect." --type=feature --priority=1

bd create --title="Wire web visualizer into main.py — replace Pygame" --description="Disable Pygame visualizer. Start WS server alongside companion. Open visualizer-web in a browser window on launch (or document how to open manually). Update settings.yaml with WS port config." --type=task --priority=2
```

Note the IDs returned and use them below.

---

## Task 1: WebSocket Event Server

**Files:**
- Create: `core/visualizer_ws.py`
- Modify: `main.py`

**Step 1: Install aiohttp**

```bash
source venv/bin/activate && pip install aiohttp
pip freeze | grep aiohttp >> requirements.txt
```

**Step 2: Write failing test**

```python
# tests/test_visualizer_ws.py
import asyncio
import json
import pytest
import aiohttp
from core.visualizer_ws import VisualizerWSServer

@pytest.mark.asyncio
async def test_server_starts_and_accepts_connection():
    server = VisualizerWSServer(host='127.0.0.1', port=8765)
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect('ws://127.0.0.1:8765/ws') as ws:
                assert not ws.closed
    finally:
        await server.stop()

@pytest.mark.asyncio
async def test_broadcast_emotion_event():
    server = VisualizerWSServer(host='127.0.0.1', port=8766)
    await server.start()
    received = []
    async def receive():
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect('ws://127.0.0.1:8766/ws') as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                received.append(json.loads(msg.data))
    task = asyncio.create_task(receive())
    await asyncio.sleep(0.1)
    await server.emit_emotion('happy', theme='dark')
    await asyncio.wait_for(task, timeout=3.0)
    await server.stop()
    assert received[0] == {'type': 'emotion', 'emotion': 'happy', 'theme': 'dark'}
```

**Step 3: Run test — confirm FAIL**

```bash
source venv/bin/activate && pip install pytest-asyncio
pytest tests/test_visualizer_ws.py -v
```
Expected: ImportError or AttributeError.

**Step 4: Implement core/visualizer_ws.py**

```python
"""WebSocket server for broadcasting emotion/state events to the web visualizer."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Set

from aiohttp import web

logger = logging.getLogger(__name__)


class VisualizerWSServer:
    """Lightweight WS server — emits events, visualizer clients subscribe."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._clients: Set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/ws", self._ws_handler)
        self._runner: Optional[web.AppRunner] = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Visualizer WS server started at ws://%s:%d/ws", self._host, self._port)

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    async def emit_emotion(self, emotion: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "emotion", "emotion": emotion, "theme": theme})

    async def emit_state(self, state: str, theme: str = "dark") -> None:
        await self._broadcast({"type": "state", "state": state, "theme": theme})

    async def emit_tag(self, tag: str) -> None:
        """Emit a custom contextual tag event."""
        await self._broadcast({"type": "tag", "tag": tag})

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(payload)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.debug("Visualizer client connected (%d total)", len(self._clients))
        try:
            async for _ in ws:
                pass  # We don't expect messages from the visualizer
        finally:
            self._clients.discard(ws)
            logger.debug("Visualizer client disconnected (%d remaining)", len(self._clients))
        return ws
```

**Step 5: Run test — confirm PASS**

```bash
pytest tests/test_visualizer_ws.py -v
```
Expected: 2 tests pass.

**Step 6: Wire into main.py**

Find where `DV3App.setup()` initializes subsystems. Add:

```python
from core.visualizer_ws import VisualizerWSServer
# In setup():
ws_port = self.settings.get('visualizer_ws_port', 8765)
self.visualizer_ws = VisualizerWSServer(port=ws_port)
await self.visualizer_ws.start()
```

Find where emotion events are dispatched to the Pygame visualizer and add a parallel WS emit:
```python
# After dispatching to animation_engine:
if hasattr(self, 'visualizer_ws'):
    asyncio.create_task(self.visualizer_ws.emit_emotion(emotion))
```

Add to `settings.yaml`:
```yaml
visualizer_ws_port: 8765
```

**Step 7: Commit**

```bash
git add core/visualizer_ws.py tests/test_visualizer_ws.py main.py config/settings.yaml requirements.txt
git commit -m "feat: add WebSocket event server for web visualizer"
```

---

## Task 2: Scaffold visualizer-web App

**Files:**
- Create: `visualizer-web/` (new Vite app)

**Step 1: Scaffold**

```bash
cd /home/shawn/projects/dv3
npm create vite@latest visualizer-web -- --template react-ts
cd visualizer-web
npm install
npm install -D tailwindcss autoprefixer postcss
npx tailwindcss init -p
```

**Step 2: Configure Tailwind**

In `visualizer-web/tailwind.config.js`:
```js
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
```

In `visualizer-web/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  background: #000;
  overflow: hidden;
}
```

**Step 3: Configure Vite to serve animations**

In `visualizer-web/vite.config.ts`:
```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    fs: {
      allow: ['.', path.resolve(__dirname, '../data/animations')],
    },
  },
});
```

In `visualizer-web/index.html`, add a symlink or alias — actually, configure the public dir to serve animations:

Actually, use Vite's `publicDir` or serve via a custom endpoint. Simplest: configure `server.fs.allow` and access files at `/@fs/home/shawn/projects/dv3/data/animations/`.

**Step 4: Basic fullscreen App.tsx**

```tsx
// visualizer-web/src/App.tsx
import './index.css';

export default function App() {
  return (
    <div className="w-full h-full bg-black flex items-center justify-center">
      <p className="text-white/20 text-sm">DV3 Visualizer — waiting for connection...</p>
    </div>
  );
}
```

**Step 5: Verify it runs**

```bash
cd visualizer-web && npm run dev
```
Open `http://localhost:5174` — should show black screen with placeholder text.

**Step 6: Commit**

```bash
git add visualizer-web/
git commit -m "feat: scaffold visualizer-web React app"
```

---

## Task 3: Manifest Loader + Animation Index

**Files:**
- Create: `visualizer-web/src/lib/manifest.ts`

```typescript
// visualizer-web/src/lib/manifest.ts

export interface ManifestAsset {
  file: string;
  theme: 'dark' | 'light' | 'both';
  emotions: string[];
  states: string[];
  tags: string[];
  title?: string;
}

export interface Manifest {
  version: 1;
  assets: ManifestAsset[];
}

export interface AnimationIndex {
  /** emotion → [absolute URL paths] */
  byEmotion: Record<string, string[]>;
  byState: Record<string, string[]>;
  byTag: Record<string, string[]>;
  all: string[];
}

/** Resolve a manifest filename to a URL the browser can load */
export function assetUrl(filename: string): string {
  // Vite serves the animations dir via fs.allow
  // Access pattern: /@fs/<absolute-path>
  return `/@fs/home/shawn/projects/dv3/data/animations/${filename}`;
}

export async function loadManifest(): Promise<Manifest | null> {
  try {
    // Fetch via the Vite fs.allow path
    const res = await fetch(assetUrl('manifest.json'));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export function buildIndex(manifest: Manifest, theme: 'dark' | 'light' = 'dark'): AnimationIndex {
  const byEmotion: Record<string, string[]> = {};
  const byState: Record<string, string[]> = {};
  const byTag: Record<string, string[]> = {};
  const all: string[] = [];

  for (const asset of manifest.assets) {
    if (asset.theme !== 'both' && asset.theme !== theme) continue;
    const url = assetUrl(asset.file);
    all.push(url);
    for (const e of asset.emotions) {
      (byEmotion[e] ??= []).push(url);
    }
    for (const s of asset.states) {
      (byState[s] ??= []).push(url);
    }
    for (const t of asset.tags) {
      (byTag[t] ??= []).push(url);
    }
  }

  return { byEmotion, byState, byTag, all };
}

export function pickAnimation(
  index: AnimationIndex,
  event: { type: 'emotion' | 'state' | 'tag'; emotion?: string; state?: string; tag?: string },
  theme: 'dark' | 'light' = 'dark'
): string | null {
  let pool: string[] = [];

  if (event.type === 'emotion' && event.emotion) {
    pool = index.byEmotion[event.emotion] ?? index.byEmotion['neutral'] ?? index.all;
  } else if (event.type === 'state' && event.state) {
    pool = index.byState[event.state] ?? index.byEmotion['neutral'] ?? index.all;
  } else if (event.type === 'tag' && event.tag) {
    pool = index.byTag[event.tag] ?? index.all;
  } else {
    pool = index.byEmotion['neutral'] ?? index.all;
  }

  if (pool.length === 0) return null;
  return pool[Math.floor(Math.random() * pool.length)];
}
```

**Step 2: Test manifest loading manually**

After starting the dev server and ensuring `data/animations/manifest.json` exists:
```bash
curl http://localhost:5174/@fs/home/shawn/projects/dv3/data/animations/manifest.json
```
Expected: JSON manifest content.

**Step 3: Commit**

```bash
git add visualizer-web/src/lib/manifest.ts
git commit -m "feat: manifest loader and animation index for visualizer"
```

---

## Task 4: Animation Player with Radial Gradient Mask

**Files:**
- Create: `visualizer-web/src/components/AnimationPlayer.tsx`
- Modify: `visualizer-web/src/App.tsx`

**Step 1: Create AnimationPlayer.tsx**

The key visual effect from the mockups:
- Black fullscreen background
- Animation centered, sized as % of screen height (default 45%)
- Radial gradient mask: black overlay with transparent ellipse cutout in center
- Crossfade between animations (300ms)

```tsx
// visualizer-web/src/components/AnimationPlayer.tsx
import * as React from 'react';
import { useState, useEffect, useRef } from 'react';

interface Props {
  /** URL of the current animation to display */
  src: string | null;
  /** Height as % of screen height (default 45) */
  sizePercent?: number;
  /** Gradient opacity 0–1 (default 0.85) */
  gradientOpacity?: number;
  /** How far gradient reaches inward as % of animation size (default 60) */
  gradientReach?: number;
  /** Crossfade duration in ms (default 300) */
  fadeDuration?: number;
}

export const AnimationPlayer: React.FC<Props> = ({
  src,
  sizePercent = 45,
  gradientOpacity = 0.85,
  gradientReach = 60,
  fadeDuration = 300,
}) => {
  // Double-buffer: current shows, next fades in
  const [currentSrc, setCurrentSrc] = useState<string | null>(src);
  const [nextSrc, setNextSrc] = useState<string | null>(null);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    if (src === currentSrc) return;
    if (!src) { setCurrentSrc(null); return; }

    // Start crossfade
    setNextSrc(src);
    setFading(true);

    const timer = setTimeout(() => {
      setCurrentSrc(src);
      setNextSrc(null);
      setFading(false);
    }, fadeDuration);

    return () => clearTimeout(timer);
  }, [src]);

  const animSize = `${sizePercent}vh`;

  // Radial gradient: transparent center, black edges
  // gradientReach controls how far in the black starts
  const innerStop = `${100 - gradientReach}%`;
  const gradientStyle = {
    background: `radial-gradient(ellipse ${animSize} ${animSize} at center, transparent 0%, transparent ${innerStop}, rgba(0,0,0,${gradientOpacity}) 100%)`,
  };

  return (
    <div className="relative w-full h-full bg-black overflow-hidden">
      {/* Layer 1: current animation */}
      {currentSrc && (
        <img
          src={currentSrc}
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 object-contain"
          style={{
            height: animSize,
            width: animSize,
            opacity: fading ? 0 : 1,
            transition: `opacity ${fadeDuration}ms ease-in-out`,
          }}
          alt=""
        />
      )}

      {/* Layer 2: next animation fading in */}
      {nextSrc && (
        <img
          src={nextSrc}
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 object-contain"
          style={{
            height: animSize,
            width: animSize,
            opacity: fading ? 1 : 0,
            transition: `opacity ${fadeDuration}ms ease-in-out`,
          }}
          alt=""
        />
      )}

      {/* Gradient mask overlay — covers entire screen, transparent cutout in center */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={gradientStyle}
      />
    </div>
  );
};
```

**Step 2: Wire into App.tsx for testing**

```tsx
// visualizer-web/src/App.tsx
import { AnimationPlayer } from './components/AnimationPlayer';
import { loadManifest, buildIndex, pickAnimation } from './lib/manifest';
import { useState, useEffect } from 'react';

export default function App() {
  const [currentSrc, setCurrentSrc] = useState<string | null>(null);
  const [status, setStatus] = useState('Loading manifest...');

  useEffect(() => {
    loadManifest().then((manifest) => {
      if (!manifest || manifest.assets.length === 0) {
        setStatus('No manifest found — tag animations in WebPew first');
        return;
      }
      const index = buildIndex(manifest, 'dark');
      const url = pickAnimation(index, { type: 'emotion', emotion: 'neutral' });
      setCurrentSrc(url);
      setStatus('');
    });
  }, []);

  return (
    <div className="w-screen h-screen bg-black">
      {status && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-white/20 text-sm">
          {status}
        </div>
      )}
      <AnimationPlayer src={currentSrc} />
    </div>
  );
}
```

**Step 3: Visual test**

Start dev server:
```bash
cd visualizer-web && npm run dev
```
Open `http://localhost:5174`. Verify:
- Black background, animation centered
- Edges fade into black (not a hard box)
- Animation loops

If no animations are tagged yet, the manifest will be empty — that's expected. Add one test animation manually:
```bash
# Temporarily put one WebP in data/animations/ and create a minimal manifest
echo '{"version":1,"assets":[{"file":"test.webp","theme":"dark","emotions":["neutral"],"states":[],"tags":[]}]}' > data/animations/manifest.json
cp data/animations/inbox/<any>.webp data/animations/test.webp
```
Then reload — animation should appear floating on black.

**Step 4: Commit**

```bash
git add visualizer-web/src/components/AnimationPlayer.tsx visualizer-web/src/App.tsx
git commit -m "feat: animation player with radial gradient mask and crossfade"
```

---

## Task 5: WebSocket Client + Event Handling

**Files:**
- Create: `visualizer-web/src/lib/wsClient.ts`
- Modify: `visualizer-web/src/App.tsx`

**Step 1: Create wsClient.ts**

```typescript
// visualizer-web/src/lib/wsClient.ts

export type VisualizerEvent =
  | { type: 'emotion'; emotion: string; theme: string }
  | { type: 'state'; state: string; theme: string }
  | { type: 'tag'; tag: string };

export type EventHandler = (event: VisualizerEvent) => void;

export class VisualizerWSClient {
  private ws: WebSocket | null = null;
  private handler: EventHandler;
  private reconnectDelay = 1000;
  private maxDelay = 30000;
  private stopped = false;

  constructor(private url: string, handler: EventHandler) {
    this.handler = handler;
  }

  connect(): void {
    if (this.stopped) return;
    try {
      this.ws = new WebSocket(this.url);
      this.ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as VisualizerEvent;
          this.handler(event);
        } catch { /* ignore malformed */ }
      };
      this.ws.onopen = () => {
        console.log('[visualizer] WS connected');
        this.reconnectDelay = 1000;  // Reset backoff on success
      };
      this.ws.onclose = () => {
        if (!this.stopped) this.scheduleReconnect();
      };
      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.stopped = true;
    this.ws?.close();
  }

  private scheduleReconnect(): void {
    setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
      this.connect();
    }, this.reconnectDelay);
  }
}
```

**Step 2: Update App.tsx to use WS**

```tsx
// visualizer-web/src/App.tsx
import { useEffect, useState, useRef } from 'react';
import { AnimationPlayer } from './components/AnimationPlayer';
import { loadManifest, buildIndex, pickAnimation, AnimationIndex } from './lib/manifest';
import { VisualizerWSClient } from './lib/wsClient';

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8765/ws';

export default function App() {
  const [currentSrc, setCurrentSrc] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const indexRef = useRef<AnimationIndex | null>(null);

  useEffect(() => {
    // Load manifest and build index
    loadManifest().then((manifest) => {
      if (manifest) {
        indexRef.current = buildIndex(manifest, 'dark');
        // Play neutral on load
        const url = pickAnimation(indexRef.current, { type: 'emotion', emotion: 'neutral' });
        setCurrentSrc(url);
      }
    });

    // Connect to companion WS
    const client = new VisualizerWSClient(WS_URL, (event) => {
      setConnected(true);
      if (!indexRef.current) return;
      const url = pickAnimation(indexRef.current, event as Parameters<typeof pickAnimation>[1]);
      if (url) setCurrentSrc(url);
    });
    client.connect();

    return () => client.disconnect();
  }, []);

  return (
    <div className="w-screen h-screen bg-black">
      <AnimationPlayer src={currentSrc} />
      {/* Dev indicator — remove for production */}
      {!connected && (
        <div className="absolute top-2 right-2 text-white/20 text-[10px]">
          waiting for companion...
        </div>
      )}
    </div>
  );
}
```

**Step 3: Create .env**

```bash
echo 'VITE_WS_URL=ws://localhost:8765/ws' > visualizer-web/.env.local
```

**Step 4: End-to-end test**

Start companion with debug:
```bash
source venv/bin/activate && python main.py --windowed --debug 2>&1 | grep -E "WS|emotion|visualizer" &
```

Start visualizer:
```bash
cd visualizer-web && npm run dev
```

Open `http://localhost:5174` in browser. Then test WS event manually:
```python
import asyncio, aiohttp, json
async def test():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('ws://localhost:8765/ws') as ws:
            # Actually — this is the server side. Use a test script to emit:
            pass
asyncio.run(test())
```

Or write a simple test sender:
```python
# scripts/test_ws_emit.py
import asyncio
import aiohttp
import json

async def main():
    emotions = ['happy', 'sad', 'alert', 'thinking', 'neutral']
    # Connect to companion's WS and verify it accepts connections
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect('ws://localhost:8765/ws') as ws:
                print("Connected to visualizer WS server")
                # Receive any broadcast
                await asyncio.sleep(1)
    except Exception as e:
        print(f"Could not connect: {e}")

asyncio.run(main())
```

Verify animations change when companion processes an emotion event.

**Step 5: Commit**

```bash
git add visualizer-web/src/lib/wsClient.ts visualizer-web/src/App.tsx visualizer-web/.env.local
git commit -m "feat: WS client connects to companion, updates animation on emotion events"
```

---

## Task 6: Wire Into main.py — Replace Pygame

**Files:**
- Modify: `main.py`
- Modify: `config/settings.yaml`

**Step 1: Make Pygame visualizer optional**

In `main.py`, find the Pygame init block. Wrap it:

```python
use_pygame = self.settings.get('use_pygame_visualizer', False)
if use_pygame:
    # existing Pygame init
    ...
else:
    logger.info("Pygame visualizer disabled — using web visualizer at http://localhost:5174")
    self.display = None
    self.animation_engine = None
```

**Step 2: Update settings.yaml**

```yaml
use_pygame_visualizer: false
visualizer_ws_port: 8765
```

**Step 3: Test companion boots without Pygame**

```bash
source venv/bin/activate && python main.py --debug 2>&1 | head -30
```
Expected: boots without Pygame window, logs "using web visualizer".

**Step 4: Document startup**

Add to `README.md` (or `CLAUDE.md` devnotes):
```
# Starting the visualizer
1. cd visualizer-web && npm run dev   (or build and serve)
2. Open http://localhost:5174 in browser (fullscreen with F11)
3. python main.py                     (companion connects and emits events)
```

**Step 5: Run all tests**

```bash
source venv/bin/activate && pytest tests/ -v
cd visualizer-web && npm run typecheck
```

**Step 6: Commit**

```bash
git add main.py config/settings.yaml
git commit -m "feat: replace Pygame visualizer with web visualizer — Pygame now opt-in via settings"
```

---

## Final Verification Checklist

- [ ] `pytest tests/ -v` — all pass
- [ ] `cd visualizer-web && npm run typecheck` — 0 errors
- [ ] Companion starts, logs "Visualizer WS server started"
- [ ] Opening `http://localhost:5174` shows black screen with animation playing
- [ ] Animation has no visible hard edges (gradient mask working)
- [ ] When companion processes a voice input, animation changes
- [ ] Disconnecting and reconnecting WS recovers automatically
- [ ] `data/animations/manifest.json` is loaded correctly (check console)

---

## Configuration Reference (settings.yaml)

```yaml
use_pygame_visualizer: false    # set true to revert to Pygame
visualizer_ws_port: 8765        # port for WS event server
visualizer_theme: dark          # dark or light
visualizer_size_percent: 45     # animation height as % of screen height
visualizer_gradient_opacity: 0.85
visualizer_gradient_reach: 60   # how far gradient extends inward (%)
visualizer_crossfade_ms: 300
```
