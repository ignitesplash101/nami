import { useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { OverlayShell } from "./OverlayShell";

interface ConfirmDialogProps {
  isOpen: boolean;
  // Parent owns useOverlay() (scroll lock + Esc); the shell owns trap/focus.
  // NEVER render this while another useOverlay overlay is open — both Esc
  // listeners sit on window and would close together.
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  // Destructive confirms: the confirm button takes the loss-red treatment.
  danger?: boolean;
  // Exact-match gate (e.g. "DELETE") — confirm stays disabled until typed.
  typeToConfirm?: string;
  busy?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  body,
  confirmLabel = "Confirm",
  danger = false,
  typeToConfirm,
  busy = false
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) setTyped("");
  }, [isOpen]);

  const confirmDisabled = busy || (typeToConfirm != null && typed !== typeToConfirm);
  const initialFocusRef = (typeToConfirm ? inputRef : cancelRef) as RefObject<HTMLElement>;

  return (
    <OverlayShell
      isOpen={isOpen}
      onClose={onClose}
      className="confirm-dialog"
      backdropClassName="drawer-backdrop confirm-backdrop"
      ariaLabel={title}
      title={title}
      panelElement="section"
      initialFocusRef={initialFocusRef}
    >
      <div className="confirm-body">
        <div className="confirm-text">{body}</div>
        {typeToConfirm ? (
          <label>
            Confirmation
            <input
              ref={inputRef}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              aria-describedby="confirm-type-hint"
              disabled={busy}
              autoComplete="off"
            />
            <span id="confirm-type-hint" className="muted confirm-hint">
              Type {typeToConfirm} to enable the button.
            </span>
          </label>
        ) : null}
        <div className="confirm-actions">
          <button
            type="button"
            ref={cancelRef}
            className="ghost-button"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`primary-button${danger ? " danger" : ""}`}
            onClick={() => void onConfirm()}
            disabled={confirmDisabled}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </OverlayShell>
  );
}
