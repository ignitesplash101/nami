import { useEffect, useRef } from "react";
import { getAccess } from "./api";
import type { AccessMode, AccessResponse } from "./types";

/** Pure downgrade rule: the session-expired banner shows only when an admin
 * session silently became a visitor one (cookie expiry) — never on a
 * deliberate lock or an initial visitor load. */
export function nextSessionExpired(
  prev: AccessMode | null,
  next: AccessMode,
  intentional: boolean
): boolean {
  return prev === "admin" && next === "visitor" && !intentional;
}

export function useAccessWatch(options: {
  enabled: boolean;
  intervalMs?: number;
  onAccess: (access: AccessResponse) => void;
}): void {
  const { enabled, intervalMs = 5 * 60_000 } = options;
  // Read through a ref so the interval isn't re-armed on every render.
  const onAccessRef = useRef(options.onAccess);
  onAccessRef.current = options.onAccess;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const refetch = () => {
      getAccess()
        .then((access) => {
          if (!cancelled) onAccessRef.current(access);
        })
        .catch(() => {
          // Swallowed deliberately: a network blip must not fabricate a
          // session downgrade.
        });
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") refetch();
    };
    document.addEventListener("visibilitychange", onVisibility);
    const interval = setInterval(() => {
      if (document.visibilityState !== "hidden") refetch();
    }, intervalMs);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      clearInterval(interval);
    };
  }, [enabled, intervalMs]);
}
