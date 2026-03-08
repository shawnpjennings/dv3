import * as React from 'react';
import type { InboxItem, LibraryAsset } from '../types';
import { InboxPanel } from './InboxPanel';
import { LibraryPanel } from './LibraryPanel';

interface SidebarPanelProps {
  activeTab: 'inbox' | 'library';
  onTabChange: (tab: 'inbox' | 'library') => void;
  inboxItems: InboxItem[];
  activeInboxId: string | null;
  libraryAssets: LibraryAsset[];
  activeLibraryFile: string | null;
  dirHandle: FileSystemDirectoryHandle | null;
  onSelectInbox: (id: string) => void;
  onImport: (files: File[]) => void;
  onSelectLibrary: (file: string) => void;
}

export const SidebarPanel: React.FC<SidebarPanelProps> = ({
  activeTab,
  onTabChange,
  inboxItems,
  activeInboxId,
  libraryAssets,
  activeLibraryFile,
  dirHandle,
  onSelectInbox,
  onImport,
  onSelectLibrary,
}) => {
  return (
    <div className="w-[380px] flex-none flex flex-col bg-[#0a0a0a] border-r border-white/10 z-10 h-full">
      {/* Tab bar */}
      <div className="flex border-b border-white/10 shrink-0">
        <button
          onClick={() => onTabChange('inbox')}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-bold tracking-widest uppercase transition-colors relative ${
            activeTab === 'inbox'
              ? 'text-[#f97316]'
              : 'text-white/40 hover:text-white/70'
          }`}
        >
          Inbox
          {/* Count badge on inactive tab */}
          {activeTab !== 'inbox' && inboxItems.length > 0 && (
            <span className="bg-[#f97316]/20 text-[#f97316] text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none">
              {inboxItems.length}
            </span>
          )}
          {/* Active underline */}
          {activeTab === 'inbox' && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#f97316]" />
          )}
        </button>

        <button
          onClick={() => onTabChange('library')}
          className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-bold tracking-widest uppercase transition-colors relative ${
            activeTab === 'library'
              ? 'text-[#f97316]'
              : 'text-white/40 hover:text-white/70'
          }`}
        >
          Library
          {/* Count badge on inactive tab */}
          {activeTab !== 'library' && libraryAssets.length > 0 && (
            <span className="bg-white/10 text-white/50 text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none">
              {libraryAssets.length}
            </span>
          )}
          {/* Active underline */}
          {activeTab === 'library' && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#f97316]" />
          )}
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 flex flex-col min-h-0">
        {activeTab === 'inbox' ? (
          <InboxPanel
            items={inboxItems}
            activeId={activeInboxId}
            onSelect={onSelectInbox}
            onImport={onImport}
          />
        ) : (
          <LibraryPanel
            assets={libraryAssets}
            activeFile={activeLibraryFile}
            dirHandle={dirHandle}
            onSelect={onSelectLibrary}
          />
        )}
      </div>
    </div>
  );
};
