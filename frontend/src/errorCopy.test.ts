import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import type { ApiErrorKind } from "./api";
import { presentApiError } from "./errorCopy";
import type { ErrorCta } from "./errorCopy";

function present(kind: ApiErrorKind, detail = "raw server detail") {
  return presentApiError(new ApiError({ status: null, detail, kind }));
}

describe("presentApiError", () => {
  const cases: Array<[ApiErrorKind, RegExp, ErrorCta]> = [
    ["budget_exhausted", /budget is exhausted/i, "wait_tomorrow"],
    ["run_cap", /run cap reached/i, "wait_tomorrow"],
    ["expired", /cache entry has expired/i, "rerun"],
    ["too_large", /too large to save/i, "reduce_size"],
    ["marking_unavailable", /failed closed/i, "retry"],
    ["forbidden", /requires admin mode/i, "unlock"],
    ["network", /network error/i, "retry"],
    ["cancelled", /cancelled/i, null]
  ];

  it.each(cases)("%s renders fixed copy with the %s CTA", (kind, pattern, cta) => {
    const presentation = present(kind);
    expect(presentation.message).toMatch(pattern);
    expect(presentation.cta).toBe(cta);
  });

  it("passes raw detail through for validation/auth/timeout/rate_limited/unknown", () => {
    expect(present("validation", "Weights must sum to ~1.0.").message).toBe(
      "Weights must sum to ~1.0."
    );
    expect(present("auth", "Incorrect passcode.").message).toBe("Incorrect passcode.");
    expect(present("timeout", "Stream timed out — no progress for 60s.").message).toMatch(
      /timed out/
    );
    // Server copy differs between the per-IP limiter and the unlock lockout —
    // both pass through verbatim with a retry CTA.
    expect(present("rate_limited", "Too many unlock attempts; try again later.").message).toBe(
      "Too many unlock attempts; try again later."
    );
    expect(present("rate_limited").cta).toBe("retry");
    expect(present("unknown", "boom").message).toBe("boom");
  });

  it("appends the re-run explanation to rerun_required LLM details", () => {
    const presentation = present("rerun_required", "That asks for a new mechanism.");
    expect(presentation.message).toBe(
      "That asks for a new mechanism. — this edit changes the scenario itself, so it needs a full re-run."
    );
    expect(presentation.cta).toBe("rerun");
    expect(presentation.ctaLabel).toBe("Pre-fill re-run");
  });

  it("only fixed-copy kinds expose a CTA label", () => {
    expect(present("budget_exhausted").ctaLabel).toBeNull();
    expect(present("expired").ctaLabel).toBe("Re-run scenario");
    expect(present("forbidden").ctaLabel).toBe("Unlock");
  });

  it("network passes the mid-stream drop copy through, generic on raw transport detail", () => {
    const dropped = present(
      "network",
      "Connection dropped mid-run — the server may still finish and warm the cache, so retrying can be instant."
    );
    expect(dropped.message).toMatch(/^Connection dropped mid-run/);
    expect(dropped.cta).toBe("retry");

    const raw = present("network", "Failed to fetch");
    expect(raw.message).toMatch(/network error — check your connection/i);
  });

  it("uses recovery-aware copy for a startup connection interruption", () => {
    const boot = present(
      "network",
      "Connection was interrupted while loading nami. The app retries automatically when you reconnect or return to this tab."
    );
    expect(boot.message).toMatch(/interrupted while loading/i);
    expect(boot.message).toMatch(/retries automatically/i);
    expect(boot.cta).toBe("retry");
    expect(boot.ctaLabel).toBe("Retry");
  });

  it("unavailable passes actionable server detail through, generic on bare status lines", () => {
    const detailed = present(
      "unavailable",
      "Saved-analytics store unavailable: composite index missing — gcloud firestore indexes ..."
    );
    expect(detailed.message).toMatch(/composite index missing/);
    expect(detailed.cta).toBe("retry");

    const bare = present("unavailable", "503 Service Unavailable");
    expect(bare.message).toMatch(/temporarily unavailable/i);
  });
});
