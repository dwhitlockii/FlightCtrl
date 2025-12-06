import React from 'react';
import { createPortal } from 'react-dom';

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  side?: 'left' | 'right';
  title?: string;
  children: React.ReactNode;
};

export function Drawer({ open, onClose, side = 'right', title, children }: DrawerProps) {
  if (!open) return null;
  return createPortal(
    <div className="ui-drawer-backdrop" onClick={onClose}>
      <div
        className={`ui-drawer ui-drawer-${side}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ui-drawer-header">
          <div className="ui-drawer-title">{title}</div>
          <button className="ui-btn ui-btn-icon ui-btn-ghost" onClick={onClose} aria-label="Close drawer">
            ×
          </button>
        </div>
        <div className="ui-drawer-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}
