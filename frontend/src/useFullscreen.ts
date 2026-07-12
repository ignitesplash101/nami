import { useCallback, useEffect, useState } from "react";
import type { RefObject } from "react";

/** Native element fullscreen for chart cards. Deliberately NOT a useOverlay —
 * the browser owns Esc/backdrop, so the app's two-overlays-Esc rule is
 * untouched. `supported` is false where the API is absent (iPhone Safari);
 * callers hide the affordance there. A fullscreen flip dispatches a window
 * resize next frame so Plotly (responsive: true) re-fits both ways. */
export function useFullscreen(ref: RefObject<HTMLElement>): {
  isFullscreen: boolean;
  toggle: () => void;
  supported: boolean;
} {
  const supported =
    typeof document !== "undefined" && Boolean(document.fullscreenEnabled);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    if (!supported) return;
    const onChange = () => {
      setIsFullscreen(
        document.fullscreenElement != null && document.fullscreenElement === ref.current
      );
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [ref, supported]);

  const toggle = useCallback(() => {
    const node = ref.current;
    if (!node) return;
    if (document.fullscreenElement === node) {
      void document.exitFullscreen();
    } else {
      void node.requestFullscreen().catch(() => {
        // Permission/API failure: stay inline — the button is a progressive
        // enhancement, never a broken state.
      });
    }
  }, [ref]);

  return { isFullscreen, toggle, supported };
}
