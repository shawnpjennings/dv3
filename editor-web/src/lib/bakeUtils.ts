/**
 * bakeUtils.ts — Inbox → Library bake-and-save pipeline.
 *
 * Applies a single InboxItem's edit stack via FFmpeg, writes the result
 * to animations/{filename}.webp in the connected directory, and
 * updates manifest.json.  Simpler than executeBatchExport — no ZIP,
 * no batch loop, no metadata embedding in the WebP stream.
 */

import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import type { InboxItem, LibraryAsset, Manifest, SavePayload } from '../types';

// ---------------------------------------------------------------------------
// Module-level FFmpeg singleton (shared with exportUtils if loaded first, but
// each module keeps its own ref — both lazy-initialise the same WASM binary).
// ---------------------------------------------------------------------------
let ffmpeg: FFmpeg | null = null;

// ---------------------------------------------------------------------------
// Helpers (copied from exportUtils so bakeUtils stays self-contained)
// ---------------------------------------------------------------------------

const isLikelyWebP = (bytes: Uint8Array): boolean => {
  if (bytes.length < 12) return false;
  const riff = String.fromCharCode(...bytes.slice(0, 4));
  const webp = String.fromCharCode(...bytes.slice(8, 12));
  return riff === 'RIFF' && webp === 'WEBP';
};

const hasAsciiChunk = (bytes: Uint8Array, token: string): boolean => {
  const enc = new TextEncoder().encode(token);
  for (let i = 0; i <= bytes.length - enc.length; i++) {
    let ok = true;
    for (let j = 0; j < enc.length; j++) {
      if (bytes[i + j] !== enc[j]) { ok = false; break; }
    }
    if (ok) return true;
  }
  return false;
};

const isAnimatedWebP = (bytes: Uint8Array): boolean =>
  isLikelyWebP(bytes) && (hasAsciiChunk(bytes, 'ANIM') || hasAsciiChunk(bytes, 'ANMF'));

const getImageDecoderCtor = () =>
  (window as unknown as {
    ImageDecoder?: new (init: { data: Uint8Array; type: string }) => {
      tracks: { selectedTrack?: { frameCount?: number } };
      decode: (opts: { frameIndex: number }) => Promise<{ image: { duration?: number; close?: () => void } }>;
      close?: () => void;
    };
  }).ImageDecoder;

const bitmapToPngBytes = async (bitmap: ImageBitmap): Promise<Uint8Array> => {
  if (typeof OffscreenCanvas !== 'undefined') {
    const off = new OffscreenCanvas(bitmap.width, bitmap.height);
    const ctx = off.getContext('2d');
    if (!ctx) throw new Error('Failed to create OffscreenCanvas context.');
    ctx.clearRect(0, 0, bitmap.width, bitmap.height);
    ctx.drawImage(bitmap, 0, 0);
    const blob = await off.convertToBlob({ type: 'image/png' });
    return new Uint8Array(await blob.arrayBuffer());
  }
  const canvas = document.createElement('canvas');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Failed to create canvas context.');
  ctx.clearRect(0, 0, bitmap.width, bitmap.height);
  ctx.drawImage(bitmap, 0, 0);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(b => b ? resolve(b) : reject(new Error('Frame canvas to PNG blob failed.')), 'image/png');
  });
  return new Uint8Array(await blob.arrayBuffer());
};

const decodeAnimatedToPngSequence = async (
  ff: FFmpeg,
  itemId: string,
  sourceBytes: Uint8Array,
  sourceType: string,
  maxFrames = 240
) => {
  const Decoder = getImageDecoderCtor();
  if (!Decoder) throw new Error('ImageDecoder is unavailable in this browser.');

  const decoder = new Decoder({ data: sourceBytes, type: sourceType });
  const declaredCount = decoder.tracks.selectedTrack?.frameCount;
  const count = declaredCount ? Math.min(declaredCount, maxFrames) : maxFrames;

  const cleanupFiles: string[] = [];
  const durationsMs: number[] = [];
  let frameCount = 0;

  for (let i = 0; i < count; i++) {
    let decoded;
    try { decoded = await decoder.decode({ frameIndex: i }); } catch { break; }

    const { image } = decoded;
    const bitmap = await createImageBitmap(image as unknown as CanvasImageSource);
    const pngBytes = await bitmapToPngBytes(bitmap);
    bitmap.close();

    const rawDuration = image.duration ?? 100000;
    const durationMs = rawDuration > 1000 ? rawDuration / 1000 : rawDuration;
    durationsMs.push(Math.max(10, Math.round(durationMs)));
    image.close?.();

    const frameName = `bkfrm_${itemId}_${String(i).padStart(5, '0')}.png`;
    await ff.writeFile(frameName, pngBytes);
    cleanupFiles.push(frameName);
    frameCount++;
  }

  decoder.close?.();
  if (frameCount === 0) throw new Error('No decodable animated frames found.');

  const avgMs = durationsMs.length > 0
    ? durationsMs.reduce((s, d) => s + d, 0) / durationsMs.length
    : 1000 / 24;
  const fps = Math.max(1, Math.min(60, Math.round(1000 / Math.max(1, avgMs))));

  return {
    cleanupFiles,
    inputArgs: ['-framerate', String(fps), '-i', `bkfrm_${itemId}_%05d.png`],
  };
};

