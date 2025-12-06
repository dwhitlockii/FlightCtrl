import React from 'react';

type Variant = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

const variantClass: Record<Variant, string> = {
  neutral: 'bg-slate-800 text-slate-100 border-slate-700',
  success: 'bg-emerald-900/60 text-emerald-100 border-emerald-700',
  warning: 'bg-amber-900/60 text-amber-100 border-amber-700',
  danger: 'bg-red-900/60 text-red-100 border-red-700',
  info: 'bg-cyan-900/60 text-cyan-100 border-cyan-700',
};

type Props = {
  title?: string;
  description?: string;
  variant?: Variant;
  children?: React.ReactNode;
  className?: string;
};

export function Alert({ title, description, variant = 'neutral', children, className = '' }: Props) {
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${variantClass[variant]} ${className}`}>
      {title && <div className="font-semibold mb-1">{title}</div>}
      {description && <div className="text-sm opacity-90">{description}</div>}
      {children}
    </div>
  );
}
