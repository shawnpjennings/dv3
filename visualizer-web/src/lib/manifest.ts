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
  byEmotion: Record<string, string[]>;
  byState: Record<string, string[]>;
  byTag: Record<string, string[]>;
  all: string[];
}

export type VisualizerEvent =
  | { type: 'emotion'; emotion: string; theme?: string }
  | { type: 'state'; state: string; theme?: string }
  | { type: 'tag'; tag: string };

const ANIMATIONS_BASE = '/@fs/home/shawn/projects/dv3/animations';

/** Resolve a manifest filename to a URL the browser can load via Vite's fs.allow */
export function assetUrl(filename: string): string {
  return `${ANIMATIONS_BASE}/${filename}`;
}

export async function loadManifest(): Promise<Manifest | null> {
  try {
    const res = await fetch(`${ANIMATIONS_BASE}/manifest.json`);
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
    for (const e of asset.emotions) (byEmotion[e] ??= []).push(url);
    for (const s of asset.states) (byState[s] ??= []).push(url);
    for (const t of asset.tags) (byTag[t] ??= []).push(url);
  }

  return { byEmotion, byState, byTag, all };
}

export function pickAnimation(
  index: AnimationIndex,
  event: VisualizerEvent,
  exclude?: string | null,
): string | null {
  let pool: string[] = [];
  if (event.type === 'emotion') {
    pool = index.byEmotion[event.emotion] ?? index.byEmotion['neutral'] ?? index.all;
  } else if (event.type === 'state') {
    pool = index.byState[event.state] ?? index.byEmotion['neutral'] ?? index.all;
  } else if (event.type === 'tag') {
    pool = index.byTag[event.tag] ?? index.all;
  }
  if (pool.length === 0) return null;
  // Avoid repeating the same animation when possible
  if (exclude && pool.length > 1) {
    pool = pool.filter((u) => u !== exclude);
  }
  return pool[Math.floor(Math.random() * pool.length)];
}
