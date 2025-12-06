import React from 'react';

type CardProps = React.HTMLAttributes<HTMLDivElement>;

export const Card = React.forwardRef<HTMLDivElement, CardProps>(function Card(
  { className = '', children, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      className={`ui-card ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
});

type PanelProps = React.HTMLAttributes<HTMLDivElement>;

export const Panel = React.forwardRef<HTMLDivElement, PanelProps>(function Panel(
  { className = '', children, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      className={`ui-panel ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
});
