import * as React from 'react';
import { useState, useEffect } from 'react';
import { Layers } from 'lucide-react';
import type { LibraryAsset } from '../types';

interface LibraryPanelProps {
  assets: LibraryAsset[];
  activeFile: string | null;
  dirHandle: FileSystemDirectoryHandle | null;
  onSelect: (file: string) => void;
}

/**
 * Load a preview object URL for a LibraryAsset from the directory handle.
 * Returns the URL string, or null on failure.
 */
async function loadPreviewUrl(
  handle: FileSystemDirectoryHandle,
  filename: string,
): Promise<string | null> {
  try {
    // Walk into subdirectories to find the file by name
    // Try common DV3 paths: emotions/<any>/<file>, contextual/<any>/<file>, or root/<file>
    const tryGet = async (dir: FileSystemDirectoryHandle, name: string): Promise<File | null> => {
      try {
        const fh = await dir.getFileHandle(name);
        return fh.getFile();
      } catch {
        return null;
      }
    };

    // Try root first
    let file = await tryGet(handle, filename);
    if (file) return URL.createObjectURL(file);

    // Walk one level of subdirectories
    for await (const [, entry] of (handle as unknown as AsyncIterable<[string, FileSystemHandle]>)) {
      if (entry.kind === 'directory') {
        const subDir = entry as FileSystemDirectoryHandle;
        file = await tryGet(subDir, filename);
        if (file) return URL.createObjectURL(file);

        // Two levels deep
        for await (const [, subEntry] of (subDir as unknown as AsyncIterable<[string, FileSystemHandle]>)) {
          if (subEntry.kind === 'directory') {
            file = await tryGet(subEntry as FileSystemDirectoryHandle, filename);
            if (file) return URL.createObjectURL(file);
          }
        }
      }
    }

    return null;
  } catch {
    return null;
  }
}

interface AssetThumbProps {
  asset: LibraryAsset;
  isActive: boolean;
  dirHandle: FileSystemDirectoryHandle | null;
  onSelect: (file: string) => void;
}

const AssetThumb: React.FC<AssetThumbProps> = ({ asset, isActive, dirHandle, onSelect }) => {
  const [previewUrl, setPreviewUrl] = useState<string | null>(asset.previewUrl ?? null);

  useEffect(() => {
    if (previewUrl || !dirHandle) return;
    let revoked = false;

    loadPreviewUrl(dirHandle, asset.file).then(url => {
      if (!revoked && url) setPreviewUrl(url);
    });

    return () => {
      revoked = true;
    };
  }, [dirHandle, asset.file, previewUrl]);

  const badge: { label: string; className: string } | null = asset.file.endsWith('.gif')
    ? { label: 'GIF', className: 'bg-amber-500 text-black' }
    : asset.file.endsWith('.webp')
    ? { label: 'WEBP', className: 'bg-[#00d2ff]/80 text-black' }
    : null;

  return (
    <div
      onClick={() => onSelect(asset.file)}
      className={`relative aspect-square bg-black rounded overflow-hidden cursor-pointer border-2 transition-all group ${
        isActive
          ? 'border-[#f97316] shadow-lg shadow-[#f97316]/30'
          : 'border-transparent hover:border-white/20'
      }`}
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          className="w-full h-full object-cover"
          alt={asset.title || asset.file}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-white/20">
          <Layers className="w-6 h-6" />
        </div>
      )}

      {/* Emotion tags */}
      {asset.emotions.length > 0 && (
        <div className="absolute top-1 left-1 flex flex-wrap gap-0.5 max-w-[90%]">
          {asset.emotions.slice(0, 2).map(em => (
            <span
              key={em}
              className="bg-[#f97316]/80 text-black text-[8px] font-bold px-1 py-0.5 rounded leading-none"
            >
              {em}
            </span>
          ))}
          {asset.emotions.length > 2 && (
            <span className="bg-white/20 text-white text-[8px] px-1 py-0.5 rounded leading-none">
              +{asset.emotions.length - 2}
            </span>
          )}
        </div>
      )}

      {badge && (
        <div className={`absolute top-1 right-1 px-1 py-0.5 rounded font-bold uppercase text-[8px] leading-none ${badge.className}`}>
          {badge.label}
        </div>
      )}

      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-1 pt-4 text-[10px] truncate text-white/80">
        {asset.title || asset.file}
      </div>
    </div>
  );
};

export const LibraryPanel: React.FC<LibraryPanelProps> = ({
  assets,
  activeFile,
  dirHandle,
  onSelect,
}) => {
  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[#0a0a0a]">
      {/* Panel header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10 shrink-0">
        <span className="font-mono text-xs font-bold tracking-widest text-white/60 uppercase">Library</span>
        {assets.length > 0 && (
          <span className="bg-white/10 text-white/60 text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
            {assets.length}
          </span>
        )}
      </div>

      {/* Item grid */}
      <div className="flex-1 overflow-y-auto p-3 custom-scrollbar">
        {assets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12 text-white/30 border-2 border-dashed border-white/10 rounded-lg mt-2">
            <Layers className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm leading-relaxed">No tagged animations.</p>
            <p className="text-xs mt-1 opacity-70">Tag files in Inbox to add them here.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {assets.map(asset => (
              <AssetThumb
                key={asset.file}
                asset={asset}
                isActive={activeFile === asset.file}
                dirHandle={dirHandle}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
