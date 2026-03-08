import * as React from 'react';
import { useState } from 'react';
import { X, FolderOpen, CheckCircle2 } from 'lucide-react';
import { EditorSettings } from '../types';

interface SettingsModalProps {
  settings: EditorSettings;
  folderName: string | null;
  onClose: () => void;
  onSave: (settings: EditorSettings) => void;
  onSelectFolder: () => Promise<void>;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ settings, folderName, onClose, onSave, onSelectFolder }) => {
  const [localSettings, setLocalSettings] = useState<EditorSettings>(settings);
  const [selectingFolder, setSelectingFolder] = useState(false);

  const handleSave = () => {
    onSave(localSettings);
  };

  const handleSelectFolder = async () => {
    setSelectingFolder(true);
    try {
      await onSelectFolder();
    } finally {
      setSelectingFolder(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-black border border-white/10 rounded-lg shadow-2xl w-[440px] overflow-hidden">
        <div className="p-4 border-b border-white/10 flex justify-between items-center bg-black">
          <h2 className="font-display text-[#00d2ff]">Editor Settings</h2>
          <button onClick={onClose} className="text-white/70 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-6 space-y-5 text-sm">

          <div className="p-4 rounded border border-white/10 bg-white/5 space-y-3">
            <label className="block text-white/60 text-xs uppercase tracking-wide">DV3 Library Folder</label>
            {folderName ? (
              <div className="flex items-center gap-2 text-green-400 text-xs">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate font-mono">{folderName}</span>
              </div>
            ) : (
              <p className="text-white/40 text-xs">Not set — exports will download as ZIP</p>
            )}
            <button
              onClick={handleSelectFolder}
              disabled={selectingFolder}
              className="flex items-center gap-2 px-3 py-2 bg-[#00d2ff]/10 hover:bg-[#00d2ff]/20 border border-[#00d2ff]/30 text-[#00d2ff] rounded text-xs transition-colors disabled:opacity-50"
            >
              <FolderOpen className="w-3.5 h-3.5" />
              {folderName ? 'Change Folder' : 'Select animations Folder'}
            </button>
            <p className="text-[10px] text-white/35 leading-relaxed">
              Grant access to your <span className="text-white/60 font-mono">animations/</span> folder.
              Exports will write directly to <span className="text-white/60 font-mono">emotions/</span> and <span className="text-white/60 font-mono">contextual/</span> subfolders — no ZIP download needed.
            </p>
          </div>

          <div>
            <label className="block text-white/60 text-xs mb-1.5 uppercase tracking-wide">Default Size / Zoom Offset (px)</label>
            <input
              type="number"
              value={localSettings.defaultPadding}
              onChange={e => setLocalSettings({...localSettings, defaultPadding: parseInt(e.target.value, 10) || 0})}
              className="w-full bg-black border border-white/10 rounded px-3 py-2 focus:border-[#00d2ff] outline-none text-white"
            />
          </div>
        </div>
        <div className="p-4 border-t border-white/10 bg-black flex justify-end">
          <button onClick={handleSave} className="px-4 py-2 bg-[#f97316] hover:bg-[#fb923c] text-white rounded text-sm font-medium">
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
