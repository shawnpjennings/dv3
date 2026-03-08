import * as React from 'react';
import { useState, useEffect, KeyboardEvent } from 'react';
import { Copy, Trash2 } from 'lucide-react';
import { AssetTheme, InboxItem, LibraryAsset, SavePayload } from '../types';
import { EMOTIONS, STATES, EVENT_TAGS } from '../constants';
import { CircleCheck } from './CircleCheck';

interface TagPanelProps {
  /** The inbox item currently selected — null if nothing selected */
  item: InboxItem | null;
  /** If re-editing a library asset, pre-populate from here */
  libraryAsset?: LibraryAsset | null;
  /** Whether save is in progress */
  isSaving: boolean;
  /** Status message to show below save button */
  saveStatus: string;
  /** Called when user clicks Save */
  onSave: (payload: SavePayload) => void;
  /** Called to open the folder picker (shown inline when no folder is connected) */
  onConnectFolder?: () => void;
  /** Called when user clicks Duplicate */
  onDuplicate?: () => void;
  /** Called when user clicks Remove */
  onDelete?: () => void;
}

export function TagPanel({
  item,
  libraryAsset,
  isSaving,
  saveStatus,
  onSave,
  onConnectFolder,
  onDuplicate,
  onDelete,
}: TagPanelProps) {
  const [selectedEmotions, setSelectedEmotions] = useState<string[]>([]);
  const [selectedStates, setSelectedStates] = useState<string[]>([]);
  const [customTags, setCustomTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [filename, setFilename] = useState('');
  const [theme, setTheme] = useState<AssetTheme>('dark');

  // Reset all local state when the selected item changes
  useEffect(() => {
    if (item === null) {
      setSelectedEmotions([]);
      setSelectedStates([]);
      setCustomTags([]);
      setTagInput('');
      setFilename('');
      setTheme('dark');
      return;
    }

    // Pre-populate from libraryAsset if re-editing, otherwise from item
    if (libraryAsset) {
      setSelectedEmotions(libraryAsset.emotions ?? []);
      setSelectedStates(libraryAsset.states ?? []);
      setCustomTags(libraryAsset.tags ?? []);
      setFilename(libraryAsset.file.replace(/\.[^/.]+$/, ''));
      setTheme(libraryAsset.theme ?? 'dark');
    } else {
      setSelectedEmotions([]);
      setSelectedStates([]);
      setCustomTags([]);
      setFilename(item.name.replace(/\s+/g, '_'));
      setTheme('dark');
    }
    setTagInput('');
  }, [item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleEmotion = (emotion: string) => {
    setSelectedEmotions(prev =>
      prev.includes(emotion) ? prev.filter(e => e !== emotion) : [...prev, emotion]
    );
  };

  const toggleState = (state: string) => {
    setSelectedStates(prev =>
      prev.includes(state) ? prev.filter(s => s !== state) : [...prev, state]
    );
  };

  const handleTagInputKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const raw = tagInput.trim().toLowerCase().replace(/\s+/g, '_');
      if (raw && !customTags.includes(raw)) {
        setCustomTags(prev => [...prev, raw]);
      }
      setTagInput('');
    }
  };

  const removeTag = (tag: string) => {
    setCustomTags(prev => prev.filter(t => t !== tag));
  };

  const handleFilenameBlur = () => {
    setFilename(prev => prev.trim().replace(/\s+/g, '_'));
  };

  const canSave =
    filename.trim() !== '' &&
    (selectedEmotions.length > 0 || selectedStates.length > 0 || customTags.length > 0);

  const handleSave = () => {
    if (!canSave || isSaving) return;
    onSave({
      filename: filename.trim(),
      theme,
      emotions: selectedEmotions,
      states: selectedStates,
      tags: customTags,
      title: filename.trim(),
      notes: '',
    });
  };

  // Empty state
  if (item === null) {
    return (
      <div className="w-[320px] flex-none bg-[#0a0a0a] border-l border-white/10 flex items-center justify-center">
        <p className="text-white/30 text-sm text-center px-6">
          Select an inbox file to tag it
        </p>
      </div>
    );
  }

  const sectionHeader = 'text-xs font-bold tracking-wider text-[#00d2ff] uppercase mb-2 flex items-center gap-1.5';

  return (
    <div className="w-[320px] flex-none bg-[#0a0a0a] border-l border-white/10 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-white/10">
        <p className="text-[11px] text-white/60 font-mono truncate">{item.name}</p>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-4 space-y-5">

        {/* EMOTIONS */}
        <section>
          <h3 className={sectionHeader}>Emotions</h3>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {EMOTIONS.map(emotion => (
              <CircleCheck
                key={emotion}
                label={emotion}
                checked={selectedEmotions.includes(emotion)}
                onChange={() => toggleEmotion(emotion)}
                className="text-xs"
              />
            ))}
          </div>
        </section>

        {/* STATES */}
        <section>
          <h3 className={sectionHeader}>States</h3>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {STATES.map(state => (
              <CircleCheck
                key={state}
                label={state}
                checked={selectedStates.includes(state)}
                onChange={() => toggleState(state)}
                className="text-xs"
              />
            ))}
          </div>
        </section>

        {/* EVENT TAGS */}
        <section>
          <h3 className={sectionHeader}>Events</h3>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {EVENT_TAGS.map(tag => (
              <button
                key={tag}
                onClick={() => {
                  if (!customTags.includes(tag)) setCustomTags(prev => [...prev, tag]);
                  else setCustomTags(prev => prev.filter(t => t !== tag));
                }}
                className={
                  customTags.includes(tag)
                    ? 'bg-[#f97316]/30 text-[#f97316] text-xs px-2 py-0.5 rounded border border-[#f97316]/50'
                    : 'bg-white/5 text-white/40 text-xs px-2 py-0.5 rounded border border-white/10 hover:text-white/60 hover:border-white/20 transition-colors'
                }
              >
                {tag}
              </button>
            ))}
          </div>
        </section>

        {/* TAGS */}
        <section>
          <h3 className={sectionHeader}>Tags</h3>
          {customTags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {customTags.map(tag => (
                <span
                  key={tag}
                  className="bg-[#f97316]/20 text-[#f97316] text-xs px-2 py-0.5 rounded flex items-center gap-1"
                >
                  {tag}
                  <button
                    onClick={() => removeTag(tag)}
                    className="hover:text-white transition-colors leading-none"
                    aria-label={`Remove tag ${tag}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <input
            type="text"
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={handleTagInputKeyDown}
            placeholder="Type + Enter to add"
            className="w-full bg-white/5 border border-white/10 rounded px-2 py-1.5 text-xs text-white placeholder-white/20 focus:outline-none focus:border-[#f97316]/50"
          />
        </section>

        {/* FILENAME */}
        <section>
          <h3 className={sectionHeader}>Filename</h3>
          <input
            type="text"
            value={filename}
            onChange={e => setFilename(e.target.value)}
            onBlur={handleFilenameBlur}
            placeholder="e.g. happy_bounce"
            className="w-full bg-white/5 border border-white/10 rounded px-2 py-1.5 text-xs text-white placeholder-white/20 focus:outline-none focus:border-[#f97316]/50"
          />
        </section>

        {/* THEME */}
        <section>
          <h3 className={sectionHeader}>Theme</h3>
          <div className="flex gap-4">
            {(['dark', 'light', 'both'] as AssetTheme[]).map(t => (
              <label key={t} className="flex items-center gap-1.5 cursor-pointer group">
                <input
                  type="radio"
                  name="theme"
                  className="accent-[#f97316] cursor-pointer"
                  checked={theme === t}
                  onChange={() => setTheme(t)}
                />
                <span className="text-xs text-white/70 group-hover:text-white transition-colors capitalize">
                  {t}
                </span>
              </label>
            ))}
          </div>
        </section>
      </div>

      {/* Save + actions footer */}
      <div className="px-4 pb-5 pt-4 border-t border-white/10 space-y-2">
        <button
          onClick={handleSave}
          disabled={!canSave || isSaving}
          className={
            canSave && !isSaving
              ? 'bg-[#f97316] text-black font-black py-3.5 w-full rounded hover:bg-[#ea6c0a] transition-colors text-sm tracking-widest shadow-lg shadow-[#f97316]/30'
              : 'bg-white/10 text-white/30 font-bold py-3.5 w-full rounded cursor-not-allowed text-sm'
          }
        >
          {isSaving ? 'SAVING…' : 'SAVE'}
        </button>

        {saveStatus === 'no-folder' ? (
          <div className="text-center space-y-1">
            <p className="text-[10px] text-amber-400">No folder connected</p>
            {onConnectFolder && (
              <button
                onClick={onConnectFolder}
                className="text-[10px] text-[#f97316] hover:text-[#fb923c] underline transition-colors"
              >
                Connect animations folder
              </button>
            )}
          </div>
        ) : saveStatus ? (
          <p className="text-[10px] text-center text-white/40">{saveStatus}</p>
        ) : !canSave && !isSaving ? (
          <p className="text-[10px] text-center text-white/25">
            {filename.trim() === ''
              ? 'Enter a filename to enable save'
              : 'Select at least one emotion, state, or tag'}
          </p>
        ) : null}

        {/* Duplicate / Remove */}
        {(onDuplicate || onDelete) && (
          <div className="flex gap-2 pt-1">
            {onDuplicate && (
              <button
                onClick={onDuplicate}
                className="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 bg-white/8 hover:bg-white/15 text-white/70 hover:text-white rounded text-xs transition-colors border border-white/10"
              >
                <Copy className="w-3.5 h-3.5" />
                Duplicate
              </button>
            )}
            {onDelete && (
              <button
                onClick={onDelete}
                className="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 bg-red-900/30 hover:bg-red-800/60 text-red-400 hover:text-red-200 rounded text-xs transition-colors border border-red-800/40"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Remove
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
