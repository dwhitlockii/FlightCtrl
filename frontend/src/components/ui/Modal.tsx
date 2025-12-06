import React from 'react';
import { createPortal } from 'react-dom';

type ModalProps = {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
};

export function Modal({ open, onClose, title, children }: ModalProps) {
  if (!open) return null;
  return createPortal(
    <div className="ui-modal-backdrop" onClick={onClose}>
      <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ui-modal-header">
          <div className="ui-modal-title">{title}</div>
          <button className="ui-btn ui-btn-icon ui-btn-ghost" onClick={onClose} aria-label="Close modal">
            ×
          </button>
        </div>
        <div className="ui-modal-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}
