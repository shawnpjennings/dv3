export const EMOTIONS = [
  'happy', 'excited', 'sad', 'thinking', 'confused',
  'laughing', 'surprised', 'calm', 'alert', 'tired',
  'sarcastic', 'neutral', 'concerned', 'curious', 'proud'
];

export const CONTEXTS = [
  'music', 'weather', 'special', 'idle', 'system'
];

export const STATES = [
  'idle',
  'listening',
  'processing',
  'thinking',
] as const;

export type StateTag = typeof STATES[number];
