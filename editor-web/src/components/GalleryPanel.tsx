import * as React from 'react';
import { useState, useRef } from 'react';
import { Upload, Image as ImageIcon, Search, CheckSquare, Square, Link2, Settings as SettingsIcon, Layers, Type, Trash2, Pencil, AlertCircle, CheckCircle2 } from 'lucide-react';
import { Asset, BatchRenamePayload } from '../types';
import { EMOTIONS, CONTEXTS } from '../constants';

interface GalleryPanelProps {
  assets: Asset[];
  activeAssetId: string | null;
  selectedIds: Set<string>;
  searchQuery: string;
  filterEmotion: string;
  filterContext: string;
  filterType: string;
  onSearchChange: (q: string) => void;
  onFilterEmotionChange: (f: string) => void;
  onFilterContextChange: (f: string) => void;
  onFilterTypeChange: (f: string) => void;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onSelectAsset: (id: string) => void;
  onToggleSelection: (id: string, e: React.MouseEvent) => void;
  onBatchExport: () => void;
  onBatchRename: (payload: BatchRenamePayload) => void;
  onDeleteAsset: (id: string) => void;
  onOpenSettings: () => void;
}

export const GalleryPanel: React.FC<GalleryPanelProps> = ({
  assets,
  activeAssetId,
  selectedIds,
  searchQuery,
  filterEmotion,
  filterContext,
  filterType,
  onSearchChange,
  onFilterEmotionChange,
  onFilterContextChange,
  onFilterTypeChange,
  onUpload,
  onSelectAsset,
  onToggleSelection,
  onBatchExport,
  onBatchRename,
  onDeleteAsset,
  onOpenSettings
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showBatchRename, setShowBatchRename] = useState(false);
  const [renamePrefix, setRenamePrefix] = useState('dv3');
  const [renameTag, setRenameTag] = useState('');
  const [renameStartIndex, setRenameStartIndex] = useState(1);

  const handleBatchRenameSubmit = () => {
    onBatchRename({
      prefix: renamePrefix,
      tag: renameTag,
      startIndex: renameStartIndex
    });
    setShowBatchRename(false);
  };

  return (
    <div className="w-80 bg-black border-r border-white/10 flex flex-col z-10 shrink-0 h-full">
      <div className="p-4 border-b border-white/10 bg-black flex justify-between items-center shrink-0">
        <h1 className="font-display text-lg text-[#f97316] flex items-center gap-2">
          <Layers className="w-5 h-5" /> DV3 Library
        </h1>
        <div className="flex gap-2">
          <button onClick={onOpenSettings} className="p-2 text-white/70 hover:text-[#00d2ff] transition-colors" title="Settings">
            <SettingsIcon className="w-4 h-4" />
          </button>
          <button onClick={() => fileInputRef.current?.click()} className="bg-[#f97316] hover:bg-[#fb923c] text-white p-2 rounded cursor-pointer transition-colors shadow-lg shadow-[#f97316]/20" title="Upload Media">
            <Upload className="w-4 h-4" />
          </button>
        </div>
        <input type="file" ref={fileInputRef} className="hidden" multiple accept="image/gif, image/webp, image/png, image/jpeg" onChange={onUpload} />
      </div>

      <div className="p-3 border-b border-white/10 space-y-2 bg-black shrink-0">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-gray-500" />
          <input
            type="text" placeholder="Search files, tags, notes..."
            value={searchQuery} onChange={e => onSearchChange(e.target.value)}
            className="w-full bg-black border border-white/10 rounded pl-9 pr-3 py-1.5 text-sm focus:border-[#00d2ff] outline-none text-white"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <select
            value={filterEmotion} onChange={e => onFilterEmotionChange(e.target.value)}
            className="bg-black border border-white/10 rounded px-2 py-1.5 text-xs text-white/80 outline-none"
          >
            <option value="all">All Emotions</option>
            {EMOTIONS.map(e => <option key={e} value={e}>{e}</option>)}
          </select>
          <select
            value={filterContext} onChange={e => onFilterContextChange(e.target.value)}
            className="bg-black border border-white/10 rounded px-2 py-1.5 text-xs text-white/80 outline-none"
          >
            <option value="all">All Contexts</option>
            {CONTEXTS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <select
          value={filterType} onChange={e => onFilterTypeChange(e.target.value)}
          className="w-full bg-black border border-white/10 rounded px-2 py-1.5 text-xs text-white/80 outline-none"
        >
          <option value="all">All File Types</option>
          <option value="image/gif">GIF Only</option>
          <option value="image/webp">WebP Only</option>
          <option value="static">Static (PNG/JPG)</option>
        </select>
      </div>

      <div className="flex-1 overflow-y-auto p-3 custom-scrollbar">
        {assets.length === 0 ? (
          <div className="text-center p-8 text-white/40 border-2 border-dashed border-white/10 rounded-lg mt-4 bg-black">
            <ImageIcon className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No assets found.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {assets.map(asset => {
              const isSelected = selectedIds.has(asset.id);
              const isActive = activeAssetId === asset.id;
              const isGif = asset.type === 'image/gif';

              let fileTypeBadge: { label: string; className: string } | null = null;
              if (asset.type === 'image/gif') {
                fileTypeBadge = { label: 'GIF', className: 'bg-amber-500 text-black' };
              } else if (asset.type === 'image/webp') {
                fileTypeBadge = { label: 'WEBP', className: 'bg-[#00d2ff]/80 text-black' };
              } else if (asset.type === 'image/png') {
                fileTypeBadge = { label: 'PNG', className: 'bg-white/40 text-black' };
              } else if (asset.type === 'image/jpeg') {
                fileTypeBadge = { label: 'JPG', className: 'bg-white/40 text-black' };
              }

              return (
                <div
                  key={asset.id}
                  onClick={(e) => {
                    if (e.shiftKey || e.ctrlKey || e.metaKey) {
                      onToggleSelection(asset.id, e);
                    } else {
                      onSelectAsset(asset.id);
                    }
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    onDeleteAsset(asset.id);
                  }}
                  className={`relative aspect-square bg-black rounded overflow-hidden cursor-pointer border-2 transition-all group ${isActive ? 'border-[#f97316] shadow-lg shadow-[#f97316]/30' : isSelected ? 'border-[#00d2ff]' : `border-transparent hover:border-white/20`} ${isGif && !isActive && !isSelected ? 'ring-1 ring-amber-500/30' : ''}`}
                >
                  <img src={asset.fileUrl} className="w-full h-full object-cover" alt={asset.name} />

                  <div
                    onClick={(e) => { e.stopPropagation(); onToggleSelection(asset.id, e); }}
                    className={`absolute top-1 left-1 p-1 rounded backdrop-blur transition-opacity ${isSelected || isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} ${isSelected ? 'text-[#00d2ff]' : 'text-white/60 hover:text-white'}`}
                  >
                    {isSelected ? <CheckSquare className="w-4 h-4 bg-black/60 rounded" /> : <Square className="w-4 h-4 bg-black/60 rounded" />}
                  </div>

                  {asset.linkedVariantId && <div className="absolute top-1 right-8 bg-[#00d2ff] rounded-full p-0.5 shadow"><Link2 className="w-3 h-3 text-black"/></div>}

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteAsset(asset.id);
                    }}
                    className="absolute top-1 right-1 p-1 rounded bg-black/50 text-gray-300 opacity-0 group-hover:opacity-100 hover:text-red-400 transition-opacity"
                    title="Remove asset"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>

                  {asset.editStack.length > 0 && !asset.lastExportedAt && (
                    <div className="absolute bottom-6 left-1 flex items-center bg-amber-500/90 rounded px-1 py-0.5" title="Has pending edits — not yet exported">
                      <Pencil className="w-2.5 h-2.5 text-black" />
                    </div>
                  )}

                  {asset.editStack.length > 0 && asset.lastExportedAt && (
                    <div className="absolute bottom-6 left-1 flex items-center bg-amber-500/90 rounded px-1 py-0.5" title="Edited since last export">
                      <AlertCircle className="w-2.5 h-2.5 text-black" />
                    </div>
                  )}

                  {asset.editStack.length === 0 && asset.lastExportedAt && (
                    <div className="absolute bottom-6 left-1 flex items-center bg-green-500/90 rounded px-1 py-0.5" title={`Exported to DV3 ${new Date(asset.lastExportedAt).toLocaleDateString()}`}>
                      <CheckCircle2 className="w-2.5 h-2.5 text-black" />
                    </div>
                  )}

                  {fileTypeBadge && (
                    <div className={`absolute bottom-6 right-1 px-1 py-0.5 rounded font-bold uppercase text-[8px] leading-none ${fileTypeBadge.className}`}>
                      {fileTypeBadge.label}
                    </div>
                  )}

                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-1 pt-4 text-[10px] truncate text-white" title={asset.name}>
                    {asset.name}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {selectedIds.size > 0 && (
        <div className="p-3 border-t border-white/10 bg-black flex flex-col gap-2 shrink-0">
          <div className="flex justify-between items-center text-xs text-white/60 px-1">
            <span>{selectedIds.size} assets selected</span>
            <button onClick={() => setShowBatchRename(!showBatchRename)} className="hover:text-white transition-colors flex items-center gap-1">
              <Type className="w-3 h-3" /> Rename
            </button>
          </div>

          {showBatchRename && (
            <div className="bg-black border border-white/10 rounded p-2 text-xs space-y-2 mb-1">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="block text-[10px] text-white/50 mb-1">Prefix</label>
                  <input type="text" value={renamePrefix} onChange={e => setRenamePrefix(e.target.value)} className="w-full bg-black border border-white/10 rounded px-2 py-1 text-white outline-none focus:border-[#00d2ff]" placeholder="e.g. dv3" />
                </div>
                <div className="flex-1">
                  <label className="block text-[10px] text-white/50 mb-1">Tag (Opt)</label>
                  <input type="text" value={renameTag} onChange={e => setRenameTag(e.target.value)} className="w-full bg-black border border-white/10 rounded px-2 py-1 text-white outline-none focus:border-[#00d2ff]" placeholder="e.g. happy" />
                </div>
                <div className="w-16">
                  <label className="block text-[10px] text-white/50 mb-1">Start #</label>
                  <input type="number" min="1" value={renameStartIndex} onChange={e => setRenameStartIndex(parseInt(e.target.value, 10) || 1)} className="w-full bg-black border border-white/10 rounded px-2 py-1 text-white outline-none focus:border-[#00d2ff]" />
                </div>
              </div>
              <button onClick={handleBatchRenameSubmit} className="w-full py-1.5 bg-white/10 hover:bg-white/20 text-white rounded border border-white/10 transition-colors">
                Apply Rename
              </button>
            </div>
          )}

          <button onClick={onBatchExport} className="w-full py-2 bg-[#f97316] hover:bg-[#fb923c] text-white rounded text-sm font-medium transition-colors">
            Batch Export WebP
          </button>
        </div>
      )}
    </div>
  );
};
