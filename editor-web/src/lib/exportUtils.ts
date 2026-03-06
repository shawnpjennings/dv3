import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';
import { Asset, EditorSettings } from '../types';

let ffmpeg: FFmpeg | null = null;

const sanitizeName = (name: string) => name.replace(/[^a-zA-Z0-9._-]+/g, '_');
const sanitizeMeta = (value: string) => value.replace(/[^a-zA-Z0-9._ -]+/g, '_');

const hasAsciiChunk = (bytes: Uint8Array, token: string) => {
  const enc = new TextEncoder().encode(token);
  for (let i = 0; i <= bytes.length - enc.length; i++) {
    let ok = true;
    for (let j = 0; j < enc.length; j++) {
      if (bytes[i + j] !== enc[j]) {
        ok = false;
        break;
      }
    }
    if (ok) return true;
  }
  return false;
};

const isLikelyWebP = (bytes: Uint8Array) => {
  if (bytes.length < 12) return false;
  const riff = String.fromCharCode(...bytes.slice(0, 4));
  const webp = String.fromCharCode(...bytes.slice(8, 12));
  return riff === 'RIFF' && webp === 'WEBP';
};

const isAnimatedWebP = (bytes: Uint8Array) => {
  if (!isLikelyWebP(bytes)) return false;
  return hasAsciiChunk(bytes, 'ANIM') || hasAsciiChunk(bytes, 'ANMF');
};

const toErrorMessage = (err: unknown) => {
  if (err instanceof Error) return err.message;
  return String(err);
};

const getImageDecoderCtor = () => {
  return (window as unknown as {
    ImageDecoder?: new (init: { data: Uint8Array; type: string }) => {
      tracks: { selectedTrack?: { frameCount?: number } };
      decode: (opts: { frameIndex: number }) => Promise<{ image: { duration?: number; close?: () => void } }>;
      close?: () => void;
    };
  }).ImageDecoder;
};

const bitmapToPngBytes = async (bitmap: ImageBitmap): Promise<Uint8Array> => {
  if (typeof OffscreenCanvas !== 'undefined') {
    const off = new OffscreenCanvas(bitmap.width, bitmap.height);
    const ctx = off.getContext('2d');
    if (!ctx) throw new Error('Failed to create canvas context for frame conversion.');
    ctx.clearRect(0, 0, bitmap.width, bitmap.height);
    ctx.drawImage(bitmap, 0, 0);
    const blob = await off.convertToBlob({ type: 'image/png' });
    return new Uint8Array(await blob.arrayBuffer());
  }

  if (typeof document === 'undefined') {
    throw new Error('No canvas API available for frame conversion.');
  }

  const canvas = document.createElement('canvas');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Failed to create canvas context for frame conversion.');
  ctx.clearRect(0, 0, bitmap.width, bitmap.height);
  ctx.drawImage(bitmap, 0, 0);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((b) => {
      if (b) resolve(b);
      else reject(new Error('Failed to convert frame canvas to PNG blob.'));
    }, 'image/png');
  });

  return new Uint8Array(await blob.arrayBuffer());
};

const decodeAnimatedToPngSequence = async (
  ff: FFmpeg,
  assetId: string,
  sourceBytes: Uint8Array,
  sourceType: string,
  maxFrames = 240
) => {
  const Decoder = getImageDecoderCtor();
  if (!Decoder) {
    throw new Error('ImageDecoder is unavailable in this browser.');
  }

  const decoder = new Decoder({ data: sourceBytes, type: sourceType });
  const declaredCount = decoder.tracks.selectedTrack?.frameCount;
  const count = declaredCount ? Math.min(declaredCount, maxFrames) : maxFrames;

  const cleanupFiles: string[] = [];
  const durationsMs: number[] = [];
  let frameCount = 0;

  for (let i = 0; i < count; i++) {
    let decoded;
    try {
      decoded = await decoder.decode({ frameIndex: i });
    } catch {
      break;
    }

    const { image } = decoded;
    const bitmap = await createImageBitmap(image as unknown as CanvasImageSource);
    const pngBytes = await bitmapToPngBytes(bitmap);
    bitmap.close();

    const rawDuration = image.duration ?? 100000;
    const durationMs = rawDuration > 1000 ? rawDuration / 1000 : rawDuration;
    durationsMs.push(Math.max(10, Math.round(durationMs)));
    image.close?.();

    const frameName = `frm_${assetId}_${String(i).padStart(5, '0')}.png`;
    await ff.writeFile(frameName, pngBytes);
    cleanupFiles.push(frameName);
    frameCount++;
  }

  decoder.close?.();

  if (frameCount === 0) {
    throw new Error('No decodable animated frames found.');
  }

  const avgMs = durationsMs.length > 0
    ? durationsMs.reduce((sum, d) => sum + d, 0) / durationsMs.length
    : 1000 / 24;
  const fps = Math.max(1, Math.min(60, Math.round(1000 / Math.max(1, avgMs))));

  return {
    cleanupFiles,
    inputArgs: ['-framerate', String(fps), '-i', `frm_${assetId}_%05d.png`],
  };
};

