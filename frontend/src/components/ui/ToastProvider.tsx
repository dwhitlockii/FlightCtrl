import React, { createContext, useContext, useMemo, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';

type Toast = {
  id: string;
  title?: string;
  message: string;
  variant?: 'neutral' | 'info' | 'success' | 'warning' | 'danger';
};

type ToastContextType = {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
};

const ToastContext = createContext<ToastContextType | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((prev) => [...prev, { id, ...toast }]);
    setTimeout(() => removeToast(id), 4000);
  }, [removeToast]);

  const value = useMemo(() => ({ toasts, addToast, removeToast }), [toasts, addToast, removeToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="ui-toast-portal">
          {toasts.map((toast) => (
            <div key={toast.id} className={`ui-toast ui-toast-${toast.variant || 'neutral'}`}>
              {toast.title && <div className="ui-toast-title">{toast.title}</div>}
              <div className="ui-toast-message">{toast.message}</div>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
