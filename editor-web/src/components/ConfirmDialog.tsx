import * as React from 'react';
import { useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';

export interface ConfirmDialogProps {
  /** Whether the dialog is visible */
  open: boolean;
  /** Title shown at the top of the dialog */
  title?: string;
  /** Main message / body text */
  message: string;
  /** Label for the confirm button */
  confirmLabel?: string;
  /** Label for the cancel button */
  cancelLabel?: string;
  /** If true, confirm button uses red/destructive styling */
  destructive?: boolean;
  /** Called when the user confirms */
  onConfirm: () => void;
  /** Called when the user cancels (or presses Escape) */
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title = 'DV3 EDITOR',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}) => {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    // Focus the confirm button when dialog opens
    const timer = setTimeout(() => confirmRef.current?.focus(), 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#111] border border-white/10 rounded-lg shadow-2xl w-[380px] overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-2 px-5 pt-5 pb-2">
          <AlertTriangle className={`w-5 h-5 ${destructive ? 'text-red-400' : 'text-[#f97316]'}`} />
          <span className="text-xs font-bold tracking-[0.2em] text-[#f97316] uppercase">
            {title}
          </span>
        </div>

        {/* Body */}
        <div className="px-5 py-3">
          <p className="text-sm text-white/80 leading-relaxed">{message}</p>
        </div>

        {/* Actions */}
        <div className="flex gap-2 px-5 pb-5 pt-2">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 bg-white/8 hover:bg-white/15 text-white/70 hover:text-white rounded text-xs font-medium transition-colors border border-white/10"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`flex-1 py-2.5 rounded text-xs font-bold transition-colors ${
              destructive
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-[#f97316] hover:bg-[#ea6c0a] text-black'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
