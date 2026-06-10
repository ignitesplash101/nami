import { Copy } from "lucide-react";
import { ApiError } from "./api";
import { presentApiError } from "./errorCopy";
import { useToasts } from "./toast";

interface ErrorNoticeProps {
  // string = legacy/local validation messages rendered verbatim.
  error: ApiError | string;
  variant?: "banner" | "inline";
  // CTA handlers — the matching button renders only when the presentation's
  // cta and a handler are both present.
  onRetry?: () => void;
  onUnlock?: () => void;
  onRerun?: () => void;
  // Optional element id so inputs can pair via aria-describedby.
  id?: string;
}

export function ErrorNotice({
  error,
  variant = "banner",
  onRetry,
  onUnlock,
  onRerun,
  id
}: ErrorNoticeProps) {
  const { push } = useToasts();
  const className = variant === "banner" ? "error-banner" : "inline-error";

  if (typeof error === "string") {
    return (
      <div className={className} id={id} role="alert">
        {error}
      </div>
    );
  }

  const apiError = error;
  const presentation = presentApiError(apiError);
  const handler =
    presentation.cta === "retry"
      ? onRetry
      : presentation.cta === "unlock"
        ? onUnlock
        : presentation.cta === "rerun"
          ? onRerun
          : undefined;

  async function copyRequestId() {
    if (!apiError.requestId) return;
    try {
      await navigator.clipboard.writeText(apiError.requestId);
      push({ message: "Request id copied.", variant: "info" });
    } catch {
      // Clipboard unavailable (insecure origin) — no-op.
    }
  }

  return (
    <div className={className} id={id} role="alert">
      <span>{presentation.message}</span>
      {handler && presentation.ctaLabel ? (
        <div className="error-cta-row">
          <button type="button" className="ghost-button" onClick={handler}>
            {presentation.ctaLabel}
          </button>
        </div>
      ) : null}
      {apiError.requestId ? (
        <div>
          <span className="error-ref">
            ref: <code>{apiError.requestId}</code>
            <button type="button" aria-label="Copy request id" onClick={copyRequestId}>
              <Copy size={12} />
            </button>
          </span>
        </div>
      ) : null}
    </div>
  );
}
