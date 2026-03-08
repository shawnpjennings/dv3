import { useEffect, useState, useRef } from 'react';
import { AnimationPlayer } from './components/AnimationPlayer';
import { loadManifest, buildIndex, pickAnimation } from './lib/manifest';
import type { AnimationIndex } from './lib/manifest';
import './index.css';

export default function App() {
  const [currentSrc, setCurrentSrc] = useState<string | null>(null);
  const [status, setStatus] = useState('Loading...');
  const indexRef = useRef<AnimationIndex | null>(null);

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
    }).catch(() => setStatus('Failed to load manifest'));
  }, []);

  return (
    <div className="w-screen h-screen bg-black">
      <AnimationPlayer src={currentSrc} />
      {status && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <p className="text-white/20 text-sm font-mono text-center px-8">{status}</p>
        </div>
      )}
    </div>
  );
}