// ---------------------------------------------------------------------------
// FFmpeg filter chain builder — adapted from executeBatchExport
// ---------------------------------------------------------------------------

const buildFilters = (item: InboxItem, sourceIsAnimated: boolean): string[] => {
  const activeEdits = item.editStack.slice(0, item.historyIndex + 1);

  const getEdit = (type: string, def: number | boolean): number | boolean => {
    for (let i = activeEdits.length - 1; i >= 0; i--) {
      if (activeEdits[i].type === type) return activeEdits[i].value;
    }
    return def;
  };

  const filters: string[] = [];

  const outfillEnabled = getEdit('OUTFILL_ENABLED', false) as boolean;
  const outfillColorNum = getEdit('OUTFILL_COLOR', 0x000000) as number;
  const bgColor = outfillEnabled
    ? `0x${Math.max(0, Math.min(0xffffff, Math.round(outfillColorNum))).toString(16).padStart(6, '0')}`
    : '0x000000';

  if (getEdit('SQUARE_CROP', false)) {
    filters.push(`crop='min(in_w,in_h)':'min(in_w,in_h)'`);
  }

  filters.push('scale=750:750:force_original_aspect_ratio=decrease');
  filters.push(`pad=750:750:(ow-iw)/2:(oh-ih)/2:${bgColor}`);

  const zoomOffset = getEdit('PADDING', 0) as number;
  const zoomFactor = Math.min(2.5, Math.max(0.15, 1 + zoomOffset / 300));
  if (zoomFactor !== 1) {
    const scaled = Math.max(2, Math.round(750 * zoomFactor));
    filters.push(`scale=${scaled}:${scaled}:flags=lanczos`);
    if (zoomFactor > 1) {
      filters.push('crop=750:750:(in_w-750)/2:(in_h-750)/2');
    } else {
      filters.push(`pad=750:750:(ow-iw)/2:(oh-ih)/2:${bgColor}`);
    }
  }

  const posX = getEdit('POSITION_X', 0) as number;
  const posY = getEdit('POSITION_Y', 0) as number;
  if (posX !== 0 || posY !== 0) {
    const padW = 750 + 2 * Math.abs(posX);
    const padH = 750 + 2 * Math.abs(posY);
    const padX = Math.abs(posX);
    const padY = Math.abs(posY);
    const cropX = Math.abs(posX) - posX;
    const cropY = Math.abs(posY) - posY;
    filters.push(`pad=${padW}:${padH}:${padX}:${padY}:${bgColor}`);
    filters.push(`crop=750:750:${cropX}:${cropY}`);
  }

  if (getEdit('FLIP_H', false)) filters.push('hflip');
  if (getEdit('FLIP_V', false)) filters.push('vflip');

  const bUI = getEdit('BRIGHTNESS', 100) as number;
  const cUI = getEdit('CONTRAST', 100) as number;
  const sUI = getEdit('SATURATION', 100) as number;
  const hue = getEdit('HUE', 0) as number;
  const grayscaleEnabled = getEdit('GRAYSCALE', false);
  const invertEnabled = getEdit('INVERT', false);

  if (bUI !== 100 || cUI !== 100) {
    const bf = Math.max(0, bUI / 100).toFixed(4);
    const cf = Math.max(0, cUI / 100).toFixed(4);
    const expr = `clip((val*${bf}-128)*${cf}+128,0,255)`;
    filters.push(`lutrgb=r='${expr}':g='${expr}':b='${expr}'`);
  }

  if (invertEnabled) filters.push('negate');
  if (grayscaleEnabled) filters.push('hue=s=0');

  if (hue !== 0 || sUI !== 100) {
    const saturation = sUI / 100;
    const absHue = Math.abs(hue);
    const normalized = absHue / 180;
    const damping = Math.max(0.28, 1 - 3 * normalized * normalized);
    const hueForExport = Math.round(hue * damping);
    filters.push(`hue=h=${hueForExport}:s=${saturation}`);
  }

  if (getEdit('BG_SWAP', false) && !sourceIsAnimated) {
    const thresholdUi = getEdit('BG_THRESHOLD', 24) as number;
    const threshold = Math.max(0, Math.min(255, Math.round((thresholdUi / 100) * 255)));
    const colorNum = getEdit('BG_COLOR', 0xffffff) as number;
    const color = Math.max(0, Math.min(0xffffff, Math.round(colorNum)));
    const r = (color >> 16) & 255;
    const g = (color >> 8) & 255;
    const b = color & 255;
    filters.push(`lutrgb=r='if(lt(val,${threshold}),${r},val)':g='if(lt(val,${threshold}),${g},val)':b='if(lt(val,${threshold}),${b},val)'`);
  }

  if (getEdit('VIGNETTE', false)) filters.push('vignette=PI/4');

  if (getEdit('CIRCLE_MASK', false)) {
    const radius = 375;
    const center = 375;
    const circleExpr = `if(gt((X-${center})*(X-${center})+(Y-${center})*(Y-${center}),${radius * radius}),0,CHAN)`;
    filters.push(
      `geq=` +
      `r='${circleExpr.replace('CHAN', 'r(X,Y)')}':` +
      `g='${circleExpr.replace('CHAN', 'g(X,Y)')}':` +
      `b='${circleExpr.replace('CHAN', 'b(X,Y)')}':` +
      `a='alpha(X,Y)'`
    );
  }

  const speed = getEdit('SPEED', 1) as number;
  const speedFactor = speed > 0 ? speed : 1;
  if (speedFactor !== 1) {
    filters.push(`fps=${Math.max(1, Math.round(24 * speedFactor))}`);
    filters.push(`setpts=${1 / speedFactor}*PTS`);
  }
  if (getEdit('REVERSE', false)) filters.push('reverse');

  filters.push('format=rgba');

  return filters;
};

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Bake an InboxItem's edit stack into a final WebP and write it to the
 * library directory.  Returns the new LibraryAsset (with previewUrl set).
 *
 * @param item             The InboxItem to bake.
 * @param payload          Tag/filename data from the TagPanel.
 * @param animationsHandle FileSystemDirectoryHandle pointing at
 *                         animations/ (the root the user connected).
 */
