import { useEffect, useRef } from "react";

/** A compact drawer must not survive the 1079.98px -> desktop transition:
 * desktop mounts the inline rail, while the stale drawer would keep focus and
 * body scroll locked over it. Initial desktop render is deliberately inert. */
export function useCloseRailOnDesktop(isCompact: boolean, close: () => void): void {
  const wasCompact = useRef(isCompact);

  useEffect(() => {
    if (wasCompact.current && !isCompact) close();
    wasCompact.current = isCompact;
  }, [close, isCompact]);
}
