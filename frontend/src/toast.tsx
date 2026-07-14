import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

export type ToastVariant = "success" | "info" | "error";

export interface ToastInput {
  message: string;
  variant?: ToastVariant;
  durationMs?: number;
  /** Optional action button rendered between the message and the dismiss
   * control; clicking runs onAction() then dismisses the toast. */
  actionLabel?: string;
  onAction?: () => void;
  /** Visual-only: render OUTSIDE the toast stack's polite live region so it is
   * not announced. The app has exactly ONE polite region for run lifecycle (in
   * the App shell); completion toasts are silent to avoid double-announcing. */
  silent?: boolean;
}

interface ToastRecord {
  id: number;
  message: string;
  variant: ToastVariant;
  actionLabel?: string;
  onAction?: () => void;
  silent: boolean;
}

interface ToastContextValue {
  push: (toast: ToastInput) => void;
}

interface ToastTimer {
  handle: ReturnType<typeof setTimeout>;
  expiresAt: number;
  remainingMs: number;
  // Hover and keyboard focus are tracked independently: the countdown pauses
  // while EITHER holds and resumes only when BOTH release.
  hovered: boolean;
  focused: boolean;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION_MS = 4500;
const MIN_RESUME_MS = 600;

// Outside a provider (isolated component tests) push is a silent no-op — the
// provider is mounted once at the root in production.
const NOOP_CONTEXT: ToastContextValue = { push: () => {} };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ToastTimer>());

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer.handle);
    timers.current.delete(id);
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: ToastInput) => {
      const id = nextId.current++;
      const durationMs = toast.durationMs ?? DEFAULT_DURATION_MS;
      setToasts((prev) => [
        ...prev,
        {
          id,
          message: toast.message,
          variant: toast.variant ?? "info",
          actionLabel: toast.actionLabel,
          onAction: toast.onAction,
          silent: toast.silent ?? false
        }
      ]);
      timers.current.set(id, {
        handle: setTimeout(() => dismiss(id), durationMs),
        expiresAt: Date.now() + durationMs,
        remainingMs: durationMs,
        hovered: false,
        focused: false
      });
    },
    [dismiss]
  );

  // Countdown pauses while hovered OR focused and resumes only when both are
  // released — a keyboard user reaching the action button must never have it
  // expire mid-interaction. Only the paused<->running transitions touch the
  // timer, so intra-toast focus moves (action -> dismiss) don't reset it.
  const setInteraction = useCallback(
    (id: number, patch: Partial<Pick<ToastTimer, "hovered" | "focused">>) => {
      const timer = timers.current.get(id);
      if (!timer) return;
      const wasActive = timer.hovered || timer.focused;
      Object.assign(timer, patch);
      const isActive = timer.hovered || timer.focused;
      if (isActive === wasActive) return;
      clearTimeout(timer.handle);
      if (isActive) {
        timer.remainingMs = Math.max(0, timer.expiresAt - Date.now());
      } else {
        const delay = Math.max(timer.remainingMs, MIN_RESUME_MS);
        timer.handle = setTimeout(() => dismiss(id), delay);
        timer.expiresAt = Date.now() + delay;
      }
    },
    [dismiss]
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const timer of map.values()) clearTimeout(timer.handle);
      map.clear();
    };
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  const renderToast = (toast: ToastRecord) => (
    <div
      key={toast.id}
      className={`toast toast-${toast.variant}`}
      onMouseEnter={() => setInteraction(toast.id, { hovered: true })}
      onMouseLeave={() => setInteraction(toast.id, { hovered: false })}
      onFocus={() => setInteraction(toast.id, { focused: true })}
      onBlur={() => setInteraction(toast.id, { focused: false })}
    >
      <span className="toast-message">{toast.message}</span>
      {toast.actionLabel && toast.onAction ? (
        <button
          type="button"
          className="toast-action"
          onClick={() => {
            toast.onAction?.();
            dismiss(toast.id);
          }}
        >
          {toast.actionLabel}
        </button>
      ) : null}
      <button
        type="button"
        className="toast-dismiss"
        aria-label="Dismiss notification"
        onClick={() => dismiss(toast.id)}
      >
        <X size={14} />
      </button>
    </div>
  );

  const announced = toasts.filter((toast) => !toast.silent);
  const silent = toasts.filter((toast) => toast.silent);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Always mounted (even empty) so the live region is registered before
          the first toast arrives. Two sibling regions share the fixed stack via
          display:contents so all toasts flow into one visual column. */}
      <div className="toast-stack">
        <div className="toast-region" role="status" aria-live="polite">
          {announced.map(renderToast)}
        </div>
        {/* Silent toasts render outside any live region (visual-only) but their
            action button stays keyboard-reachable — never aria-hidden. */}
        <div className="toast-region">{silent.map(renderToast)}</div>
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastContextValue {
  return useContext(ToastContext) ?? NOOP_CONTEXT;
}