export async function bakeAndSave(
  item: InboxItem,
  payload: SavePayload,
  animationsHandle: FileSystemDirectoryHandle,
): Promise<LibraryAsset> {

  const outName = payload.filename.endsWith('.webp')
    ? payload.filename
    : `${payload.filename}.webp`;

  // -------------------------------------------------------------------------
  // 1. Bake edits with FFmpeg (or passthrough if no edits applied)
  // -------------------------------------------------------------------------
  const activeEdits = item.editStack.slice(0, item.historyIndex + 1);
  const hasEdits = activeEdits.length > 0;

  let bakedBytes: Uint8Array;

  if (!hasEdits) {
    // Fast path: no edits — read original bytes directly.
    bakedBytes = new Uint8Array(await item.file.arrayBuffer());
  } else {
    // Lazy-init FFmpeg.
    if (!ffmpeg) {
      ffmpeg = new FFmpeg();
      await ffmpeg.load();
    }
    const ff = ffmpeg;

    const ffmpegLogTail: string[] = [];
    ff.on('log', ({ message }: { message: string }) => {
      if (!message) return;
      ffmpegLogTail.push(message.trim());
      if (ffmpegLogTail.length > 60) ffmpegLogTail.shift();
    });

    const itemId = item.id;
    const ext = item.file.name.split('.').pop() || 'webp';
    const inputName = `bkin_${itemId}.${ext}`;
    const outputName = `bkout_${itemId}.webp`;

    const sourceBytes = new Uint8Array(await item.file.arrayBuffer());
    const sourceIsAnimated =
      item.type === 'image/gif' ||
      (item.type === 'image/webp' && isAnimatedWebP(sourceBytes));

    // Clean up any stale temp files from previous runs.
    for (const name of [inputName, outputName]) {
      try { await ff.deleteFile(name); } catch { /* ok */ }
    }

    const cleanupFiles: string[] = [];
    let inputArgs: string[];

    if (sourceIsAnimated) {
      try {
        const sequence = await decodeAnimatedToPngSequence(ff, itemId, sourceBytes, item.type);
        cleanupFiles.push(...sequence.cleanupFiles);
        inputArgs = sequence.inputArgs;
      } catch {
        // Fallback: pass raw file to FFmpeg directly.
        await ff.writeFile(inputName, await fetchFile(item.file));
        cleanupFiles.push(inputName);
        inputArgs = ['-i', inputName];
      }
    } else {
      await ff.writeFile(inputName, await fetchFile(item.file));
      cleanupFiles.push(inputName);
      inputArgs = ['-i', inputName];
    }

    const filters = buildFilters(item, sourceIsAnimated);

    const toErrorMessage = (err: unknown) =>
      err instanceof Error ? err.message : String(err);

    const buildArgs = (codec: 'libwebp_anim' | 'libwebp', quality: string) => {
      const args: string[] = [...inputArgs];
      if (filters.length > 0) args.push('-vf', filters.join(','));
      args.push('-c:v', codec, '-lossless', '0', '-quality', quality,
        '-loop', '0', '-an', outputName);
      return args;
    };

    const runAndRead = async (codec: 'libwebp_anim' | 'libwebp', quality: string) => {
      const exitCode = await ff.exec(buildArgs(codec, quality));
      if (exitCode !== 0) {
        const tail = ffmpegLogTail.slice(-8).join(' | ');
        throw new Error(`FFmpeg exited ${exitCode} (${codec}). ${tail}`.trim());
      }
      const data = await ff.readFile(outputName);
      const bytes = data instanceof Uint8Array ? Uint8Array.from(data) : new Uint8Array();
      if (!isLikelyWebP(bytes) || bytes.length === 0) {
        const tail = ffmpegLogTail.slice(-8).join(' | ');
        throw new Error(`Output is empty or not a valid WebP. ${tail}`.trim());
      }
      if (sourceIsAnimated && !isAnimatedWebP(bytes)) {
        throw new Error('Animation frames were lost during encoding.');
      }
      return bytes;
    };

    try {
      bakedBytes = await runAndRead('libwebp_anim', '90');
    } catch (e1) {
      try {
        try { await ff.deleteFile(outputName); } catch { /* ok */ }
        bakedBytes = await runAndRead('libwebp_anim', '85');
      } catch (e2) {
        try {
          try { await ff.deleteFile(outputName); } catch { /* ok */ }
          bakedBytes = await runAndRead('libwebp', '85');
        } catch (e3) {
          throw new Error(
            `Bake failed: ${toErrorMessage(e1)} | ` +
            `Fallback1: ${toErrorMessage(e2)} | ` +
            `Fallback2: ${toErrorMessage(e3)}`
          );
        }
      }
    }

    // Cleanup FFmpeg FS.
    for (const name of [...cleanupFiles, outputName]) {
      try { await ff.deleteFile(name); } catch { /* ok */ }
    }
  }

  // -------------------------------------------------------------------------
  // 2. Write baked WebP to animations/library/{outName}
  // -------------------------------------------------------------------------
  const libraryHandle = await animationsHandle.getDirectoryHandle('library', { create: true });
  const fileHandle = await libraryHandle.getFileHandle(outName, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(new Blob([bakedBytes.buffer as ArrayBuffer], { type: 'image/webp' }));
  await writable.close();

  // -------------------------------------------------------------------------
  // 3. Read existing manifest.json (or start fresh)
  // -------------------------------------------------------------------------
  let manifest: Manifest = { version: 1, assets: [] };
  try {
    const mh = await animationsHandle.getFileHandle('manifest.json');
    const mf = await mh.getFile();
    manifest = JSON.parse(await mf.text()) as Manifest;
    if (!Array.isArray(manifest.assets)) manifest.assets = [];
  } catch {
    // First run — manifest doesn't exist yet, use the empty default above.
  }

  // -------------------------------------------------------------------------
  // 4. Build/update manifest entry
  // -------------------------------------------------------------------------
  const newEntry: LibraryAsset = {
    file: `library/${outName}`,
    theme: payload.theme,
    emotions: payload.emotions,
    states: payload.states,
    tags: payload.tags,
    title: payload.title,
    notes: payload.notes,
  };

  const idx = manifest.assets.findIndex(a => a.file === `library/${outName}`);
  if (idx >= 0) {
    manifest.assets[idx] = newEntry;
  } else {
    manifest.assets.push(newEntry);
  }

  // -------------------------------------------------------------------------
  // 5. Write manifest.json back
  // -------------------------------------------------------------------------
  const manifestHandle = await animationsHandle.getFileHandle('manifest.json', { create: true });
  const mWritable = await manifestHandle.createWritable();
  const manifestBytes = new TextEncoder().encode(JSON.stringify(manifest, null, 2));
  await mWritable.write(new Blob([manifestBytes.buffer as ArrayBuffer], { type: 'application/json' }));
  await mWritable.close();

  // -------------------------------------------------------------------------
  // 6. Delete inbox original (best-effort)
  // -------------------------------------------------------------------------
  try {
    const inboxHandle = await animationsHandle.getDirectoryHandle('inbox');
    await inboxHandle.removeEntry(item.file.name);
  } catch {
    // inbox sub-dir may not exist, or file already removed — that's fine.
  }

  // -------------------------------------------------------------------------
  // 7. Return LibraryAsset with a fresh preview URL
  // -------------------------------------------------------------------------
  const previewUrl = URL.createObjectURL(
    new Blob([bakedBytes.buffer as ArrayBuffer], { type: 'image/webp' })
  );
  return { ...newEntry, previewUrl };
}
