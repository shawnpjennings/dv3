import * as React from 'react';
import { Undo, Redo, Copy, Download, Folder, Link2, X, Trash2 } from 'lucide-react';
import { Asset } from '../types';

interface TopToolbarProps {
  activeAsset?: Asset;
  linkedAsset?: Asset;
  availableAssets: Asset[];
  dv3PathPreview: string;
  onUndo: () => void;
  onRedo: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onExport: () => void;
  onLinkVariant: (id: string) => void;
  onUnlinkVariant: () => void;
}

export const TopToolbar: React.FC<TopToolbarProps> = ({
  activeAsset,
  linkedAsset,
  availableAssets,
  dv3PathPreview,
  onUndo,
  onRedo,
  onDuplicate,
  onDelete,
  onExport,
  onLinkVariant,
  onUnlinkVariant
}) => {
  if (!activeAsset) {
    return (
      <div className="h-14 border-b border-white/10 bg-black/90 backdrop-blur flex items-center px-4 shrink-0 z-10" />
    );
  }

  const canUndo = activeAsset.historyIndex >= 0;
  const canRedo = activeAsset.historyIndex < activeAsset.editStack.length - 1;

  return (
    <div className="h-14 border-b border-white/10 bg-black/90 backdrop-blur flex items-center justify-between px-4 shrink-0 z-10">
      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-2 text-white/70 bg-black px-3 py-1.5 rounded border border-white/10">
          <Folder className="w-4 h-4 text-[#f97316]" />
          <span className="truncate max-w-sm">{dv3PathPreview}</span>
        </div>

        <div className="flex items-center gap-2">
          {linkedAsset ? (
            <div className="flex items-center gap-2 bg-white/10 text-[#00d2ff] border border-white/10 px-3 py-1.5 rounded">
              <Link2 className="w-4 h-4"/> Linked to: {linkedAsset.name}
              <button onClick={onUnlinkVariant} className="hover:text-white ml-2">
                <X className="w-3 h-3"/>
              </button>
            </div>
          ) : (
            <select
              onChange={(e) => onLinkVariant(e.target.value)}
              value=""
              className="bg-black border border-white/10 text-white/80 text-xs rounded px-2 py-1.5 outline-none hover:border-white/20"
            >
              <option value="" disabled>Link Dark/Light Variant...</option>
              {availableAssets.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button onClick={onUndo} disabled={!canUndo} className="p-2 hover:bg-white/10 disabled:opacity-30 rounded text-white/60 hover:text-white transition-colors" title="Undo">
          <Undo className="w-4 h-4" />
        </button>
        <button onClick={onRedo} disabled={!canRedo} className="p-2 hover:bg-white/10 disabled:opacity-30 rounded text-white/60 hover:text-white transition-colors" title="Redo">
          <Redo className="w-4 h-4" />
        </button>
        <div className="w-px h-6 bg-white/10 mx-2" />
        <button onClick={onDuplicate} className="flex items-center gap-2 px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white rounded text-sm transition-colors border border-white/10">
          <Copy className="w-4 h-4"/> Duplicate
        </button>
        <button onClick={onDelete} className="flex items-center gap-2 px-3 py-1.5 bg-red-900/60 hover:bg-red-800 text-red-100 rounded text-sm transition-colors border border-red-700/50">
          <Trash2 className="w-4 h-4"/> Remove
        </button>
        <button onClick={onExport} title="Applies all edits and renders a new WebP file for download" className="flex items-center gap-2 px-3 py-1.5 bg-[#f97316] hover:bg-[#fb923c] text-white rounded text-sm font-medium shadow-lg shadow-[#f97316]/20 transition-all">
          <Download className="w-4 h-4"/> Render & Export WebP
        </button>
      </div>
    </div>
  );
};
