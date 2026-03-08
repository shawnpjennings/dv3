import * as React from 'react';
import { useEffect, useState, useRef } from 'react';
import { Sliders, FlipHorizontal, FlipVertical, FastForward, Maximize, Eye, EyeOff, ChevronDown, ChevronRight, RotateCcw } from 'lucide-react';
import { Asset, ActionType } from '../types';
import { VariantComparison } from './VariantComparison';

interface EditorPanelProps {
  activeAsset: Asset;
  linkedAsset?: Asset;
  compareMode: boolean;
  dv3PreviewMode: boolean;
  isExporting: boolean;
  onToggleCompareMode: () => void;
  onToggleDv3Preview: () => void;
  onUpdateAsset: (id: string, updates: Partial<Asset>) => void;
  onApplyEdit: (type: ActionType, value: number | boolean) => void;
}

export const EditorPanel: React.FC<EditorPanelProps> = ({
  activeAsset,
  linkedAsset,
  compareMode,
  dv3PreviewMode,
  isExporting,
  onToggleCompareMode,
  onToggleDv3Preview,
  onUpdateAsset,
  onApplyEdit,
}) => {
  const PREVIEW_SIZE = 750;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [decodedFrames, setDecodedFrames] = useState<ImageBitmap[]>([]);
  const [frameDurations, setFrameDurations] = useState<number[]>([]);
  const [isDecodingSpeedPreview, setIsDecodingSpeedPreview] = useState(false);
  const [speedPreviewUnavailable, setSpeedPreviewUnavailable] = useState(false);

  const [openSections, setOpenSections] = useState({
    layout: true,
    tone: true,
    temporal: true,
  });

  const toggleSection = (section: keyof typeof openSections) => {
    setOpenSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const applyNumericEdit = (
    type: ActionType,
    rawValue: string,
    min: number,
    max: number
  ) => {
    const parsed = Number(rawValue);
    if (Number.isNaN(parsed)) return;
    const clamped = Math.min(max, Math.max(min, parsed));
    onApplyEdit(type, clamped);
  };

  const activeEditStack = activeAsset.editStack.slice(0, activeAsset.historyIndex + 1);

  const getEditValue = (type: ActionType, defaultValue: number | boolean) => {
    for (let i = activeEditStack.length - 1; i >= 0; i--) {
      if (activeEditStack[i].type === type) {
        return activeEditStack[i].value;
      }
    }
    return defaultValue;
  };

  const speed = getEditValue('SPEED', 1) as number;
  const reverse = getEditValue('REVERSE', false) as boolean;
  const isAnimatedAsset = activeAsset.type === 'image/gif' || activeAsset.type === 'image/webp';
  const useSpeedCanvasPreview = isAnimatedAsset && (speed !== 1 || reverse) && !isExporting;
  const hasLiveSpeedFrames = decodedFrames.length > 1;

  useEffect(() => {
    let cancelled = false;

    const decodeFrames = async () => {
      if (!useSpeedCanvasPreview) {
        setDecodedFrames([]);
        setFrameDurations([]);
        setIsDecodingSpeedPreview(false);
        setSpeedPreviewUnavailable(false);
        return;
      }

      setIsDecodingSpeedPreview(true);

      const decoderCtor = (window as unknown as { ImageDecoder?: new (init: { data: Uint8Array; type: string }) => {
        tracks: { selectedTrack?: { frameCount?: number } };
        decode: (opts: { frameIndex: number }) => Promise<{ image: { duration?: number; close?: () => void } }>;
        close?: () => void;
      } }).ImageDecoder;

      if (!decoderCtor) {
        setSpeedPreviewUnavailable(true);
        setDecodedFrames([]);
        setFrameDurations([]);
        setIsDecodingSpeedPreview(false);
        return;
      }

      try {
        const MAX_PREVIEW_BYTES = 12 * 1024 * 1024;
        const MAX_PREVIEW_FRAMES = 180;
        if (activeAsset.originalFile.size > MAX_PREVIEW_BYTES) {
          setSpeedPreviewUnavailable(true);
          setDecodedFrames([]);
          setFrameDurations([]);
          setIsDecodingSpeedPreview(false);
          return;
        }

        const bytes = new Uint8Array(await activeAsset.originalFile.arrayBuffer());
        const decoder = new decoderCtor({ data: bytes, type: activeAsset.type });
        const advertisedCount = decoder.tracks.selectedTrack?.frameCount;
        const count = advertisedCount ? Math.min(advertisedCount, MAX_PREVIEW_FRAMES) : MAX_PREVIEW_FRAMES;

        const nextFrames: ImageBitmap[] = [];
        const nextDurations: number[] = [];

        for (let i = 0; i < count; i++) {
          let decoded;
          try {
            decoded = await decoder.decode({ frameIndex: i });
          } catch {
            break;
          }

          const { image } = decoded;
          const bitmap = await createImageBitmap(image as unknown as CanvasImageSource);
          nextFrames.push(bitmap);

          // Some implementations report microseconds, others milliseconds.
          const rawDuration = image.duration ?? 100000;
          const durationMs = rawDuration > 1000 ? rawDuration / 1000 : rawDuration;
          nextDurations.push(Math.max(10, Math.round(durationMs)));
          image.close?.();
        }

        decoder.close?.();

        if (!cancelled) {
          setSpeedPreviewUnavailable(nextFrames.length <= 1);
          setDecodedFrames(nextFrames);
          setFrameDurations(nextDurations);
          setIsDecodingSpeedPreview(false);
        } else {
          nextFrames.forEach(frame => frame.close());
        }
      } catch {
        if (!cancelled) {
          setSpeedPreviewUnavailable(true);
          setDecodedFrames([]);
          setFrameDurations([]);
          setIsDecodingSpeedPreview(false);
        }
      }
    };

    decodeFrames();

    return () => {
      cancelled = true;
    };
  }, [activeAsset.id, activeAsset.originalFile, activeAsset.type, useSpeedCanvasPreview]);

  useEffect(() => {
    return () => {
      decodedFrames.forEach(frame => frame.close());
    };
  }, [decodedFrames]);

  useEffect(() => {
    if (!useSpeedCanvasPreview || decodedFrames.length < 2 || !canvasRef.current) return;

    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return;

    const fpsScale = speed > 0 ? speed : 1;
    const frames = reverse ? [...decodedFrames].reverse() : decodedFrames;
    const durations = (reverse ? [...frameDurations].reverse() : frameDurations).map(ms => Math.max(10, ms / fpsScale));

    let frameIndex = 0;
    let raf = 0;
    let lastTime = performance.now();

    const drawFrame = (bitmap: ImageBitmap) => {
      const cw = PREVIEW_SIZE;
      const ch = PREVIEW_SIZE;
      const bw = bitmap.width;
      const bh = bitmap.height;

      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, cw, ch);

      const scale = Math.min(cw / bw, ch / bh);
      const dw = bw * scale;
      const dh = bh * scale;
      const dx = (cw - dw) / 2;
      const dy = (ch - dh) / 2;
      ctx.drawImage(bitmap, dx, dy, dw, dh);
    };

    drawFrame(frames[frameIndex]);

    const tick = (now: number) => {
      const frameDuration = durations[frameIndex] ?? 100;
      if (now - lastTime >= frameDuration) {
        frameIndex = (frameIndex + 1) % frames.length;
        lastTime = now;
        drawFrame(frames[frameIndex]);
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [PREVIEW_SIZE, decodedFrames, frameDurations, reverse, speed, useSpeedCanvasPreview]);

  const previewStyles = (() => {
    let filter = '';
    let transform = '';

    const flipH = getEditValue('FLIP_H', false) as boolean;
    const flipV = getEditValue('FLIP_V', false) as boolean;
    if (flipH) transform += 'scaleX(-1) ';
    if (flipV) transform += 'scaleY(-1) ';

    const bright = getEditValue('BRIGHTNESS', 100) as number;
    const cont = getEditValue('CONTRAST', 100) as number;
    const invert = getEditValue('INVERT', false) as boolean;
    const hue = getEditValue('HUE', 0) as number;
    const sat = getEditValue('SATURATION', 100) as number;
    const grayscale = getEditValue('GRAYSCALE', false) as boolean;

    if (bright !== 100) filter += `brightness(${bright}%) `;
    if (cont !== 100) filter += `contrast(${cont}%) `;
    if (invert) filter += 'invert(100%) ';
    if (grayscale) filter += 'grayscale(100%) ';
    if (hue !== 0) filter += `hue-rotate(${hue}deg) `;
    if (sat !== 100) filter += `saturate(${sat}%) `;

    // PADDING now behaves as a bidirectional zoom offset where:
    // negative = zoom out (smaller subject), positive = zoom in (larger subject).
    const zoomOffset = getEditValue('PADDING', 0) as number;
    const zoomScale = Math.min(2.5, Math.max(0.15, 1 + zoomOffset / 300));
    const cropScale = getEditValue('SQUARE_CROP', false) as boolean ? 1.2 : 1;

    const posX = getEditValue('POSITION_X', 0) as number;
    const posY = getEditValue('POSITION_Y', 0) as number;
    if (posX !== 0) transform += `translateX(${posX}px) `;
    if (posY !== 0) transform += `translateY(${posY}px) `;

    return {
      filter: filter.trim(),
      transform: `${transform.trim()} scale(${cropScale * zoomScale})`,
      transformOrigin: 'center center' as const
    };
  })();

  const zoomOffset = getEditValue('PADDING', 0) as number;
  const outfillEnabled = getEditValue('OUTFILL_ENABLED', false) as boolean;
  const outfillColorNum = getEditValue('OUTFILL_COLOR', 0x000000) as number;
  const outfillColorHex = `#${Math.max(0, Math.min(0xffffff, outfillColorNum)).toString(16).padStart(6, '0')}`;
  const bgSwapEnabled = getEditValue('BG_SWAP', false) as boolean;
  const bgThreshold = getEditValue('BG_THRESHOLD', 24) as number;
  const bgColorValue = getEditValue('BG_COLOR', 0xffffff) as number;
  const bgColorHex = `#${Math.max(0, Math.min(0xffffff, bgColorValue)).toString(16).padStart(6, '0')}`;

  const handleResetEdits = () => {
    onUpdateAsset(activeAsset.id, {
      editStack: [],
      historyIndex: -1,
    });
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 bg-black relative flex items-center justify-center overflow-hidden checkerboard">
        <div className="absolute top-4 right-4 flex gap-2 z-20">
          {linkedAsset && (
            <button
              onClick={onToggleCompareMode}
              className={`flex items-center gap-2 px-4 py-2 rounded text-xs font-bold uppercase tracking-wider backdrop-blur-md border border-white/10 transition-all ${compareMode ? 'bg-white/10 text-[#00d2ff]' : 'bg-black/70 text-white hover:bg-white/10'}`}
            >
              <Sliders className="w-3 h-3" /> Compare Variants
            </button>
          )}
          {!compareMode && (
            <button
              onClick={onToggleDv3Preview}
              className={`flex items-center gap-2 px-4 py-2 rounded text-xs font-bold uppercase tracking-wider backdrop-blur-md border border-white/10 transition-all ${dv3PreviewMode ? 'bg-white/10 text-[#f97316]' : 'bg-black/70 text-white hover:bg-white/10'}`}
            >
              {dv3PreviewMode ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
              Visualizer Preview
            </button>
          )}
        </div>

        {compareMode && linkedAsset ? (
          <VariantComparison darkUrl={activeAsset.fileUrl} lightUrl={linkedAsset.fileUrl} />
        ) : (
          <div className="relative transition-all duration-500 overflow-hidden" style={{ width: 750, height: 750, backgroundColor: outfillEnabled ? outfillColorHex : '#000000' }}>
            {useSpeedCanvasPreview && !speedPreviewUnavailable && hasLiveSpeedFrames ? (
              <canvas
                ref={canvasRef}
                width={750}
                height={750}
                className="absolute inset-0 w-full h-full pointer-events-none"
                style={previewStyles}
              />
            ) : (
              <img
                src={activeAsset.fileUrl}
                className="absolute inset-0 w-full h-full object-contain pointer-events-none"
                style={previewStyles}
                alt="Preview"
              />
            )}
            {dv3PreviewMode && (
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(circle at center, transparent 30%, #000 70%)' }} />
            )}
            {getEditValue('CIRCLE_MASK', false) && (
              <div className="absolute inset-0 pointer-events-none shadow-[0_0_0_9999px_rgba(0,0,0,1)] rounded-full" />
            )}
            {getEditValue('VIGNETTE', false) && (
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(circle, transparent 50%, rgba(0,0,0,0.8) 100%)' }} />
            )}
            {!getEditValue('CIRCLE_MASK', false) && <div className="absolute inset-0 border-2 border-[#00d2ff]/45 rounded-full pointer-events-none shadow-[0_0_18px_rgba(0,210,255,0.2)]" />}

            <div className="absolute bottom-3 right-3 text-[10px] uppercase tracking-widest bg-black/70 border border-white/10 px-2 py-1 rounded text-[#00d2ff] font-display">
              Canvas 750x750
            </div>

            {useSpeedCanvasPreview && speedPreviewUnavailable && (
              <div className="absolute bottom-3 left-3 text-[10px] uppercase tracking-wide bg-black/70 border border-white/10 px-2 py-1 rounded text-[#f97316]">
                Live Speed Preview Unsupported In This Browser
              </div>
            )}
          </div>
        )}
      </div>

      <div className="w-80 bg-black border-l border-white/10 flex flex-col overflow-y-auto z-10 custom-scrollbar">
        <section className="border-b border-white/10 bg-black">
          <p className="text-[10px] text-white/40 leading-relaxed px-5 py-3 border-b border-white/10">
            Edits are non-destructive. Tag and Save from the panel on the right to bake edits and add to your library.
          </p>
          <div className="px-5 py-3 border-b border-white/10">
            <button
              onClick={handleResetEdits}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded border border-white/10 bg-black text-white/80 hover:text-white hover:bg-white/10 transition-colors text-xs uppercase tracking-wide"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset All Adjustments
            </button>
          </div>
          <button onClick={() => toggleSection('layout')} className="w-full p-4 flex items-center justify-between text-left hover:bg-white/10 transition-colors">
            <h3 className="text-xs font-display text-[#00d2ff] uppercase tracking-wider flex items-center gap-2"><Maximize className="w-3 h-3"/> Layout & Transform</h3>
            {openSections.layout ? <ChevronDown className="w-4 h-4 text-white/70" /> : <ChevronRight className="w-4 h-4 text-white/70" />}
          </button>
          {openSections.layout && <div className="px-5 pb-5"> 
          <div className="grid grid-cols-2 gap-2 mb-5">
            <button onClick={() => onApplyEdit('FLIP_H', !(getEditValue('FLIP_H', false) as boolean))} className={`py-2 rounded flex justify-center items-center gap-2 text-xs font-medium border transition-colors ${getEditValue('FLIP_H', false) ? 'bg-white/10 border-white/10 text-[#f97316]' : 'bg-black border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>
              <FlipHorizontal className="w-3.5 h-3.5" /> Flip H
            </button>
            <button onClick={() => onApplyEdit('FLIP_V', !(getEditValue('FLIP_V', false) as boolean))} className={`py-2 rounded flex justify-center items-center gap-2 text-xs font-medium border transition-colors ${getEditValue('FLIP_V', false) ? 'bg-white/10 border-white/10 text-[#f97316]' : 'bg-black border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>
              <FlipVertical className="w-3.5 h-3.5" /> Flip V
            </button>
          </div>

          <div className="mb-5">
            <div className="flex justify-between text-[11px] uppercase tracking-wide text-white/60 mb-2">
              <span>Size / Zoom (px)</span>
              <div className="flex items-center gap-2">
                <span className="text-[#f97316] font-mono">{zoomOffset > 0 ? `+${zoomOffset}` : zoomOffset}</span>
                <input
                  type="number"
                  min={-300}
                  max={300}
                  step={1}
                  value={zoomOffset}
                  onChange={(e) => applyNumericEdit('PADDING', e.target.value, -300, 300)}
                  className="w-16 bg-black border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white font-mono text-right focus:border-[#f97316] outline-none"
                />
              </div>
            </div>
            <p className="text-[10px] text-white/50 mb-2">Canvas: 750x750. Left = zoom out, right = zoom in.</p>
            <input
              type="range" min="-300" max="300" step="5"
              value={zoomOffset}
              onChange={(e) => onApplyEdit('PADDING', Number(e.target.value))}
              className="w-full wb-slider"
            />
          </div>

          {[
            { label: 'Position X', type: 'POSITION_X' as const, min: -375, max: 375, default: 0, unit: 'px', hint: 'Shift left/right within canvas.' },
            { label: 'Position Y', type: 'POSITION_Y' as const, min: -375, max: 375, default: 0, unit: 'px', hint: 'Shift up/down within canvas.' },
          ].map(ctrl => {
            const val = getEditValue(ctrl.type, ctrl.default) as number;
            return (
              <div key={ctrl.type} className="mb-5">
                <div className="flex justify-between text-[11px] uppercase tracking-wide text-white/60 mb-2">
                  <span>{ctrl.label}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[#f97316] font-mono">{val > 0 ? `+${val}` : val}{ctrl.unit}</span>
                    <input
                      type="number" min={ctrl.min} max={ctrl.max} step={1} value={val}
                      onChange={(e) => applyNumericEdit(ctrl.type, e.target.value, ctrl.min, ctrl.max)}
                      className="w-16 bg-black border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white font-mono text-right focus:border-[#f97316] outline-none"
                    />
                  </div>
                </div>
                <p className="text-[10px] text-white/50 mb-2">{ctrl.hint}</p>
                <input
                  type="range" min={ctrl.min} max={ctrl.max} step={1} value={val}
                  onChange={(e) => onApplyEdit(ctrl.type, Number(e.target.value))}
                  className="w-full wb-slider"
                />
              </div>
            );
          })}

          <div className="mb-5 pt-4 border-t border-white/10">
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors mb-3">
              <input type="checkbox" checked={outfillEnabled} onChange={(e) => onApplyEdit('OUTFILL_ENABLED', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Outfill Background
            </label>
            {outfillEnabled && (
              <div className="ml-7 flex items-center gap-3 border-l border-white/10 pl-3">
                <label className="text-[11px] uppercase tracking-wide text-white/60">Fill Color</label>
                <input
                  type="color"
                  value={outfillColorHex}
                  onChange={(e) => onApplyEdit('OUTFILL_COLOR', parseInt(e.target.value.slice(1), 16))}
                  className="w-8 h-8 border border-white/10 rounded bg-transparent p-0 cursor-pointer"
                />
                <span className="text-[11px] text-[#00d2ff] font-mono">{outfillColorHex.toUpperCase()}</span>
              </div>
            )}
          </div>

          <div className="space-y-3 pt-4 border-t border-white/10">
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input type="checkbox" checked={getEditValue('SQUARE_CROP', false) as boolean} onChange={(e) => onApplyEdit('SQUARE_CROP', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Crop to Square 1:1
            </label>
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input type="checkbox" checked={getEditValue('CIRCLE_MASK', false) as boolean} onChange={(e) => onApplyEdit('CIRCLE_MASK', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Apply Baked Black Mask
            </label>
          </div>
          </div>}
        </section>

        <section className="border-b border-white/10 bg-black">
          <button onClick={() => toggleSection('tone')} className="w-full p-4 flex items-center justify-between text-left hover:bg-white/10 transition-colors">
            <h3 className="text-xs font-display text-[#00d2ff] uppercase tracking-wider flex items-center gap-2"><Sliders className="w-3 h-3"/> Tone & Filters</h3>
            {openSections.tone ? <ChevronDown className="w-4 h-4 text-white/70" /> : <ChevronRight className="w-4 h-4 text-white/70" />}
          </button>
          {openSections.tone && <div className="px-5 pb-5 space-y-5"> 

          {[
            { label: 'Brightness', type: 'BRIGHTNESS', min: 0, max: 300, default: 100, step: 1 },
            { label: 'Contrast', type: 'CONTRAST', min: 0, max: 500, default: 100, step: 1 },
            { label: 'Hue', type: 'HUE', min: -180, max: 180, default: 0, step: 1 },
            { label: 'Saturation', type: 'SATURATION', min: 0, max: 200, default: 100, step: 1 },
          ].map(control => (
            <div key={control.type}>
              <div className="flex justify-between text-[11px] uppercase tracking-wide text-white/60 mb-2">
                <span>{control.label}</span>
                <div className="flex items-center gap-2">
                  <span className="text-[#f97316] font-mono">{getEditValue(control.type as ActionType, control.default) as number}</span>
                  <input
                    type="number"
                    min={control.min}
                    max={control.max}
                    step={control.step}
                    value={getEditValue(control.type as ActionType, control.default) as number}
                    onChange={(e) => applyNumericEdit(control.type as ActionType, e.target.value, control.min, control.max)}
                    className="w-16 bg-black border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white font-mono text-right focus:border-[#f97316] outline-none"
                  />
                </div>
              </div>
              <input
                type="range"
                min={control.min} max={control.max}
                step={control.step}
                value={getEditValue(control.type as ActionType, control.default) as number}
                onChange={(e) => onApplyEdit(control.type as ActionType, Number(e.target.value))}
                className="w-full wb-slider"
              />
            </div>
          ))}

          <div className="pt-4 border-t border-white/10 flex flex-col gap-3">
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input type="checkbox" checked={getEditValue('GRAYSCALE', false) as boolean} onChange={(e) => onApplyEdit('GRAYSCALE', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Grayscale
            </label>
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input type="checkbox" checked={getEditValue('INVERT', false) as boolean} onChange={(e) => onApplyEdit('INVERT', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Invert Colors
            </label>
            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input type="checkbox" checked={getEditValue('VIGNETTE', false) as boolean} onChange={(e) => onApplyEdit('VIGNETTE', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
              Apply Baked Vignette
            </label>

            <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
              <input
                type="checkbox"
                checked={bgSwapEnabled}
                onChange={(e) => onApplyEdit('BG_SWAP', e.target.checked)}
                className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]"
              />
              Replace Near-Black Background (Beta)
            </label>

            {bgSwapEnabled && (
              <div className="ml-7 space-y-3 border-l border-white/10 pl-3">
                <div>
                  <div className="flex justify-between text-[11px] uppercase tracking-wide text-white/60 mb-2">
                    <span>Detection Threshold</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[#f97316] font-mono">{bgThreshold}</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={bgThreshold}
                        onChange={(e) => applyNumericEdit('BG_THRESHOLD', e.target.value, 0, 100)}
                        className="w-16 bg-black border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white font-mono text-right focus:border-[#f97316] outline-none"
                      />
                    </div>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={bgThreshold}
                    onChange={(e) => onApplyEdit('BG_THRESHOLD', Number(e.target.value))}
                    className="w-full wb-slider"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-[11px] uppercase tracking-wide text-white/60">Target Color</label>
                  <input
                    type="color"
                    value={bgColorHex}
                    onChange={(e) => onApplyEdit('BG_COLOR', parseInt(e.target.value.slice(1), 16))}
                    className="w-8 h-8 border border-white/10 rounded bg-transparent p-0 cursor-pointer"
                  />
                  <span className="text-[11px] text-[#00d2ff] font-mono">{bgColorHex.toUpperCase()}</span>
                </div>

                <p className="text-[10px] text-white/45 uppercase tracking-wide">
                  Save-time approximation for dark backgrounds. Best on high-contrast assets.
                </p>
              </div>
            )}
          </div>
          </div>}
        </section>

        <section className="bg-black mb-10">
          <button onClick={() => toggleSection('temporal')} className="w-full p-4 flex items-center justify-between text-left hover:bg-white/10 transition-colors border-b border-white/10">
            <h3 className="text-xs font-display text-[#00d2ff] uppercase tracking-wider flex items-center gap-2"><FastForward className="w-3 h-3"/> Temporal Output</h3>
            {openSections.temporal ? <ChevronDown className="w-4 h-4 text-white/70" /> : <ChevronRight className="w-4 h-4 text-white/70" />}
          </button>
          {openSections.temporal && <div className="px-5 py-4"> 
          <div className="text-[10px] uppercase tracking-wide text-[#00d2ff] mb-3">
            {isAnimatedAsset
              ? (isExporting
                ? 'Live speed preview paused during save.'
                : (speed === 1 && !reverse
                  ? 'Set speed/reverse to enable live speed preview.'
                  : (isDecodingSpeedPreview
                    ? 'Preparing live speed preview...'
                    : (hasLiveSpeedFrames
                      ? 'Live speed preview active in canvas.'
                      : 'Live speed preview unavailable for this file/browser.'))))
              : 'Live speed preview available for GIF/WebP assets.'}
          </div>
          <div className="mb-4">
            <div className="flex justify-between text-[11px] uppercase tracking-wide text-white/60 mb-2">
              <span>Speed Multiplier</span>
              <div className="flex items-center gap-2">
                <span className="text-[#f97316] font-mono">{getEditValue('SPEED', 1) as number}x</span>
                <input
                  type="number"
                  min={0.1}
                  max={4}
                  step={0.05}
                  value={getEditValue('SPEED', 1) as number}
                  onChange={(e) => applyNumericEdit('SPEED', e.target.value, 0.1, 4)}
                  className="w-16 bg-black border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-white font-mono text-right focus:border-[#f97316] outline-none"
                />
              </div>
            </div>
            <input
              type="range"
              min="0.1" max="4" step="0.05"
              value={getEditValue('SPEED', 1) as number}
              onChange={(e) => onApplyEdit('SPEED', Number(e.target.value))}
              className="w-full wb-slider"
            />
          </div>
          <label className="flex items-center gap-3 text-sm text-white/80 cursor-pointer hover:text-white transition-colors">
            <input type="checkbox" checked={getEditValue('REVERSE', false) as boolean} onChange={(e) => onApplyEdit('REVERSE', e.target.checked)} className="w-4 h-4 rounded bg-black border-white/10 text-[#f97316] focus:ring-[#f97316]" />
            Reverse Frames on Save
          </label>
          </div>}
        </section>
      </div>
    </div>
  );
};
