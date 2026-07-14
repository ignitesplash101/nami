import { useEffect, useRef } from "react";

/** Re-arm a failed bootstrap when connectivity returns or a parked mobile tab
 * becomes visible. One listener lifetime emits at most one recovery; App
 * disables the hook while that recovery is in flight and re-enables it only if
 * startup fails again. */
export function useBootRecovery(options: {
  enabled: boolean;
  onRecover: () => void;
}): void {
  const onRecoverRef = useRef(options.onRecover);
  onRecoverRef.current = options.onRecover;

  useEffect(() => {
    if (!options.enabled) return;
    let recoveryStarted = false;

    const recover = () => {
      if (recoveryStarted) return;
      recoveryStarted = true;
      onRecoverRef.current();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") recover();
    };

    window.addEventListener("online", recover);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("online", recover);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [options.enabled]);
}
