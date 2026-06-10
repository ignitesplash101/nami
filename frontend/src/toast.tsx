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
}

interface ToastRecord {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  push: (toast: ToastInput) => void;
}

interface ToastTimer {
  handle: ReturnType<typeof setTimeout>;
  expiresAt: number;
  remainingMs: number;
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
        { id, message: toast.message, variant: toast.variant ?? "info" }
      ]);
      timers.current.set(id, {
        handle: setTimeout(() => dismiss(id), durationMs),
        expiresAt: Date.now() + durationMs,
        remainingMs: durationMs
      });
    },
    [dismiss]
  );

  // Hover pauses the countdown; leaving resumes with the remaining time.
  const pause = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (!timer) return;
    clearTimeout(timer.handle);
    timer.remainingMs = Math.max(0, timer.expiresAt - Date.now());
  }, []);

  const resume = useCallback(
    (id: number) => {
      const timer = timers.current.get(id);
      if (!timer) return;
      clearTimeout(timer.handle);
      const delay = Math.max(timer.remainingMs, MIN_RESUME_MS);
      timer.handle = setTimeout(() => dismiss(id), delay);
      timer.expiresAt = Date.now() + delay;
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

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Always mounted (even empty) so the live region is registered before
          the first toast arrives. */}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast-${toast.variant}`}
            onMouseEnter={() => pause(toast.id)}
            onMouseLeave={() => resume(toast.id)}
          >
            <span className="toast-message">{toast.message}</span>
            <button
              type="button"
              className="toast-dismiss"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastContextValue {
  return useContext(ToastContext) ?? NOOP_CONTEXT;
}
