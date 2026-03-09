import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile, toBlobURL } from '@ffmpeg/util';

let ffmpeg: FFmpeg | null = null;

async function getFFmpeg(): Promise<FFmpeg> {
  if (ffmpeg) return ffmpeg;
  const ff = new FFmpeg();
  const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm';
  await ff.load({
    coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
    wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
  });
  ffmpeg = ff;
  return ff;
}

/**
 * Get or create the inbox/ subdirectory under animations/.
 */
export async function getOrCreateInboxDir(
  animationsHandle: FileSystemDirectoryHandle,
): Promise<FileSystemDirectoryHandle> {
  return await animationsHandle.getDirectoryHandle('inbox', { create: true });
}

/**
 * Copy a WebP (or any) file to the inbox directory by writing its raw bytes.
 */
export async function copyWebPToInbox(
  file: File,
  inboxHandle: FileSystemDirectoryHandle,
): Promise<void> {
  const bytes = await file.arrayBuffer();
  const fileHandle = await inboxHandle.getFileHandle(file.name, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(bytes);
  await writable.close();
}

/**
 * Convert a GIF to WebP using FFmpeg WASM and write the result to the inbox directory.
 * Returns the converted File object (type: image/webp).
 */
export async function convertGifToInbox(
  file: File,
  inboxHandle: FileSystemDirectoryHandle,
  onProgress?: (pct: number) => void,
): Promise<File> {
  const ff = await getFFmpeg();

  const inputName = 'input.gif';
  const outputName = 'output.webp';

  onProgress?.(5);

  const inputBytes = await fetchFile(file);
  await ff.writeFile(inputName, inputBytes);

  onProgress?.(20);

  // Set up a progress listener
  let progressCleanup: (() => void) | null = null;
  if (onProgress) {
    const handler = ({ progress }: { progress: number }) => {
      // FFmpeg progress goes 0→1; map to 20→90 range
      const pct = Math.round(20 + Math.min(progress, 1) * 70);
      onProgress(pct);
    };
    ff.on('progress', handler);
    progressCleanup = () => ff.off('progress', handler);
  }

  try {
    await ff.exec([
      '-i', inputName,
      '-c:v', 'libwebp_anim',
      '-lossless', '0',
      '-quality', '80',
      '-loop', '0',
      '-vsync', '0',
      outputName,
    ]);
  } finally {
    progressCleanup?.();
  }

  onProgress?.(92);

  const outputData = await ff.readFile(outputName);
  const outputBytes = outputData instanceof Uint8Array ? outputData : new Uint8Array(outputData as ArrayBuffer);

  // Clean up ffmpeg virtual FS
  try { await ff.deleteFile(inputName); } catch { /* ignore */ }
  try { await ff.deleteFile(outputName); } catch { /* ignore */ }

  const baseName = file.name.replace(/\.[^/.]+$/, '');
  const outName = `${baseName}.webp`;
  const convertedFile = new File([outputBytes], outName, { type: 'image/webp' });

  await copyWebPToInbox(convertedFile, inboxHandle);

  onProgress?.(100);

  return convertedFile;
}
