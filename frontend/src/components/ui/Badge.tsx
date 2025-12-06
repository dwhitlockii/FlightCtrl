import React from 'react';

type Variant = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const variantClasses: Record<Variant, string> = {
  neutral: 'ui-badge-neutral',
  info: 'ui-badge-info',
  success: 'ui-badge-success',
  warning: 'ui-badge-warning',
  danger: 'ui-badge-danger',
};

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: Variant;
};

export function Badge({ variant = 'neutral', className = '', children, ...rest }: BadgeProps) {
  return (
    <span className={`ui-badge ${variantClasses[variant]} ${className}`} {...rest}>
      {children}
    </span>
  );
}
