import type { ApiError, ApiErrorKind } from "./api";

// Presentation layer for ApiError: maps each error kind to user-facing copy and
// an optional call-to-action. Kept separate from the transport layer so it is
// unit-testable and importable by any component.

export type ErrorCta = "retry" | "unlock" | "rerun" | "reduce_size" | "wait_tomorrow" | null;

export interface ErrorPresentation {
  message: string;
  cta: ErrorCta;
  ctaLabel: string | null;
}

const PRESENTATIONS: Record<ApiErrorKind, (detail: string) => ErrorPresentation> = {
  // Raw detail passthrough: the server distinguishes "slow down and retry
  // shortly" (per-IP limiter) from "try again later" (unlock lockout) — both
  // are already good copy, so don't flatten them into one message.
  rate_limited: (detail) => ({ message: detail, cta: "retry", ctaLabel: "Retry" }),
  budget_exhausted: () => ({
    message: "Daily LLM budget is exhausted. Runs resume tomorrow (00:00 UTC).",
    cta: "wait_tomorrow",
    ctaLabel: null
  }),
  run_cap: () => ({
    message: "Daily scenario run cap reached. Runs resume tomorrow (00:00 UTC).",
    cta: "wait_tomorrow",
    ctaLabel: null
  }),
  expired: () => ({
    message:
      "This scenario's server-side cache entry has expired. Re-run the scenario, then adjust again.",
    cta: "rerun",
    ctaLabel: "Re-run scenario"
  }),
  too_large: () => ({
    message:
      "This scenario is too large to save. Trim notes/tags, or save before running theme sensitivity.",
    cta: "reduce_size",
    ctaLabel: null
  }),
  validation: (detail) => ({ message: detail, cta: null, ctaLabel: null }),
  rerun_required: (detail) => ({
    message: `${detail} — this edit changes the scenario itself, so it needs a full re-run.`,
    cta: "rerun",
    ctaLabel: "Pre-fill re-run"
  }),
  marking_unavailable: () => ({
    message:
      "Live price/FX marks are unavailable, so the run failed closed rather than show " +
      "partial dollars. Retry shortly or switch the book to Weights.",
    cta: "retry",
    ctaLabel: "Retry"
  }),
  auth: (detail) => ({ message: detail, cta: null, ctaLabel: null }),
  forbidden: () => ({
    message: "This action requires admin mode — your session may have expired.",
    cta: "unlock",
    ctaLabel: "Unlock"
  }),
  // Mid-stream and bootstrap drops carry purpose-written detail; raw transport
  // messages ("Failed to fetch") fall back to the generic line.
  network: (detail) => ({
    message:
      detail.startsWith("Connection dropped") ||
      detail.startsWith("Connection was interrupted while loading")
      ? detail
      : "Network error — check your connection and retry.",
    cta: "retry",
    ctaLabel: "Retry"
  }),
  timeout: (detail) => ({ message: detail, cta: "retry", ctaLabel: "Retry" }),
  cancelled: () => ({ message: "Run cancelled.", cta: null, ctaLabel: null }),
  // Un-coded 503s carry actionable server detail (e.g. the Firestore
  // missing-index instructions or "yfinance returned no data for ...") — pass
  // it through; only a bare status line falls back to generic copy.
  unavailable: (detail) => ({
    message: /^\d{3}\s/.test(detail)
      ? "Service temporarily unavailable — retry shortly."
      : detail,
    cta: "retry",
    ctaLabel: "Retry"
  }),
  unknown: (detail) => ({ message: detail, cta: "retry", ctaLabel: "Retry" })
};

export function presentApiError(error: ApiError): ErrorPresentation {
  return PRESENTATIONS[error.kind](error.detail);
}