export const executeBatchExport = async (
  assetsToExport: Asset[],
  settings: EditorSettings,
  onProgress: (status: string, progress: number) => void
) => {
  if (!ffmpeg) {
    onProgress('Initializing FFmpeg engine...', 0);
    ffmpeg = new FFmpeg();
    await ffmpeg.load();
  }

  const ff = ffmpeg;
  if (!ff) {
    throw new Error('FFmpeg engine failed to initialize.');
  }

  const ffmpegLogTail: string[] = [];
  ff.on('log', ({ message }: { message: string }) => {
    if (!message) return;
    ffmpegLogTail.push(message.trim());
    if (ffmpegLogTail.length > 60) ffmpegLogTail.shift();
  });

  const total = assetsToExport.length;
  const encodedOutputs: Array<{ name: string; bytes: Uint8Array; mimeType: string }> = [];

  for (let i = 0; i < total; i++) {
    ffmpegLogTail.length = 0;
    const asset = assetsToExport[i];
    const progressBase = Math.round((i / total) * 100);
    onProgress(`Processing ${asset.name}...`, progressBase);

    // Calculate active edits
    const activeEdits = asset.editStack.slice(0, asset.historyIndex + 1);
    const getEdit = (type: string, def: number | boolean) => {
      for (let idx = activeEdits.length - 1; idx >= 0; idx--) {
        if (activeEdits[idx].type === type) {
          return activeEdits[idx].value;
        }
      }
      return def;
    };

    const ext = asset.originalFile.name.split('.').pop() || 'gif';
    const inputName = `in_${asset.id}.${ext}`;
    const outputName = `out_${asset.id}.webp`;
    const metadataPayload = {
      title: asset.title || asset.name,
      emotion: asset.emotion,
      context: asset.context,
      notes: asset.notes,
      linkedVariantId: asset.linkedVariantId,
      originalType: asset.type,
      dv3_ready: true,
      exportRoot: settings.exportRoot,
      exportDate: new Date().toISOString(),
    };

    const sourceBytes = new Uint8Array(await asset.originalFile.arrayBuffer());
    const sourceIsAnimated = asset.type === 'image/gif' || (asset.type === 'image/webp' && isAnimatedWebP(sourceBytes));

    const cleanupFiles: string[] = [];
    let inputArgs: string[] = [];

    // Ensure stale temp files do not poison re-runs in wasm FS.
    try {
      await ff.deleteFile(inputName);
    } catch {
      // Ignore if file does not exist.
    }
    try {
      await ff.deleteFile(outputName);
    } catch {
      // Ignore if file does not exist.
    }

    // 1. Prepare FFmpeg input source.
    if (sourceIsAnimated) {
      try {
        onProgress(`Decoding frames for ${asset.name}...`, progressBase);
        const sequence = await decodeAnimatedToPngSequence(ff, asset.id, sourceBytes, asset.type);
        cleanupFiles.push(...sequence.cleanupFiles);
        inputArgs = sequence.inputArgs;
      } catch {
        // Fallback to direct file input if frame decode path is unavailable.
        await ff.writeFile(inputName, await fetchFile(asset.originalFile));
        cleanupFiles.push(inputName);
        inputArgs = ['-i', inputName];
      }
    } else {
      await ff.writeFile(inputName, await fetchFile(asset.originalFile));
      cleanupFiles.push(inputName);
      inputArgs = ['-i', inputName];
    }

    // 2. Build FFmpeg Video Filters (-vf)
    const filters: string[] = [];

    // Resolve outfill color up front so all pad calls can use it.
    const outfillEnabled = getEdit('OUTFILL_ENABLED', false) as boolean;
    const outfillColorNum = getEdit('OUTFILL_COLOR', 0x000000) as number;
    const bgColor = outfillEnabled
      ? `0x${Math.max(0, Math.min(0xffffff, Math.round(outfillColorNum))).toString(16).padStart(6, '0')}`
      : '0x000000';

    // Layout & Transforms
    if (getEdit('SQUARE_CROP', false)) {
      filters.push(`crop='min(in_w,in_h)':'min(in_w,in_h)'`);
    }

    // Normalize to the 750x750 editor canvas model first.
    filters.push('scale=750:750:force_original_aspect_ratio=decrease');
    filters.push(`pad=750:750:(ow-iw)/2:(oh-ih)/2:${bgColor}`);

    // PADDING is used as a bidirectional zoom offset:
    // negative = zoom out, positive = zoom in.
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

    // Position shift: translate the image within the 750x750 canvas.
    // Expand canvas by 2× the offset, crop back to 750×750 from the correct origin.
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

    // Color & Tone
    const bUI = getEdit('BRIGHTNESS', 100) as number;
    const cUI = getEdit('CONTRAST', 100) as number;
    const sUI = getEdit('SATURATION', 100) as number;
    const hue = getEdit('HUE', 0) as number;
    const grayscaleEnabled = getEdit('GRAYSCALE', false);
    const invertEnabled = getEdit('INVERT', false);

    // Match preview order and tone math as closely as possible:
    // brightness/contrast -> invert -> grayscale -> hue/saturation.
    // CSS brightness() is multiplicative, unlike FFmpeg eq brightness (additive),
    // so we use LUT math to avoid washout at high values.
    if (bUI !== 100 || cUI !== 100) {
      const brightnessFactor = Math.max(0, bUI / 100);
      const contrastFactor = Math.max(0, cUI / 100);
      const bf = brightnessFactor.toFixed(4);
      const cf = contrastFactor.toFixed(4);
      const expr = `clip((val*${bf}-128)*${cf}+128,0,255)`;
      filters.push(`lutrgb=r='${expr}':g='${expr}':b='${expr}'`);
    }

    if (invertEnabled) filters.push('negate');

    if (grayscaleEnabled) {
      // Match editor preview behavior: grayscale conversion without hard thresholding.
      filters.push('hue=s=0');
    }

    if (hue !== 0 || sUI !== 100) {
      const saturation = sUI / 100; // 0-200 -> 0 to 2
      // FFmpeg hue is stronger than CSS hue-rotate, especially at higher magnitudes.
      // Use quadratic damping so +/-25 stays close while +/-75 is compressed harder.
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

      // Fast win: replace near-black channel values with target color channels.
      filters.push(`lutrgb=r='if(lt(val,${threshold}),${r},val)':g='if(lt(val,${threshold}),${g},val)':b='if(lt(val,${threshold}),${b},val)'`);
    } else if (getEdit('BG_SWAP', false) && sourceIsAnimated) {
      onProgress(`Skipping beta background swap for animated file ${asset.name}...`, progressBase);
    }

    if (getEdit('VIGNETTE', false)) filters.push('vignette=PI/4');

    if (getEdit('CIRCLE_MASK', false)) {
      // Bake the circular black matte exactly into exported pixels.
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

    // Temporal
    const speed = getEdit('SPEED', 1) as number;
    const speedFactor = speed > 0 ? speed : 1;
    if (speedFactor !== 1) {
      // Apply both frame timing and PTS scaling for better compatibility across GIF/WebP inputs.
      filters.push(`fps=${Math.max(1, Math.round(24 * speedFactor))}`);
      filters.push(`setpts=${1 / speedFactor}*PTS`);
    }
    if (getEdit('REVERSE', false)) filters.push('reverse');

    // Preserve channel fidelity before encoding to avoid grayscale/contrast drift.
    filters.push('format=rgba');

    const buildArgs = (
      codec: 'libwebp_anim' | 'libwebp',
      mode: 'full' | 'no-meta' | 'minimal'
    ) => {
      const args: string[] = [];
      args.push(...inputArgs);

      if (filters.length > 0) {
        args.push('-vf', filters.join(','));
      }

      if (mode === 'full') {
        // Write metadata into WebP. We store compact metadata in comment.
        const title = sanitizeMeta(asset.title || asset.name);
        const comment = [
          `dv3_ready=1`,
          `emotion=${sanitizeMeta(metadataPayload.emotion)}`,
          `context=${sanitizeMeta(metadataPayload.context)}`,
          `title=${title}`,
          `exportDate=${sanitizeMeta(metadataPayload.exportDate)}`,
        ].join('|');
        args.push('-metadata', `title=${title}`);
        args.push('-metadata', `comment=${comment}`);
      }

      if (mode === 'minimal') {
        args.push('-c:v', codec, '-lossless', '0', '-quality', '85', '-loop', '0', '-an', outputName);
      } else {
        args.push(
          '-c:v',
          codec,
          '-lossless',
          '0',
          '-quality',
          '90',
          '-compression_level',
          '1',
          '-loop',
          '0',
          '-vsync',
          '0',
          '-an',
          outputName
        );
      }
      return args;
    };

    const runAndRead = async (
      codec: 'libwebp_anim' | 'libwebp',
      mode: 'full' | 'no-meta' | 'minimal'
    ) => {
      const exitCode = await ff.exec(buildArgs(codec, mode));
      if (exitCode !== 0) {
        const tail = ffmpegLogTail.slice(-8).join(' | ');
        throw new Error(`FFmpeg exited with code ${exitCode} using ${codec} (${mode}). ${tail ? `Logs: ${tail}` : ''}`.trim());
      }
      const data = await ff.readFile(outputName);
      const webpBytes = data instanceof Uint8Array ? Uint8Array.from(data) : new Uint8Array();
      if (!isLikelyWebP(webpBytes) || webpBytes.length === 0) {
        const tail = ffmpegLogTail.slice(-8).join(' | ');
        throw new Error(`Encoded output for ${asset.name} is empty or invalid. ${tail ? `Logs: ${tail}` : ''}`.trim());
      }
      if (sourceIsAnimated && !isAnimatedWebP(webpBytes)) {
        throw new Error(`Animation was lost for ${asset.name}.`);
      }
      return webpBytes;
    };

    // 4/5. Run encoding with staged fallbacks for compatibility.
    let webpBytes: Uint8Array;
    try {
      webpBytes = await runAndRead('libwebp_anim', 'full');
    } catch (primaryErr) {
      onProgress(`Retrying ${asset.name} with compatibility settings...`, progressBase);
      try {
        // Best-effort cleanup before retry.
        try {
          await ff.deleteFile(outputName);
        } catch {
          // Ignore if file does not exist.
        }
        webpBytes = await runAndRead('libwebp_anim', 'no-meta');
      } catch (fallbackErr1) {
        try {
          try {
            await ff.deleteFile(outputName);
          } catch {
            // Ignore if file does not exist.
          }
          webpBytes = await runAndRead('libwebp', 'minimal');
        } catch (fallbackErr2) {
          throw new Error(
            `Failed to export ${asset.name}: ${toErrorMessage(primaryErr)} | ` +
            `Fallback1: ${toErrorMessage(fallbackErr1)} | Fallback2: ${toErrorMessage(fallbackErr2)}. ` +
            `No output file was written.`
          );
        }
      }
    }

    encodedOutputs.push({
      name: `${sanitizeName(asset.name)}.webp`,
      bytes: webpBytes,
      mimeType: 'image/webp',
    });

    // Cleanup FFmpeg FS to prevent memory leaks (best-effort)
    for (const tempName of cleanupFiles) {
      try {
        await ff.deleteFile(tempName);
      } catch {
        // Ignore missing file cleanup errors.
      }
    }
    try {
      await ff.deleteFile(outputName);
    } catch {
      // Ignore missing file cleanup errors.
    }
  }

  if (encodedOutputs.length === 0) {
    throw new Error('No files were exported.');
  }

  // Build manifest entries for all exported assets.
  const manifestEntries = assetsToExport.map((asset, i) => {
    const emotions = [asset.emotion, ...(asset.additionalEmotions ?? [])].filter(Boolean);
    return {
      id: asset.id,
      filename: encodedOutputs[i]?.name ?? `${sanitizeName(asset.name)}.webp`,
      emotions: Array.from(new Set(emotions)),
      contexts: [asset.context].filter(Boolean),
      theme: asset.theme ?? 'dark',
      title: asset.title || asset.name,
      notes: asset.notes || '',
      exportedAt: new Date().toISOString(),
    };
  });

  const manifest = {
    version: 1,
    generated: new Date().toISOString(),
    exportRoot: settings.exportRoot,
    assets: manifestEntries,
  };
  const manifestJson = JSON.stringify(manifest, null, 2);
  const manifestBytes = new TextEncoder().encode(manifestJson);

  if (encodedOutputs.length === 1) {
    const only = encodedOutputs[0];
    const safeBytes = new Uint8Array(only.bytes.length);
    safeBytes.set(only.bytes);

    // For single exports: download WebP + manifest as zip.
    const zip = new JSZip();
    zip.file(only.name, safeBytes);
    zip.file('manifest.json', manifestBytes);
    const zipBlob = await zip.generateAsync({ type: 'blob' });
    saveAs(zipBlob, `${only.name.replace('.webp', '')}_export.zip`);
    onProgress('Complete!', 100);
    return;
  }

  onProgress('Packaging batch export...', 99);
  const zip = new JSZip();
  encodedOutputs.forEach((file) => {
    zip.file(file.name, file.bytes);
  });
  zip.file('manifest.json', manifestBytes);
  const zipBlob = await zip.generateAsync({ type: 'blob' });
  saveAs(zipBlob, 'DV3_Animations_Export.zip');
  onProgress('Complete!', 100);
};
