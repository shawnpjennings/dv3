export const EMOTIONS = [
  'happy', 'excited', 'sad', 'angry', 'confused',
  'laughing', 'surprised', 'calm', 'alert', 'tired',
  'sarcastic', 'neutral', 'concerned', 'curious', 'proud',
  'roasting',
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

export const EVENT_TAGS = [
  'music_playing',
  'timer_alert',
  'spotify_active',
  'weather_update',
  'wake_word',
  'tool_call',
] as const;

export type EventTag = typeof EVENT_TAGS[number];
