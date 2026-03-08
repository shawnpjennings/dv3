import * as React from 'react';
import { useState, useMemo, useEffect, useRef } from 'react';
import { FolderOpen, Settings } from 'lucide-react';
import { Asset, EditorSettings, ActionType, BatchRenamePayload, InboxItem, LibraryAsset, SavePayload } from './types';
import { GalleryPanel } from './components/GalleryPanel';
import { SidebarPanel } from './components/SidebarPanel';
import { TopToolbar } from './components/TopToolbar';
import { EditorPanel } from './components/EditorPanel';
import { SettingsModal } from './components/SettingsModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { TagPanel } from './components/TagPanel';
import { deleteAssetFromDB, loadAssetsFromDB, saveAssetToDB, loadSettingsFromDB, saveSettingsToDB, saveDirectoryHandle, loadDirectoryHandle } from './lib/db';
import { executeBatchExport } from './lib/exportUtils';
import { bakeAndSave } from './lib/bakeUtils';
import { validateUpload } from './lib/validation';
import { copyWebPToInbox, convertGifToInbox, getOrCreateInboxDir } from './lib/inboxUtils';

// FileSystemDirectoryHandle.queryPermission/requestPermission are widely supported
// but not yet in the TypeScript lib.
type DirHandle = FileSystemDirectoryHandle & {
  queryPermission: (opts: { mode: string }) => Promise<PermissionState>;
  requestPermission: (opts: { mode: string }) => Promise<PermissionState>;
};

