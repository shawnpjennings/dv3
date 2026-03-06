import * as React from 'react';
import { useState } from 'react';
import { X } from 'lucide-react';
import { EditorSettings } from '../types';

interface SettingsModalProps {
  settings: EditorSettings;
  onClose: () => void;
  onSave: (settings: EditorSettings) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ settings, onClose, onSave }) => {
  const [localSettings, setLocalSettings] = useState<EditorSettings>(settings);

  const handleSave = () => {
    onSave(localSettings);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-black border border-white/10 rounded-lg shadow-2xl w-[400px] overflow-hidden">
        <div className="p-4 border-b border-white/10 flex justify-between items-center bg-black">
          <h2 className="font-display text-[#00d2ff]">Editor Settings</h2>
          <button onClick={onClose} className="text-white/70 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-6 space-y-4 text-sm">
          <div>
            <label className="block text-white/60 text-xs mb-1.5 uppercase tracking-wide">DV3 Export Root Path</label>
            <input
              type="text"
              value={localSettings.exportRoot}
              onChange={e => setLocalSettings({...localSettings, exportRoot: e.target.value})}
              className="w-full bg-black border border-white/10 rounded px-3 py-2 focus:border-[#00d2ff] outline-none text-white"
            />
            <p className="text-[10px] text-white/40 mt-1">E.g., data/animations (used for metadata paths)</p>
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
