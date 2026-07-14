import { ApiError } from "./api";

/** Short enough to smooth a cellular handoff without turning startup into an
 * unbounded wait: initial request + 400ms retry + 800ms retry. */
export const BOOT_RETRY_DELAYS_MS = [400, 800] as const;

/** Retry one idempotent bootstrap GET only when the API transport classified
 * the failure as a network interruption. HTTP/coded failures pass through on
 * the first attempt. */
export async function retryBootGet<T>(operation: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await operation();
    } catch (exc) {
      const delayMs = BOOT_RETRY_DELAYS_MS[attempt];
      if (!(exc instanceof ApiError) || exc.kind !== "network" || delayMs === undefined) {
        throw exc;
      }
      await new Promise<void>((resolve) => {
        setTimeout(resolve, delayMs);
      });
    }
  }
}

/** Settle async work owned by a bootstrap effect without letting an abandoned
 * StrictMode/stale effect write either its value or its error into the app. */
export async function settleActiveBootEffect<T>(
  operation: Promise<T>,
  isActive: () => boolean,
  onSuccess: (value: T) => void,
  onFailure: (error: unknown) => void
): Promise<void> {
  try {
    const value = await operation;
    if (!isActive()) return;
    onSuccess(value);
  } catch (error) {
    if (!isActive()) return;
    onFailure(error);
  }
}
