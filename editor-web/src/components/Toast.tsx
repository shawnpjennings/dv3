import * as React from 'react';
import { useEffect } from 'react';
import { X, AlertCircle, CheckCircle2 } from 'lucide-react';

export interface ToastData {
  id: string;
  message: string;
  type: 'error' | 'success' | 'info';
  /** Auto-dismiss after this many ms (0 = manual dismiss only) */
  duration?: number;
}

interface ToastProps {
  toasts: ToastData[];
  onDismiss: (id: string) => void;
}

const ToastItem: React.FC<{ toast: ToastData; onDismiss: () => void }> = ({ toast, onDismiss }) => {
  useEffect(() => {
    const dur = toast.duration ?? 5000;
    if (dur <= 0) return;
    const timer = setTimeout(onDismiss, dur);
    return () => clearTimeout(timer);
  }, [toast.duration, onDismiss]);

  const borderColor =
    toast.type === 'error'
      ? 'border-red-600'
      : toast.type === 'success'
      ? 'border-green-600'
      : 'border-[#f97316]';

  const iconColor =
    toast.type === 'error'
      ? 'text-red-400'
      : toast.type === 'success'
      ? 'text-green-400'
      : 'text-[#f97316]';

  return (
    <div
      className={`flex items-start gap-3 bg-[#111] border ${borderColor} rounded-lg shadow-2xl px-4 py-3 min-w-[300px] max-w-[450px] animate-slide-in`}
    >
      <div className={`mt-0.5 shrink-0 ${iconColor}`}>
        {toast.type === 'error' ? (
          <AlertCircle className="w-4 h-4" />
        ) : (
          <CheckCircle2 className="w-4 h-4" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-bold tracking-[0.15em] text-[#f97316] uppercase mb-1">
          DV3 EDITOR
        </p>
        <p className="text-xs text-white/80 leading-relaxed break-words">{toast.message}</p>
      </div>
      <button
        onClick={onDismiss}
        className="shrink-0 text-white/30 hover:text-white/70 transition-colors mt-0.5"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
};

export const ToastContainer: React.FC<ToastProps> = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[400] flex flex-col gap-2">
      {toasts.map(toast => (
        <ToastItem key={toast.id} toast={toast} onDismiss={() => onDismiss(toast.id)} />
      ))}
    </div>
  );
};
