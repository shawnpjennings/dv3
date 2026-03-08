import type * as React from 'react';
import type { EditAction } from '../types';

export function computeThumbStyles(editStack: EditAction[], historyIndex: number): React.CSSProperties {
  const activeStack = editStack.slice(0, historyIndex + 1);

  let brightness = 1, contrast = 1, hue = 0, saturate = 1;
  let flipH = false, flipV = false;
  let invert = false, grayscale = false;

  for (const action of activeStack) {
    switch (action.type) {
      case 'BRIGHTNESS': brightness = (action.value as number) / 100; break;
      case 'CONTRAST': contrast = (action.value as number) / 100; break;
      case 'HUE': hue = action.value as number; break;
      case 'SATURATION': saturate = (action.value as number) / 100; break;
      case 'FLIP_H': flipH = !flipH; break;
      case 'FLIP_V': flipV = !flipV; break;
      case 'INVERT': invert = action.value as boolean; break;
      case 'GRAYSCALE': grayscale = action.value as boolean; break;
    }
  }

  const filters = [
    `brightness(${brightness})`,
    `contrast(${contrast})`,
    `hue-rotate(${hue}deg)`,
    `saturate(${saturate})`,
    invert ? 'invert(1)' : '',
    grayscale ? 'grayscale(1)' : '',
  ].filter(Boolean).join(' ');

  const transforms: string[] = [];
  if (flipH) transforms.push('scaleX(-1)');
  if (flipV) transforms.push('scaleY(-1)');

  return {
    filter: filters || undefined,
    transform: transforms.length ? transforms.join(' ') : undefined,
  };
}
