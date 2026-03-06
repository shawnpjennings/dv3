import * as React from 'react';
import { useState, useMemo, useEffect, useRef } from 'react';
import { Asset, EditorSettings, ActionType, BatchRenamePayload } from './types';
import { GalleryPanel } from './components/GalleryPanel';
import { TopToolbar } from './components/TopToolbar';
import { EditorPanel } from './components/EditorPanel';
import { SettingsModal } from './components/SettingsModal';
import { ErrorBoundary } from './components/ErrorBoundary';
import { deleteAssetFromDB, loadAssetsFromDB, saveAssetToDB, loadSettingsFromDB, saveSettingsToDB } from './lib/db';
import { executeBatchExport } from './lib/exportUtils';
import { validateUpload } from './lib/validation';

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
    exportRoot: 'data/animations',
    defaultPadding: 0
  });

  const [isExporting, setIsExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState('');
  const [exportProgress, setExportProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Tab visibility state for thumbnail playback optimization
  const [isTabVisible, setIsTabVisible] = useState(true);

  useEffect(() => {
    let isMounted = true;

    const initData = async () => {
      try {
        const [savedAssets, savedSettings] = await Promise.all([
          loadAssetsFromDB(),
          loadSettingsFromDB()
        ]);

        if (!isMounted) return;

        if (savedSettings) {
          setSettings(savedSettings);
        }

        if (savedAssets && savedAssets.length > 0) {
          setAssets(savedAssets);
          setActiveAssetId(savedAssets[0].id);
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

  const activeAsset = assets.find(a => a.id === activeAssetId);
  const linkedAsset = activeAsset?.linkedVariantId ? assets.find(a => a.id === activeAsset.linkedVariantId) : undefined;

  const applyEdit = (type: ActionType, value: number | boolean) => {
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
    if (!activeAsset || activeAsset.historyIndex < 0) return;
    updateAsset(activeAsset.id, { historyIndex: activeAsset.historyIndex - 1 });
  };

  const handleRedo = () => {
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

  const handleLinkVariant = (targetId: string) => {
    if (!activeAsset) return;
    updateAsset(activeAsset.id, { linkedVariantId: targetId });
    updateAsset(targetId, { linkedVariantId: activeAsset.id });
  };

  const handleUnlinkVariant = () => {
    if (!activeAsset || !activeAsset.linkedVariantId) return;
    updateAsset(activeAsset.linkedVariantId, { linkedVariantId: undefined });
    updateAsset(activeAsset.id, { linkedVariantId: undefined });
    setCompareMode(false);
  };

  const doExport = async (assetsToExport: Asset[]) => {
    setIsExporting(true);
    setExportProgress(0);
    setExportStatus('Starting export...');
    try {
      await executeBatchExport(assetsToExport, settings, (status, progress) => {
        setExportStatus(status);
        setExportProgress(progress);
      });
      // Stamp export timestamp on all successfully exported assets
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

  const handleExport = () => {
    if (!activeAsset) return;
    doExport([activeAsset]);
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

  const dv3PathPreview = activeAsset
    ? `${settings.exportRoot}/${activeAsset.emotion !== 'neutral' ? `emotions/${activeAsset.emotion}` : `contextual/${activeAsset.context}`}/${activeAsset.name.replace(/\s+/g, '_').toLowerCase()}.webp`
    : '';

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
    <div className={`flex h-screen bg-black text-white overflow-hidden ${visibilityClass}`}>
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

      {uploadError && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[200] bg-red-900 border border-red-700 text-white px-4 py-3 rounded shadow-2xl flex flex-col items-center gap-2 max-w-lg">
          <span className="font-bold text-sm">Upload Error</span>
          <pre className="text-[10px] whitespace-pre-wrap text-center opacity-80">{uploadError}</pre>
          <button onClick={() => setUploadError(null)} className="text-xs bg-red-800 px-3 py-1 rounded hover:bg-red-700">Dismiss</button>
        </div>
      )}

      <GalleryPanel
        assets={filteredAssets}
        activeAssetId={activeAssetId}
        selectedIds={selectedIds}
        searchQuery={searchQuery}
        filterEmotion={filterEmotion}
        filterContext={filterContext}
        filterType={filterType}
        onSearchChange={setSearchQuery}
        onFilterEmotionChange={setFilterEmotion}
        onFilterContextChange={setFilterContext}
        onFilterTypeChange={setFilterType}
        onUpload={handleFileUpload}
        onSelectAsset={(id) => { setActiveAssetId(id); setCompareMode(false); lastSelectedIdRef.current = id; }}
        onToggleSelection={toggleSelection}
        onBatchExport={handleBatchExport}
        onBatchRename={handleBatchRename}
        onDeleteAsset={handleDeleteAsset}
        onOpenSettings={() => setShowSettings(true)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {!activeAsset ? (
          <div className="flex-1 flex items-center justify-center text-white/50 bg-black checkerboard">
            Select an asset from the gallery to edit.
          </div>
        ) : (
          <>
            <TopToolbar
              activeAsset={activeAsset}
              linkedAsset={linkedAsset}
              availableAssets={assets.filter(a => a.id !== activeAsset.id && !a.linkedVariantId)}
              dv3PathPreview={dv3PathPreview}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onDuplicate={handleDuplicate}
              onDelete={() => handleDeleteAsset(activeAsset.id)}
              onExport={handleExport}
              onLinkVariant={handleLinkVariant}
              onUnlinkVariant={handleUnlinkVariant}
            />
            <EditorPanel
              activeAsset={activeAsset}
              linkedAsset={linkedAsset}
              compareMode={compareMode}
              dv3PreviewMode={dv3PreviewMode}
              isExporting={isExporting}
              onToggleCompareMode={() => setCompareMode(!compareMode)}
              onToggleDv3Preview={() => setDv3PreviewMode(!dv3PreviewMode)}
              onUpdateAsset={updateAsset}
              onApplyEdit={applyEdit}
            />
          </>
        )}
      </div>

      {showSettings && (
        <SettingsModal
          settings={settings}
          onClose={() => setShowSettings(false)}
          onSave={handleSaveSettings}
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
