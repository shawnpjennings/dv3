export type ActionType =
  | 'FLIP_H' | 'FLIP_V' | 'SPEED' | 'REVERSE'
  | 'BRIGHTNESS' | 'CONTRAST' | 'INVERT' | 'GRAYSCALE'
  | 'BG_SWAP' | 'BG_THRESHOLD' | 'BG_COLOR'
  | 'HUE' | 'SATURATION' | 'VIGNETTE' | 'CIRCLE_MASK'
  | 'PADDING' | 'SQUARE_CROP' | 'POSITION_X' | 'POSITION_Y'
  | 'OUTFILL_ENABLED' | 'OUTFILL_COLOR';

export interface EditAction {
  type: ActionType;
  value: number | boolean;
}

export type AssetTheme = 'dark' | 'light' | 'both';

/** A file in data/animations/inbox/ — imported but not yet tagged or saved */
export interface InboxItem {
  id: string;
  /** The actual File object (from file picker or copied from disk) */
  file: File;
  /** Object URL for preview — revoke on cleanup */
  previewUrl: string;
  /** Original filename */
  name: string;
  /** MIME type */
  type: string;
  /** Non-destructive edit stack */
  editStack: EditAction[];
  historyIndex: number;
}

/** A tagged, baked animation in data/animations/ — has a manifest entry */
export interface LibraryAsset {
  /** filename only, e.g. "floyd_prism.webp" */
  file: string;
  theme: AssetTheme;
  emotions: string[];
  states: string[];
  /** Free-form custom tags */
  tags: string[];
  title: string;
  notes: string;
  /** Object URL for preview (loaded on demand) */
  previewUrl?: string;
}

/** Shape of data/animations/manifest.json */
export interface Manifest {
  version: 1;
  assets: LibraryAsset[];
}

/** Payload for the TagPanel's save action */
export interface SavePayload {
  filename: string;
  theme: AssetTheme;
  emotions: string[];
  states: string[];
  tags: string[];
  title: string;
  notes: string;
}

// Legacy — kept temporarily for EditorPanel compat, remove after full migration
export interface Asset {
  id: string;
  originalFile: File;
  fileUrl: string;
  name: string;
  type: string;
  emotion: string;
  additionalEmotions: string[];
  context: string;
  theme: AssetTheme;
  title: string;
  notes: string;
  editStack: EditAction[];
  historyIndex: number;
  linkedVariantId?: string;
  lastExportedAt?: string;
}

export interface EditorSettings {
  defaultPadding: number;
}

export interface BatchRenamePayload {
  prefix: string;
  tag: string;
  startIndex: number;
}
