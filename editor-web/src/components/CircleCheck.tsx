import * as React from 'react';

interface CircleCheckProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: React.ReactNode;
  className?: string;
}

/**
 * Orange circle toggle — replaces square checkboxes throughout the editor.
 * Matches the visual style of the Theme radio buttons.
 */
export function CircleCheck({ checked, onChange, label, className = '' }: CircleCheckProps) {
  return (
    <label className={`flex items-center gap-2.5 cursor-pointer group ${className}`}>
      <button
        role="checkbox"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-all ${
          checked
            ? 'border-[#f97316] bg-[#f97316]'
            : 'border-white/30 bg-transparent group-hover:border-white/50'
        }`}
      >
        {checked && <div className="w-1.5 h-1.5 rounded-full bg-black" />}
      </button>
      <span className="text-sm text-white/80 group-hover:text-white transition-colors select-none">
        {label}
      </span>
    </label>
  );
}
