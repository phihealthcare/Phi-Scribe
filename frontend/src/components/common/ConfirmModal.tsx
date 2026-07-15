import type { ReactNode } from "react";
import { Button, Modal } from "react-bootstrap";

interface ConfirmModalProps {
  show: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  confirmVariant?: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** Optional middle action (e.g. "Continuar gravando") — most modals only need confirm/cancel. */
  extraLabel?: string;
  extraVariant?: string;
  onExtra?: () => void;
}

export default function ConfirmModal({
  show,
  title,
  body,
  confirmLabel,
  cancelLabel,
  confirmVariant = "danger",
  onConfirm,
  onCancel,
  extraLabel,
  extraVariant = "outline-primary",
  onExtra,
}: ConfirmModalProps) {
  return (
    <Modal show={show} onHide={onCancel} centered>
      <Modal.Header closeButton>
        <Modal.Title>{title}</Modal.Title>
      </Modal.Header>
      <Modal.Body>{body}</Modal.Body>
      <Modal.Footer>
        <Button variant="outline-secondary" onClick={onCancel}>
          {cancelLabel}
        </Button>
        {extraLabel && onExtra && (
          <Button variant={extraVariant} onClick={onExtra}>
            {extraLabel}
          </Button>
        )}
        <Button variant={confirmVariant} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
