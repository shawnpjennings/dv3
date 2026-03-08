import { useEffect, useState, useRef } from 'react';
import { AnimationPlayer } from './components/AnimationPlayer';
import { loadManifest, buildIndex, pickAnimation } from './lib/manifest';
import { VisualizerWSClient } from './lib/wsClient';
import type { AnimationIndex } from './lib/manifest';
import './index.css';

export default function App() {
  const [currentSrc, setCurrentSrc] = useState<string | null>(null);
  const [status, setStatus] = useState('Loading...');
  const [wsConnected, setWsConnected] = useState(false);
  const indexRef = useRef<AnimationIndex | null>(null);
  const clientRef = useRef<VisualizerWSClient | null>(null);

  useEffect(() => {
    loadManifest().then((manifest) => {
      if (!manifest || manifest.assets.length === 0) {
        setStatus('No animations tagged yet — use WebPew editor to tag animations');
        return;
      }
      indexRef.current = buildIndex(manifest, 'dark');
      const url = pickAnimation(indexRef.current, { type: 'emotion', emotion: 'neutral' });
      if (url) {
        setCurrentSrc(url);
        setStatus('');
      } else {
        setStatus('No neutral animation found');
      }

      const client = new VisualizerWSClient({
        url: 'ws://localhost:8765/ws',
        onEvent: (event) => {
          if (!indexRef.current) return;
          const animUrl = pickAnimation(indexRef.current, event);
          if (animUrl) setCurrentSrc(animUrl);
        },
        onConnect: () => setWsConnected(true),
        onDisconnect: () => setWsConnected(false),
      });
      client.connect();
      clientRef.current = client;
    }).catch(() => setStatus('Failed to load manifest'));

    return () => {
      clientRef.current?.disconnect();
    };
  }, []);

  return (
    <div className="relative w-screen h-screen bg-black">
      <AnimationPlayer src={currentSrc} />
      {status && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <p className="text-white/20 text-sm font-mono text-center px-8">{status}</p>
        </div>
      )}
      <div className="absolute top-3 right-3 pointer-events-none flex items-center gap-1.5 z-10">
        <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400' : 'bg-yellow-400 animate-pulse'}`} />
        <span className="text-white/20 text-xs font-mono">{wsConnected ? 'live' : 'connecting...'}</span>
      </div>
    </div>
  );
}
