export type ActionType =
  | 'FLIP_H'
  | 'FLIP_V'
  | 'SPEED'
  | 'REVERSE'
  | 'BRIGHTNESS'
  | 'CONTRAST'
  | 'INVERT'
  | 'GRAYSCALE'
  | 'BG_SWAP'
  | 'BG_THRESHOLD'
  | 'BG_COLOR'
  | 'HUE'
  | 'SATURATION'
  | 'VIGNETTE'
  | 'CIRCLE_MASK'
  | 'PADDING'
  | 'SQUARE_CROP'
  | 'POSITION_X'
  | 'POSITION_Y'
  | 'OUTFILL_ENABLED'
  | 'OUTFILL_COLOR';

export interface EditAction {
  type: ActionType;
  value: number | boolean;
}

export type AssetTheme = 'dark' | 'light' | 'both';

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
}

export interface EditorSettings {
  exportRoot: string;
  defaultPadding: number;
}

export interface BatchRenamePayload {
  prefix: string;
  tag: string;
  startIndex: number;
}
