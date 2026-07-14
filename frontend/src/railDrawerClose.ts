import type { AccessResponse } from "./types";

/**
 * Wraps a rail-content callback so it closes the compact rail drawer
 * immediately after firing — but only if the drawer is actually open. On
 * desktop the drawer never opens, so the wrapped callback is an inert no-op
 * beyond calling `fn`.
 */
export function wrapWithDrawerClose<Args extends unknown[]>(
  fn: (...args: Args) => void,
  isOpen: () => boolean,
  close: () => void
): (...args: Args) => void {
  return (...args: Args) => {
    fn(...args);
    if (isOpen()) close();
  };
}

/**
 * True when an access-change call represents a COMPLETED, deliberate
 * transition into admin mode (a successful unlock) — the only access change
 * that should self-close the compact rail drawer. A deliberate lock
 * (`intentional: true`, but `access_mode` goes to "visitor") and a silent
 * access refresh (no `intentional` flag at all, e.g. the 5-minute watcher)
 * must both leave the drawer open — there's no completed pick to celebrate.
 */
export function isCompletedUnlock(
  next: AccessResponse,
  opts?: { intentional?: boolean }
): boolean {
  return Boolean(opts?.intentional) && next.access_mode === "admin";
}
