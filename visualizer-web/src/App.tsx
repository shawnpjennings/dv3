import { useEffect, useState, useRef, useCallback } from 'react';
import { AnimationPlayer } from './components/AnimationPlayer';
import { loadManifest, buildIndex, pickAnimation } from './lib/manifest';
import { VisualizerWSClient } from './lib/wsClient';
import { AudioClient } from './lib/audioClient';
import type { AnimationIndex, VisualizerEvent } from './lib/manifest';
import './index.css';

interface VisualizerConfig {
  animationSizePercent: number;
  gradientOpacity: number;
  gradientSize: number;
  crossfadeDurationMs: number;
  contextualDurationMs: number;
  idleRotationMs: number;
  wsUrl: string;
}

const DEFAULT_CONFIG: VisualizerConfig = {
  animationSizePercent: 65,
  gradientOpacity: 85,
  gradientSize: 50,
  crossfadeDurationMs: 300,
  contextualDurationMs: 8000,
  idleRotationMs: 12000,
  wsUrl: 'ws://localhost:8765/ws',
};

async function loadConfig(): Promise<VisualizerConfig> {
  try {
    const res = await fetch('/config.json');
    if (!res.ok) return DEFAULT_CONFIG;
    const json = await res.json();
    return { ...DEFAULT_CONFIG, ...json };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export default function App() {
  const [currentSrc, setCurrentSrc] = useState<string | null>(null);
  const [status, setStatus] = useState('Loading...');
  const [wsConnected, setWsConnected] = useState(false);
  const [micActive, setMicActive] = useState(false);
  const [wakewordActive, setWakewordActive] = useState(false);
  const wakewordTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [config, setConfig] = useState<VisualizerConfig>(DEFAULT_CONFIG);
  const [showSettings, setShowSettings] = useState(false);
  const indexRef = useRef<AnimationIndex | null>(null);
  const clientRef = useRef<VisualizerWSClient | null>(null);
  const audioRef = useRef<AudioClient | null>(null);
  const lastEmotionRef = useRef<string>('neutral');
  const currentSrcRef = useRef<string | null>(null);
  const contextualTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Keep ref in sync with state
  const updateSrc = useCallback((url: string) => {
    currentSrcRef.current = url;
    setCurrentSrc(url);
  }, []);

  const startIdleRotation = useCallback((cfg: VisualizerConfig) => {
    if (idleTimerRef.current) clearInterval(idleTimerRef.current);
    idleTimerRef.current = setInterval(() => {
      if (!indexRef.current) return;
      const idx = indexRef.current;

      // Prefer idle-appropriate animations: 50% idle state, 30% neutral emotion,
      // 20% random emotion for variety.
      const roll = Math.random();
      let url: string | null = null;

      if (roll < 0.5 && idx.byState['idle']?.length) {
        url = pickAnimation(idx, { type: 'state', state: 'idle' }, currentSrcRef.current);
      } else if (roll < 0.8 && idx.byEmotion['neutral']?.length) {
        url = pickAnimation(idx, { type: 'emotion', emotion: 'neutral' }, currentSrcRef.current);
      } else {
        const emotions = Object.keys(idx.byEmotion);
        if (emotions.length > 0) {
          const nextEmotion = emotions[Math.floor(Math.random() * emotions.length)];
          lastEmotionRef.current = nextEmotion;
          url = pickAnimation(idx, { type: 'emotion', emotion: nextEmotion }, currentSrcRef.current);
        }
      }

      if (url) updateSrc(url);
    }, cfg.idleRotationMs);
  }, [updateSrc]);

  const stopIdleRotation = useCallback(() => {
    if (idleTimerRef.current) {
      clearInterval(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  }, []);

  const handleEvent = useCallback((event: VisualizerEvent, cfg: VisualizerConfig) => {
    // Wake word indicator — flash amber for 2 seconds
    if (event.type === 'wakeword') {
      setWakewordActive(true);
      if (wakewordTimerRef.current) clearTimeout(wakewordTimerRef.current);
      wakewordTimerRef.current = setTimeout(() => setWakewordActive(false), 2000);
      return;
    }

    if (!indexRef.current) return;
    stopIdleRotation();

    const animUrl = pickAnimation(indexRef.current, event, currentSrcRef.current);
    if (!animUrl) return;

    if (event.type === 'tag') {
      updateSrc(animUrl);
      if (contextualTimerRef.current) clearTimeout(contextualTimerRef.current);
      contextualTimerRef.current = setTimeout(() => {
        if (!indexRef.current) return;
        const returnUrl = pickAnimation(indexRef.current, {
          type: 'emotion',
          emotion: lastEmotionRef.current,
        }, currentSrcRef.current);
        if (returnUrl) updateSrc(returnUrl);
      }, cfg.contextualDurationMs);
    } else {
      if (contextualTimerRef.current) {
        clearTimeout(contextualTimerRef.current);
        contextualTimerRef.current = null;
      }
      if (event.type === 'emotion') {
        lastEmotionRef.current = event.emotion;
      }
      updateSrc(animUrl);
    }
  }, [stopIdleRotation, updateSrc]);

  // Start mic capture when WS connects
  const startMic = useCallback(() => {
    const client = clientRef.current;
    if (!client?.connected) return;

    if (!audioRef.current) {
      audioRef.current = new AudioClient();
    }

    audioRef.current
      .startCapture((data) => client.sendBinary(data))
      .then(() => setMicActive(true))
      .catch((err) => {
        console.error('[App] Failed to start mic:', err);
        setMicActive(false);
      });
  }, []);

  useEffect(() => {
    Promise.all([loadConfig(), loadManifest()]).then(([cfg, manifest]) => {
      setConfig(cfg);

      if (!manifest || manifest.assets.length === 0) {
        setStatus('No animations tagged yet — use DV3 Editor to tag animations');
        return;
      }
      indexRef.current = buildIndex(manifest, 'dark');
      const url = pickAnimation(indexRef.current, { type: 'emotion', emotion: 'neutral' });
      if (url) {
        updateSrc(url);
        setStatus('');
      } else {
        setStatus('No neutral animation found');
      }

      startIdleRotation(cfg);

      const audio = new AudioClient();
      audioRef.current = audio;

      const client = new VisualizerWSClient({
        url: cfg.wsUrl,
        onEvent: (event) => handleEvent(event, cfg),
        onAudio: (pcm) => audio.playAudio(pcm),
        onConnect: () => {
          setWsConnected(true);
          stopIdleRotation();
          // Auto-start mic capture on WS connect
          audio
            .startCapture((data) => client.sendBinary(data))
            .then(() => setMicActive(true))
            .catch(() => setMicActive(false));
        },
        onDisconnect: () => {
          setWsConnected(false);
          setMicActive(false);
          audio.stopCapture();
          audio.resetPlayback();
          startIdleRotation(cfg);
        },
      });
      client.connect();
      clientRef.current = client;
    }).catch(() => setStatus('Failed to load manifest'));

    return () => {
      audioRef.current?.stopCapture();
      clientRef.current?.disconnect();
      if (contextualTimerRef.current) clearTimeout(contextualTimerRef.current);
      if (idleTimerRef.current) clearInterval(idleTimerRef.current);
    };
  }, [handleEvent, startIdleRotation, stopIdleRotation, updateSrc, startMic]);

  // Toggle settings with 'S' key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 's' || e.key === 'S') setShowSettings((v) => !v);
      if (e.ctrlKey && e.shiftKey && (e.key === 'v' || e.key === 'V')) {
        e.preventDefault();
        setShowSettings((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="relative w-screen h-screen bg-black">
      <AnimationPlayer
        src={currentSrc}
        sizePercent={config.animationSizePercent}
        gradientOpacity={config.gradientOpacity}
        gradientSize={config.gradientSize}
        fadeDuration={config.crossfadeDurationMs}
      />
      {status && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <p className="text-white/20 text-sm font-mono text-center px-8">{status}</p>
        </div>
      )}
      {/* Status indicator */}
      <div className="absolute top-3 right-3 pointer-events-none flex items-center gap-2 z-10">
        {/* Wake word indicator */}
        {wakewordActive && (
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="text-amber-400/70 text-xs font-mono">wake</span>
          </div>
        )}
        {/* Mic indicator */}
        <div className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full ${
            micActive ? 'bg-red-400 animate-pulse' : 'bg-white/10'
          }`} />
          <span className="text-white/10 text-xs font-mono">
            {micActive ? 'mic' : ''}
          </span>
        </div>
        {/* WS indicator */}
        <div className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full ${
            wsConnected ? 'bg-green-400' : 'bg-white/10'
          }`} />
          <span className="text-white/10 text-xs font-mono">
            {wsConnected ? 'live' : 'idle'}
          </span>
        </div>
      </div>
      {/* Settings panel — toggle with S key */}
      {showSettings && (
        <div className="absolute bottom-4 left-4 z-20 bg-black/80 border border-white/10 rounded-lg p-4 font-mono text-xs text-white/70 space-y-3 w-64">
          <div className="text-white/40 text-[10px] uppercase tracking-wider mb-2">
            Settings (press S to close)
          </div>
          <label className="flex items-center justify-between">
            <span>Gradient Opacity</span>
            <span className="text-white/40 w-8 text-right">{config.gradientOpacity}</span>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={config.gradientOpacity}
            onChange={(e) => setConfig((c) => ({ ...c, gradientOpacity: Number(e.target.value) }))}
            className="w-full accent-white/50"
          />
          <label className="flex items-center justify-between">
            <span>Gradient Size</span>
            <span className="text-white/40 w-8 text-right">{config.gradientSize}</span>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={config.gradientSize}
            onChange={(e) => setConfig((c) => ({ ...c, gradientSize: Number(e.target.value) }))}
            className="w-full accent-white/50"
          />
          <label className="flex items-center justify-between">
            <span>Animation Size</span>
            <span className="text-white/40 w-8 text-right">{config.animationSizePercent}%</span>
          </label>
          <input
            type="range"
            min={20}
            max={100}
            value={config.animationSizePercent}
            onChange={(e) => setConfig((c) => ({ ...c, animationSizePercent: Number(e.target.value) }))}
            className="w-full accent-white/50"
          />
        </div>
      )}
    </div>
  );
}
