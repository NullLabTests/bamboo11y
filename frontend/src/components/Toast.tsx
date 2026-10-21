import { useCallback, useMemo, useState, type ReactNode } from "react";

import { ToastContext, type ToastContextValue, type ToastTone } from "./toast-context";

interface Toast {
  id: number;
  message: string;
  detail?: string;
  tone: ToastTone;
}

let nextToastId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback<ToastContextValue["notify"]>(
    (message, options = {}) => {
      const toast: Toast = {
        id: nextToastId++,
        message,
        detail: options.detail,
        tone: options.tone ?? "info",
      };
      setToasts((current) => [...current, toast]);
      window.setTimeout(() => dismiss(toast.id), 6000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-viewport" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div className={`toast toast--${toast.tone}`} key={toast.id} role="status">
            <div>
              <p className="toast__message">{toast.message}</p>
              {toast.detail ? <p className="toast__detail">{toast.detail}</p> : null}
            </div>
            <button
              type="button"
              className="toast__close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
