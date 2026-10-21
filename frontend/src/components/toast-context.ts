import { createContext, useContext } from "react";

export type ToastTone = "success" | "error" | "info";

export interface ToastContextValue {
  notify: (message: string, options?: { detail?: string; tone?: ToastTone }) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