function AppContent() {
  const [isReady, setIsReady] = useState(false);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeAssetId, setActiveAssetId] = useState<string | null>(null);

  const [dv3PreviewMode, setDv3PreviewMode] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');
  const [filterEmotion, setFilterEmotion] = useState('all');
  const [filterContext, setFilterContext] = useState('all');
  const [filterType, setFilterType] = useState('all');

  const lastSelectedIdRef = useRef<string | null>(null);

  const [settings, setSettings] = useState<EditorSettings>({
    defaultPadding: 0
  });

  const [dirHandle, setDirHandle] = useState<DirHandle | null>(null);

  const [isExporting, setIsExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState('');
  const [exportProgress, setExportProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [isImporting, setIsImporting] = useState(false);
  const [importStatus, setImportStatus] = useState('');

  // Tab visibility state for thumbnail playback optimization
  const [isTabVisible, setIsTabVisible] = useState(true);

  // New inbox/library state model
  const [activeTab, setActiveTab] = useState<'inbox' | 'library'>('inbox');
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
  const [activeInboxId, setActiveInboxId] = useState<string | null>(null);
  const [libraryAssets, setLibraryAssets] = useState<LibraryAsset[]>([]);
  const [activeLibraryFile, setActiveLibraryFile] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');

  useEffect(() => {
    let isMounted = true;

    const initData = async () => {
      try {
        const [savedAssets, savedSettings, savedHandle] = await Promise.all([
          loadAssetsFromDB(),
          loadSettingsFromDB(),
          loadDirectoryHandle(),
        ]);

        if (!isMounted) return;

        if (savedSettings) {
          setSettings(savedSettings);
        }

        if (savedAssets && savedAssets.length > 0) {
          setAssets(savedAssets);
          setActiveAssetId(savedAssets[0].id);
        }

        if (savedHandle) {
          // Re-verify permission (browser requires re-grant after page reload)
          const typedHandle = savedHandle as DirHandle;
          const perm = await typedHandle.queryPermission({ mode: 'readwrite' });
          if (perm === 'granted') {
            setDirHandle(typedHandle);
            await loadLibrary(typedHandle);
          }
          // If 'prompt', we'll request on first export attempt
        }
      } catch (err) {
        console.error('Failed to initialize DB data:', err);
      } finally {
        if (isMounted) setIsReady(true);
      }
    };

    initData();

    const handleVisibilityChange = () => {
      setIsTabVisible(document.visibilityState === 'visible');
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      isMounted = false;
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      setAssets(currentAssets => {
        currentAssets.forEach(a => URL.revokeObjectURL(a.fileUrl));
        return currentAssets;
      });
    };
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    setUploadError(null);

    const validFiles: File[] = [];
    const errors: string[] = [];

    Array.from(e.target.files).forEach(file => {
      const { valid, error } = validateUpload(file);
      if (valid) {
        validFiles.push(file);
      } else if (error) {
        errors.push(`${file.name}: ${error}`);
      }
    });

    if (errors.length > 0) {
      setUploadError(errors.join('\n'));
    }

    if (validFiles.length === 0) {
      if (e.target) e.target.value = '';
      return;
    }

    const newAssets: Asset[] = validFiles.map(file => ({
      id: Math.random().toString(36).substring(2, 9),
      originalFile: file,
      fileUrl: URL.createObjectURL(file),
      name: file.name.replace(/\.[^/.]+$/, ''),
      type: file.type,
      emotion: 'neutral',
      additionalEmotions: [],
      context: 'idle',
      theme: 'dark' as const,
      title: '',
      notes: '',
      editStack: [],
      historyIndex: -1,
    }));

    for (const asset of newAssets) {
      await saveAssetToDB(asset);
    }

    setAssets(prev => [...prev, ...newAssets]);
    if (!activeAssetId && newAssets.length > 0) setActiveAssetId(newAssets[0].id);

    // Reset input
    if (e.target) e.target.value = '';
  };

  const updateAsset = async (id: string, updates: Partial<Asset>) => {
    let updatedAssetData: Asset | null = null;

    setAssets(prev => prev.map(a => {
      if (a.id === id) {
        const merged = { ...a, ...updates };
        updatedAssetData = merged;
        return merged;
      }
      return a;
    }));

    if (updatedAssetData) {
      await saveAssetToDB(updatedAssetData);
    }
  };

  const handleSaveSettings = async (newSettings: EditorSettings) => {
    setSettings(newSettings);
    await saveSettingsToDB(newSettings);
    setShowSettings(false);
  };

  const loadLibrary = async (handle: DirHandle) => {
    try {
      const manifestHandle = await handle.getFileHandle('manifest.json');
      const file = await manifestHandle.getFile();
      const text = await file.text();
      const data = JSON.parse(text);
      setLibraryAssets(data.assets ?? []);
    } catch {
      setLibraryAssets([]);
    }
  };

  const handleSelectFolder = async () => {
    try {
      const handle = await (window as unknown as { showDirectoryPicker: (opts?: object) => Promise<DirHandle> })
        .showDirectoryPicker({ mode: 'readwrite', startIn: 'documents' });
      await saveDirectoryHandle(handle);
      setDirHandle(handle);
      setSaveStatus('');
    } catch (err) {
      // User cancelled picker — ignore
      if (err instanceof Error && err.name !== 'AbortError') {
        console.error('Failed to select folder:', err);
      }
    }
  };

  const activeAsset = assets.find(a => a.id === activeAssetId);
  const linkedAsset = activeAsset?.linkedVariantId ? assets.find(a => a.id === activeAsset.linkedVariantId) : undefined;

  const applyEdit = (type: ActionType, value: number | boolean) => {
    // If an inbox item is active (includes library re-edits), update that instead
    if (activeInboxId) {
      setInboxItems(prev => prev.map(item => {
        if (item.id !== activeInboxId) return item;
        const stack = item.editStack.slice(0, item.historyIndex + 1);
        const last = stack[stack.length - 1];
        if (last && last.type === type) {
          stack[stack.length - 1] = { type, value };
        } else {
          stack.push({ type, value });
        }
        return { ...item, editStack: stack, historyIndex: stack.length - 1 };
      }));
      return;
    }

    if (!activeAsset) return;

    // Keep a true chronological action history so undo/redo can step through
    // every user change, including repeated edits of the same control.
    const activeEditStack = activeAsset.editStack.slice(0, activeAsset.historyIndex + 1);
    const currentStack = [...activeEditStack];
    const lastAction = currentStack[currentStack.length - 1];

    // Merge adjacent updates for the same control so a slider drag can be
    // undone in one step instead of dozens of intermediate values.
    if (lastAction && lastAction.type === type) {
      currentStack[currentStack.length - 1] = { type, value };
    } else {
      currentStack.push({ type, value });
    }

    updateAsset(activeAsset.id, {
      editStack: currentStack,
      historyIndex: currentStack.length - 1
    });
  };

  const handleUndo = () => {
    if (activeInboxItem) {
      if (activeInboxItem.historyIndex < 0) return;
      setInboxItems(prev => prev.map(i =>
        i.id === activeInboxItem.id ? { ...i, historyIndex: i.historyIndex - 1 } : i
      ));
      return;
    }
    if (!activeAsset || activeAsset.historyIndex < 0) return;
    updateAsset(activeAsset.id, { historyIndex: activeAsset.historyIndex - 1 });
  };

  const handleRedo = () => {
    if (activeInboxItem) {
      if (activeInboxItem.historyIndex >= activeInboxItem.editStack.length - 1) return;
      setInboxItems(prev => prev.map(i =>
        i.id === activeInboxItem.id ? { ...i, historyIndex: i.historyIndex + 1 } : i
      ));
      return;
    }
    if (!activeAsset || activeAsset.historyIndex >= activeAsset.editStack.length - 1) return;
    updateAsset(activeAsset.id, { historyIndex: activeAsset.historyIndex + 1 });
  };

  const handleDuplicate = async () => {
    if (!activeAsset) return;

    const duplicatedAsset: Asset = {
      ...activeAsset,
      id: Math.random().toString(36).substring(2, 9),
      name: `${activeAsset.name}_copy`,
      fileUrl: URL.createObjectURL(activeAsset.originalFile),
      editStack: [...activeAsset.editStack],
    };

    await saveAssetToDB(duplicatedAsset);
    setAssets(prev => [...prev, duplicatedAsset]);
    setActiveAssetId(duplicatedAsset.id);
  };

  const handleDuplicateInbox = () => {
    if (!activeInboxItem) return;
    const dup: InboxItem = {
      id: Math.random().toString(36).substring(2, 9),
      file: activeInboxItem.file,
      previewUrl: URL.createObjectURL(activeInboxItem.file),
      name: `${activeInboxItem.name}_copy`,
      type: activeInboxItem.type,
      editStack: [...activeInboxItem.editStack],
      historyIndex: activeInboxItem.historyIndex,
    };
    setInboxItems(prev => [...prev, dup]);
    setActiveInboxId(dup.id);
  };

  const handleDeleteInbox = () => {
    if (!activeInboxItem) return;
    const confirmed = window.confirm(`Remove "${activeInboxItem.name}" from inbox?`);
    if (!confirmed) return;
    URL.revokeObjectURL(activeInboxItem.previewUrl);
    setInboxItems(prev => prev.filter(i => i.id !== activeInboxItem.id));
    setActiveInboxId(null);
  };

  const handleDeleteAsset = async (id: string) => {
    const assetToDelete = assets.find(a => a.id === id);
    if (!assetToDelete) return;

    const shouldDelete = window.confirm(`Remove "${assetToDelete.name}" from the library?`);
    if (!shouldDelete) return;

    const linkedId = assetToDelete.linkedVariantId;
    if (linkedId) {
      const linkedAssetRecord = assets.find(a => a.id === linkedId);
      if (linkedAssetRecord) {
        await saveAssetToDB({ ...linkedAssetRecord, linkedVariantId: undefined });
      }
    }

    await deleteAssetFromDB(id);
    URL.revokeObjectURL(assetToDelete.fileUrl);

    const remaining = assets.filter(a => a.id !== id);
    setAssets(remaining.map(a => (a.id === linkedId ? { ...a, linkedVariantId: undefined } : a)));

    setSelectedIds(prev => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

    if (lastSelectedIdRef.current === id) {
      lastSelectedIdRef.current = null;
    }

    if (activeAssetId === id) {
      setActiveAssetId(remaining.length > 0 ? remaining[0].id : null);
      setCompareMode(false);
    }
  };

  const filteredAssets = useMemo(() => {
    return assets.filter(a => {
      const q = searchQuery.toLowerCase();
      const matchesSearch = q === '' ||
        a.name.toLowerCase().includes(q) ||
        a.notes.toLowerCase().includes(q) ||
        a.emotion.toLowerCase().includes(q) ||
        a.context.toLowerCase().includes(q);

      const matchesEmotion = filterEmotion === 'all' || a.emotion === filterEmotion;
      const matchesContext = filterContext === 'all' || a.context === filterContext;

      let matchesType = true;
      if (filterType === 'static') {
        matchesType = a.type === 'image/jpeg' || a.type === 'image/png';
      } else if (filterType !== 'all') {
        matchesType = a.type === filterType;
      }

      return matchesSearch && matchesEmotion && matchesContext && matchesType;
    });
  }, [assets, searchQuery, filterEmotion, filterContext, filterType]);


  const toggleSelection = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();

    const newSelection = new Set(selectedIds);

    if (e.shiftKey && lastSelectedIdRef.current) {
      const filteredIds = filteredAssets.map(a => a.id);
      const startIdx = filteredIds.indexOf(lastSelectedIdRef.current);
      const endIdx = filteredIds.indexOf(id);

      if (startIdx !== -1 && endIdx !== -1) {
        const min = Math.min(startIdx, endIdx);
        const max = Math.max(startIdx, endIdx);

        for (let i = min; i <= max; i++) {
          newSelection.add(filteredIds[i]);
        }
        setSelectedIds(newSelection);
        lastSelectedIdRef.current = id;
        return;
      }
    }

    if (newSelection.has(id)) {
      newSelection.delete(id);
    } else {
      newSelection.add(id);
      lastSelectedIdRef.current = id;
    }

    setSelectedIds(newSelection);
  };

  const doExport = async (assetsToExport: Asset[]) => {
    // If we have a saved handle, ensure permission is still granted
    let activeHandle = dirHandle;
    if (activeHandle) {
      const perm = await activeHandle.queryPermission({ mode: 'readwrite' });
      if (perm === 'prompt') {
        const granted = await activeHandle.requestPermission({ mode: 'readwrite' });
        if (granted !== 'granted') activeHandle = null;
      } else if (perm === 'denied') {
        activeHandle = null;
      }
    }

    setIsExporting(true);
    setExportProgress(0);
    setExportStatus(activeHandle ? 'Writing to DV3 library...' : 'Starting export...');
    try {
      await executeBatchExport(assetsToExport, settings, (status, progress) => {
        setExportStatus(status);
        setExportProgress(progress);
      }, activeHandle ?? undefined);
      const exportedAt = new Date().toISOString();
      for (const asset of assetsToExport) {
        await updateAsset(asset.id, { lastExportedAt: exportedAt });
      }
    } catch (err) {
      console.error('Export failed:', err);
      const details = err instanceof Error ? err.message : String(err);
      alert(`Export failed: ${details}`);
    } finally {
      setIsExporting(false);
      setExportStatus('');
      setExportProgress(0);
    }
  };

  const handleBatchExport = () => {
    const targets = selectedIds.size > 0
      ? assets.filter(a => selectedIds.has(a.id))
      : (activeAsset ? [activeAsset] : []);

    if (targets.length === 0) return;
    doExport(targets);
  };

  const handleBatchRename = async (payload: BatchRenamePayload) => {
    const targetIds = Array.from(selectedIds);
    if (targetIds.length === 0) return;

    const orderedTargets = filteredAssets.filter(a => selectedIds.has(a.id));

    let currentIndex = payload.startIndex;
    const updatedAssets = [...assets];

    for (const targetAsset of orderedTargets) {
      const paddedIndex = currentIndex.toString().padStart(3, '0');
      const tagPart = payload.tag ? `_${payload.tag}` : '';
      const newName = `${payload.prefix}${tagPart}_${paddedIndex}`;

      const assetIndex = updatedAssets.findIndex(a => a.id === targetAsset.id);
      if (assetIndex !== -1) {
        updatedAssets[assetIndex] = { ...updatedAssets[assetIndex], name: newName };
        await saveAssetToDB(updatedAssets[assetIndex]);
      }
      currentIndex++;
    }

    setAssets(updatedAssets);
  };

  const handleImport = async (files: File[]) => {
    const newItems: InboxItem[] = files.map(file => ({
      id: Math.random().toString(36).substring(2, 9),
      file,
      previewUrl: URL.createObjectURL(file),
      name: file.name.replace(/\.[^/.]+$/, ''),
      type: file.type,
      editStack: [],
      historyIndex: -1,
    }));
    setInboxItems(prev => [...prev, ...newItems]);
    if (!activeInboxId && newItems.length > 0) setActiveInboxId(newItems[0].id);

    if (!dirHandle) return; // no folder selected yet — in-memory only

    setIsImporting(true);
    try {
      const inboxDir = await getOrCreateInboxDir(dirHandle);
      for (const item of newItems) {
        if (item.type === 'image/gif') {
          setImportStatus(`Converting ${item.name}...`);
          const converted = await convertGifToInbox(item.file, inboxDir, (pct) => {
            setImportStatus(`Converting ${item.name}... ${pct}%`);
          });
          URL.revokeObjectURL(item.previewUrl);
          const newUrl = URL.createObjectURL(converted);
          setInboxItems(prev =>
            prev.map(i =>
              i.id === item.id
                ? { ...i, file: converted, previewUrl: newUrl, type: 'image/webp' }
                : i
            )
          );
        } else {
          setImportStatus(`Copying ${item.name}...`);
          await copyWebPToInbox(item.file, inboxDir);
        }
      }
    } finally {
      setIsImporting(false);
      setImportStatus('');
    }
  };

  const activeInboxItem = inboxItems.find(i => i.id === activeInboxId) ?? null;

  // When a library asset is selected, create a temporary InboxItem so EditorPanel can show a preview
  const handleSelectLibrary = async (file: string) => {
    setActiveLibraryFile(file);
    setActiveTab('library');

    if (!dirHandle) return;

    try {
      // Navigate path segments (e.g. "library/filename.webp" → subdir + filename)
      const parts = file.split('/');
      let dir: FileSystemDirectoryHandle = dirHandle;
      for (let i = 0; i < parts.length - 1; i++) {
        dir = await dir.getDirectoryHandle(parts[i]);
      }
      const filename = parts[parts.length - 1];
      const fh = await dir.getFileHandle(filename);
      const f = await fh.getFile();

      const url = URL.createObjectURL(f);
      const tempId = `lib_${file}`;
      const tempItem: InboxItem = {
        id: tempId,
        file: f,
        previewUrl: url,
        name: filename.replace(/\.webp$/, '').replace(/\.gif$/, ''),
        type: f.type || 'image/webp',
        editStack: [],
        historyIndex: -1,
      };

      setInboxItems(prev => {
        const filtered = prev.filter(i => i.id !== tempId);
        return [...filtered, tempItem];
      });
      setActiveInboxId(tempId);
    } catch (err) {
      console.warn('Could not load library asset for editing:', err);
    }
  };

  // Derive an Asset-compatible object from the active InboxItem so EditorPanel can preview it
  const activeInboxAsset: Asset | undefined = activeInboxItem
    ? {
        id: activeInboxItem.id,
        originalFile: activeInboxItem.file,
        fileUrl: activeInboxItem.previewUrl,
        name: activeInboxItem.name,
        type: activeInboxItem.type,
        emotion: 'neutral',
        additionalEmotions: [],
        context: 'idle',
        theme: 'dark' as const,
        title: '',
        notes: '',
        editStack: activeInboxItem.editStack,
        historyIndex: activeInboxItem.historyIndex,
      }
    : undefined;

  // When re-editing a library asset, pass its metadata to TagPanel for pre-population
  const activeLibraryAsset: LibraryAsset | null =
    activeInboxId?.startsWith('lib_')
      ? (libraryAssets.find(a => `lib_${a.file}` === activeInboxId) ?? null)
      : null;

  const handleSave = async (payload: SavePayload) => {
    if (!activeInboxItem) {
      setSaveStatus('No file selected.');
      return;
    }
    if (!dirHandle) {
      setSaveStatus('no-folder');
      return;
    }
    setIsSaving(true);
    setSaveStatus('Baking edits...');
    try {
      const libraryAsset = await bakeAndSave(activeInboxItem, payload, dirHandle);
      // Add to library (replace if same filename already exists)
      setLibraryAssets(prev => {
        const existing = prev.findIndex(a => a.file === libraryAsset.file);
        if (existing >= 0) {
          const next = [...prev];
          next[existing] = libraryAsset;
          return next;
        }
        return [...prev, libraryAsset];
      });
      // Remove from inbox and revoke preview URL, then select next inbox item
      URL.revokeObjectURL(activeInboxItem.previewUrl);
      setInboxItems(prev => {
        const next = prev.filter(i => i.id !== activeInboxItem.id);
        // Select the next available inbox item (stay on inbox tab)
        const nextItem = next.find(i => !i.id.startsWith('lib_')) ?? next[0] ?? null;
        setActiveInboxId(nextItem?.id ?? null);
        return next;
      });
      setSaveStatus('Saved!');
      setTimeout(() => setSaveStatus(''), 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveStatus(`Save failed: ${msg}`);
      alert(`Save failed: ${msg}`);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isReady) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-black text-[#f97316] space-y-4">
        <div className="animate-pulse text-lg font-display tracking-widest">LOADING LIBRARY</div>
      </div>
    );
  }

  // Generate class to pause GIFs in gallery when tab is not visible
  const visibilityClass = isTabVisible ? '' : 'pause-animations';

  return (
    <div className={`flex flex-col h-screen bg-black text-white overflow-hidden ${visibilityClass}`}>
      <style dangerouslySetInnerHTML={{__html: `
        .checkerboard {
          background-image: linear-gradient(45deg, #131316 25%, transparent 25%),
                            linear-gradient(-45deg, #131316 25%, transparent 25%),
                            linear-gradient(45deg, transparent 75%, #131316 75%),
                            linear-gradient(-45deg, transparent 75%, #131316 75%);
          background-size: 20px 20px;
          background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: #0a0a0a; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.2); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.35); }

        .pause-animations img[src$=".gif"],
        .pause-animations img[src$=".webp"] {
          /* Note: Browsers natively throttle off-screen media.
             This class is a hook for future manual canvas rendering freezes if needed,
             or CSS animation pausing if CSS anims are used. Native GIFs pause automatically when hidden. */
        }
      `}} />

      {/* APP HEADER */}
      <header className="h-10 flex items-center justify-between px-4 border-b border-white/10 bg-black shrink-0 z-20">
        <span className="text-xs font-bold tracking-[0.2em] text-[#f97316] uppercase">DV3 EDITOR</span>
        <div className="flex items-center gap-3">
          {dirHandle ? (
            <button
              onClick={handleSelectFolder}
              className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white/80 transition-colors"
              title="Change folder"
            >
              <FolderOpen className="w-3.5 h-3.5 text-[#f97316]" />
              <span className="truncate max-w-[200px]">{dirHandle.name}</span>
            </button>
          ) : (
            <button
              onClick={handleSelectFolder}
              className="flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300 transition-colors"
              title="Connect animations folder to enable save"
            >
              <FolderOpen className="w-3.5 h-3.5" />
              <span>Connect folder</span>
            </button>
          )}
          <button
            onClick={() => setShowSettings(true)}
            className="p-1.5 text-white/40 hover:text-white transition-colors rounded hover:bg-white/10"
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </header>

      {uploadError && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[200] bg-red-900 border border-red-700 text-white px-4 py-3 rounded shadow-2xl flex flex-col items-center gap-2 max-w-lg">
          <span className="font-bold text-sm">Upload Error</span>
          <pre className="text-[10px] whitespace-pre-wrap text-center opacity-80">{uploadError}</pre>
          <button onClick={() => setUploadError(null)} className="text-xs bg-red-800 px-3 py-1 rounded hover:bg-red-700">Dismiss</button>
        </div>
      )}

      {/* MAIN 3-COLUMN LAYOUT */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Legacy GalleryPanel kept for reference, replaced by SidebarPanel */}
        <SidebarPanel
          activeTab={activeTab}
          onTabChange={setActiveTab}
          inboxItems={inboxItems}
          activeInboxId={activeInboxId}
          libraryAssets={libraryAssets}
          activeLibraryFile={activeLibraryFile}
          dirHandle={dirHandle}
          onSelectInbox={(id) => setActiveInboxId(id)}
          onImport={handleImport}
          onSelectLibrary={handleSelectLibrary}
        />

        <div className="flex-1 flex flex-col min-w-0">
          {!(activeInboxAsset ?? activeAsset) ? (
            <div className="flex-1 flex items-center justify-center text-white/50 bg-black checkerboard">
              Select a file from Inbox to preview and edit.
            </div>
          ) : (
            <>
              <TopToolbar
                activeAsset={(activeInboxAsset ?? activeAsset)!}
                onUndo={handleUndo}
                onRedo={handleRedo}
              />
              <EditorPanel
                activeAsset={(activeInboxAsset ?? activeAsset)!}
                linkedAsset={activeInboxAsset ? undefined : linkedAsset}
                compareMode={activeInboxAsset ? false : compareMode}
                dv3PreviewMode={activeInboxAsset ? false : dv3PreviewMode}
                isExporting={isExporting}
                onToggleCompareMode={activeInboxAsset ? () => {} : () => setCompareMode(!compareMode)}
                onToggleDv3Preview={activeInboxAsset ? () => {} : () => setDv3PreviewMode(!dv3PreviewMode)}
                onUpdateAsset={activeInboxAsset ? () => {} : updateAsset}
                onApplyEdit={applyEdit}
              />
            </>
          )}
        </div>

        <TagPanel
          item={activeInboxItem}
          libraryAsset={activeLibraryAsset}
          isSaving={isSaving}
          saveStatus={saveStatus}
          onSave={handleSave}
          onConnectFolder={handleSelectFolder}
          onDuplicate={activeInboxItem ? handleDuplicateInbox : undefined}
          onDelete={activeInboxItem ? handleDeleteInbox : undefined}
        />
      </div>

      {showSettings && (
        <SettingsModal
          settings={settings}
          folderName={dirHandle?.name ?? null}
          onClose={() => setShowSettings(false)}
          onSave={handleSaveSettings}
          onSelectFolder={handleSelectFolder}
        />
      )}

      {isExporting && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="bg-black border border-white/10 rounded-lg shadow-2xl w-[400px] overflow-hidden p-6 text-center">
            <h2 className="font-display text-white mb-4 text-lg">Rendering Animations</h2>

            <div className="w-full h-3 bg-white/10 rounded-full overflow-hidden mb-3 border border-white/10">
              <div
                className="h-full bg-[#f97316] transition-all duration-300 ease-out"
                style={{ width: `${exportProgress}%` }}
              />
            </div>

            <p className="text-sm text-[#00d2ff] font-mono mb-2">{exportStatus}</p>
            <p className="text-xs text-white/50">Please do not close this tab. WASM encoding is running locally.</p>
          </div>
        </div>
      )}

      {isImporting && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="bg-black border border-white/10 rounded-lg shadow-2xl w-[400px] overflow-hidden p-6 text-center">
            <h2 className="font-display text-white mb-4 text-lg">Importing Files</h2>

            <div className="w-full h-3 bg-white/10 rounded-full overflow-hidden mb-3 border border-white/10">
              <div className="h-full bg-[#f97316] animate-pulse w-full" />
            </div>

            <p className="text-sm text-[#00d2ff] font-mono mb-2">{importStatus}</p>
            <p className="text-xs text-white/50">Please do not close this tab. Files are being written locally.</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}
