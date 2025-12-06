import React from 'react';

type Variant = 'solid' | 'outline' | 'ghost' | 'icon';
type Tone = 'primary' | 'secondary' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const sizeMap: Record<Size, string> = {
  sm: 'ui-btn-sm',
  md: 'ui-btn-md',
  lg: 'ui-btn-lg',
};

const toneClass: Record<Tone, string> = {
  primary: 'ui-btn-primary',
  secondary: 'ui-btn-secondary',
  danger: 'ui-btn-danger',
};

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  tone?: Tone;
  size?: Size;
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className = '', variant = 'solid', tone = 'primary', size = 'md', children, ...rest },
  ref
) {
  const isIcon = variant === 'icon';
  return (
    <button
      ref={ref}
      className={`ui-btn ${toneClass[tone]} ${sizeMap[size]} ${variant === 'outline' ? 'ui-btn-outline' : ''} ${variant === 'ghost' ? 'ui-btn-ghost' : ''} ${isIcon ? 'ui-btn-icon' : ''} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
});
