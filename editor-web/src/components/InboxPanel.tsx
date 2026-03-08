import * as React from 'react';
import { useRef } from 'react';
import { Upload, Image as ImageIcon } from 'lucide-react';
import type { InboxItem } from '../types';
import { computeThumbStyles } from '../lib/thumbStyles';

interface InboxPanelProps {
  items: InboxItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onImport: (files: File[]) => void;
}

export const InboxPanel: React.FC<InboxPanelProps> = ({
  items,
  activeId,
  onSelect,
  onImport,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const files = Array.from(e.target.files);
    if (files.length > 0) onImport(files);
    // Reset so the same file can be re-imported
    e.target.value = '';
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[#0a0a0a]">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/10 shrink-0">
        <div className="flex items-center gap-2">
          {items.length > 0 && (
            <span className="bg-[#f97316]/20 text-[#f97316] text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
              {items.length} files
            </span>
          )}
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-1.5 bg-[#f97316] hover:bg-[#fb923c] text-white text-xs font-medium px-3 py-1.5 rounded transition-colors shadow-lg shadow-[#f97316]/20"
        >
          <Upload className="w-3.5 h-3.5" />
          Import
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".webp,.gif,image/webp,image/gif"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />
      </div>

      {/* Item grid */}
      <div className="flex-1 overflow-y-auto p-3 custom-scrollbar">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12 text-white/30 border-2 border-dashed border-white/10 rounded-lg mt-2">
            <ImageIcon className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm leading-relaxed">No files in inbox.</p>
            <p className="text-xs mt-1 opacity-70">Click Import to add animations.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {items.map(item => {
              const isActive = item.id === activeId;
              const thumbStyles = computeThumbStyles(item.editStack, item.historyIndex);

              let badge: { label: string; className: string } | null = null;
              if (item.type === 'image/gif') {
                badge = { label: 'GIF', className: 'bg-amber-500 text-black' };
              } else if (item.type === 'image/webp') {
                badge = { label: 'WEBP', className: 'bg-[#00d2ff]/80 text-black' };
              }

              return (
                <div
                  key={item.id}
                  onClick={() => onSelect(item.id)}
                  className={`relative aspect-square bg-black rounded overflow-hidden cursor-pointer border-2 transition-all group ${
                    isActive
                      ? 'border-[#f97316] shadow-lg shadow-[#f97316]/30'
                      : 'border-transparent hover:border-white/20'
                  }`}
                >
                  <img
                    src={item.previewUrl}
                    className="w-full h-full object-cover"
                    alt={item.name}
                    style={thumbStyles}
                  />

                  {badge && (
                    <div className={`absolute top-1 right-1 px-1 py-0.5 rounded font-bold uppercase text-[8px] leading-none ${badge.className}`}>
                      {badge.label}
                    </div>
                  )}

                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-1 pt-4 text-[10px] truncate text-white/80">
                    {item.name}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
