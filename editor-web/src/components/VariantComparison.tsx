import * as React from 'react';
import { useState, useRef } from 'react';
import { Sliders } from 'lucide-react';

interface VariantComparisonProps {
  darkUrl: string;
  lightUrl: string;
}

export const VariantComparison: React.FC<VariantComparisonProps> = ({ darkUrl, lightUrl }) => {
  const [position, setPosition] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const clientX = 'touches' in e ? e.touches[0].clientX : (e as React.MouseEvent).clientX;
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    setPosition((x / rect.width) * 100);
  };

  return (
    <div
      ref={containerRef}
      className="relative w-[750px] h-[750px] cursor-ew-resize select-none shadow-2xl overflow-hidden bg-[#0a0a0c] rounded-full ring-1 ring-white/10"
      onMouseMove={e => e.buttons === 1 && handleMouseMove(e)}
      onTouchMove={handleMouseMove}
      onMouseDown={handleMouseMove}
    >
      <img src={darkUrl} className="absolute inset-0 w-full h-full object-contain pointer-events-none" alt="Dark Variant" />

      <div className="absolute top-0 left-0 bottom-0 overflow-hidden" style={{ width: `${position}%` }}>
        <img src={lightUrl} className="absolute top-0 left-0 w-[750px] h-[750px] max-w-none object-contain pointer-events-none" alt="Light Variant" />
      </div>

      <div className="absolute top-0 bottom-0 w-1 bg-[#00d2ff] shadow-[0_0_10px_rgba(0,210,255,0.8)] z-10" style={{ left: `calc(${position}% - 2px)` }}>
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 bg-[#00d2ff] rounded-full flex items-center justify-center shadow-lg">
          <Sliders className="w-4 h-4 text-white rotate-90" />
        </div>
      </div>

      <div className="absolute top-8 left-8 bg-black/60 backdrop-blur text-white px-3 py-1.5 rounded-full text-xs font-medium border border-white/10 tracking-wider uppercase">Light</div>
      <div className="absolute top-8 right-8 bg-black/60 backdrop-blur text-white px-3 py-1.5 rounded-full text-xs font-medium border border-white/10 tracking-wider uppercase">Dark</div>
    </div>
  );
};
