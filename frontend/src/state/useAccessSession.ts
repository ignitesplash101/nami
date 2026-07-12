import { useRef, useState } from "react";
import { getAccess } from "../api";
import { nextSessionExpired, useAccessWatch } from "../useAccessWatch";
import type { AccessResponse } from "../types";

/** Access mode + the silent-downgrade watcher. Every access update routes
 * through applyAccess so an un-intentional admin→visitor transition (cookie
 * expiry) raises the session banner exactly once; deliberate lock/unlock
 * passes intentional=true and stays quiet. */
export function useAccessSession() {
  const [access, setAccess] = useState<AccessResponse | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const accessModeRef = useRef<AccessResponse["access_mode"] | null>(null);

  function applyAccess(next: AccessResponse, opts?: { intentional?: boolean }) {
    const prev = accessModeRef.current;
    accessModeRef.current = next.access_mode;
    if (next.access_mode === "admin") {
      setSessionExpired(false);
    } else if (nextSessionExpired(prev, next.access_mode, Boolean(opts?.intentional))) {
      setSessionExpired(true);
    }
    setAccess(next);
  }

  async function refreshAccess() {
    applyAccess(await getAccess());
  }

  useAccessWatch({ enabled: access != null, onAccess: applyAccess });

  const isAdmin = access?.access_mode === "admin";
  return { access, isAdmin, sessionExpired, applyAccess, refreshAccess };
}
