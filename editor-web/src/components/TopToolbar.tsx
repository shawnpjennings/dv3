import * as React from 'react';
import { Undo2, Redo2 } from 'lucide-react';
import { Asset } from '../types';

interface TopToolbarProps {
  activeAsset?: Asset;
  onUndo: () => void;
  onRedo: () => void;
}

export const TopToolbar: React.FC<TopToolbarProps> = ({
  activeAsset,
  onUndo,
  onRedo,
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
      <div className="flex items-center gap-1">
        <button
          onClick={onUndo}
          disabled={!canUndo}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-white/80 hover:text-white hover:bg-white/10 disabled:opacity-25 disabled:cursor-not-allowed transition-colors text-xs"
          title="Undo"
        >
          <Undo2 className="w-3.5 h-3.5" />
          Undo
        </button>
        <button
          onClick={onRedo}
          disabled={!canRedo}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-white/80 hover:text-white hover:bg-white/10 disabled:opacity-25 disabled:cursor-not-allowed transition-colors text-xs"
          title="Redo"
        >
          <Redo2 className="w-3.5 h-3.5" />
          Redo
        </button>
      </div>
    </div>
  );
};
