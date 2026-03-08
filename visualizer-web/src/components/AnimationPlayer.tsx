import * as React from 'react';
import { useState, useEffect } from 'react';

interface Props {
  src: string | null;
  /** Animation height as % of viewport height (default 45) */
  sizePercent?: number;
  /** Radial gradient opacity 0-1 (default 0.92) */
  gradientOpacity?: number;
  /** How far the transparent center extends as % of animation area (default 55) */
  gradientReach?: number;
  /** Crossfade duration ms (default 300) */
  fadeDuration?: number;
}

export const AnimationPlayer: React.FC<Props> = ({
  src,
  sizePercent = 45,
  gradientOpacity = 0.92,
  gradientReach = 55,
  fadeDuration = 300,
}) => {
  const [currentSrc, setCurrentSrc] = useState<string | null>(src);
  const [nextSrc, setNextSrc] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);

  useEffect(() => {
    if (src === currentSrc) return;
    if (!src) { setCurrentSrc(null); return; }
    setNextSrc(src);
    setTransitioning(true);
    const t = setTimeout(() => {
      setCurrentSrc(src);
      setNextSrc(null);
      setTransitioning(false);
    }, fadeDuration);
    return () => clearTimeout(t);
  }, [src, fadeDuration]);

  const size = `${sizePercent}vh`;
  // Radial gradient: transparent ellipse in center, black at edges
  const gradient = `radial-gradient(ellipse ${size} ${size} at center, transparent 0%, transparent ${gradientReach}%, rgba(0,0,0,${gradientOpacity}) 100%)`;

  return (
    <div className="relative w-full h-full" style={{ background: '#000' }}>
      {/* Current animation */}
      {currentSrc && (
        <img
          key={`cur-${currentSrc}`}
          src={currentSrc}
          alt=""
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 object-contain"
          style={{
            height: size,
            width: size,
            opacity: transitioning ? 0 : 1,
            transition: `opacity ${fadeDuration}ms ease-in-out`,
          }}
        />
      )}
      {/* Next animation fading in */}
      {nextSrc && (
        <img
          key={`nxt-${nextSrc}`}
          src={nextSrc}
          alt=""
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 object-contain"
          style={{
            height: size,
            width: size,
            opacity: transitioning ? 1 : 0,
            transition: `opacity ${fadeDuration}ms ease-in-out`,
          }}
        />
      )}
      {/* Fullscreen gradient mask — transparent center, black edges */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: gradient }}
      />
    </div>
  );
};
