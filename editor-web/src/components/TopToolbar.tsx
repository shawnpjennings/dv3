import * as React from 'react';
import { Undo, Redo, Copy, Trash2 } from 'lucide-react';
import { Asset } from '../types';

interface TopToolbarProps {
  activeAsset?: Asset;
  onUndo: () => void;
  onRedo: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

export const TopToolbar: React.FC<TopToolbarProps> = ({
  activeAsset,
  onUndo,
  onRedo,
  onDuplicate,
  onDelete,
}) => {
  if (!activeAsset) {
    return (
      <div className="h-10 border-b border-white/10 bg-black/90 backdrop-blur flex items-center px-4 shrink-0 z-10" />
    );
  }

  const canUndo = activeAsset.historyIndex >= 0;
  const canRedo = activeAsset.historyIndex < activeAsset.editStack.length - 1;

  return (
    <div className="h-10 border-b border-white/10 bg-black/90 backdrop-blur flex items-center justify-end px-4 shrink-0 z-10">
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
      </div>
    </div>
  );
};
