import * as React from 'react';
import { useState, useEffect } from 'react';

interface Props {
  src: string | null;
  /** Animation height as % of viewport height (default 65) */
  sizePercent?: number;
  /** Edge opacity 0-100 — how opaque the black edges are (default 85) */
  gradientOpacity?: number;
  /** How far inward the gradient reaches, % of animation area (default 70) */
  gradientSize?: number;
  /** Crossfade duration ms (default 300) */
  fadeDuration?: number;
}

export const AnimationPlayer: React.FC<Props> = ({
  src,
  sizePercent = 65,
  gradientOpacity = 85,
  gradientSize = 70,
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

  // Match the Pygame GradientOverlay logic:
  // - gradientSize controls how far inward the fade reaches (0-100)
  //   At 100 the entire surface fades; at 0 only the very edge is darkened.
  // - gradientOpacity controls peak edge alpha (0-100)
  //
  // The "inner" ellipse (fully transparent) shrinks as gradientSize increases.
  // innerRadius = 50% * (1 - gradientSize/100) of the element
  // At gradientSize=70: inner = 50% * 0.3 = 15% — so transparent from 0-15%, fading 15-50%
  const maxAlpha = gradientOpacity / 100;
  const innerPct = 50 * (1 - gradientSize / 100); // % from center where fade starts

  // Build gradient on the animation-sized overlay (not fullscreen)
  // This sits directly on top of the animation img and masks its edges
  const animGradient = [
    `radial-gradient(ellipse 50% 50% at center,`,
    `transparent ${innerPct}%,`,
    `rgba(0,0,0,${(maxAlpha * 0.3).toFixed(3)}) ${innerPct + (50 - innerPct) * 0.3}%,`,
    `rgba(0,0,0,${(maxAlpha * 0.6).toFixed(3)}) ${innerPct + (50 - innerPct) * 0.6}%,`,
    `rgba(0,0,0,${maxAlpha.toFixed(3)}) 50%)`,
  ].join(' ');

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
      {/* Gradient overlay — sized to animation area, covers edges/watermarks */}
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
        style={{
          width: size,
          height: size,
          background: animGradient,
        }}
      />
    </div>
  );
};
