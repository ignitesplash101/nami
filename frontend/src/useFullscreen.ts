import { useCallback, useEffect, useRef, useState } from "react";
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
  const wasFullscreen = useRef(false);

  useEffect(() => {
    if (!supported) return;
    const onChange = () => {
      const next =
        document.fullscreenElement != null && document.fullscreenElement === ref.current;
      // `fullscreenchange` fires on `document` for every hook instance on
      // every transition — dispatch the resize only when THIS element's own
      // state actually flipped, or many mounted cards would fan out one real
      // transition into a resize storm. Compared via ref, NOT inside the
      // setIsFullscreen updater: StrictMode double-invokes updaters in dev,
      // which would dispatch twice; the event handler itself runs once.
      if (wasFullscreen.current !== next) {
        wasFullscreen.current = next;
        requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
      }
      setIsFullscreen(next);
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

/** Pure fullscreen chart-height rule shared by every fullscreen-capable
 * chart: inline uses `base`; fullscreen reclaims the viewport minus room for
 * heading/controls, floored so a short viewport never collapses the chart.
 * `h` prefers an explicit `viewportHeight` (from `useViewportHeight`, so it
 * tracks orientation/chrome changes), falls back to a live
 * `window.innerHeight` read, then 800 — never NaN. */
export function fullscreenChartHeight(
  isFullscreen: boolean,
  base: number,
  viewportHeight?: number
): number {
  if (!isFullscreen) return base;
  const h =
    typeof viewportHeight === "number" && Number.isFinite(viewportHeight) && viewportHeight > 0
      ? viewportHeight
      : typeof window !== "undefined" && Number.isFinite(window.innerHeight)
        ? window.innerHeight
        : 800;
  return Math.max(420, h - 260);
}

/** Tracks `window.innerHeight` reactively while `active`, `undefined`
 * otherwise. Chart cards only need this while actually fullscreen — orientation
 * changes and mobile browser-chrome show/hide (address bar collapse) resize
 * the viewport without any other trigger firing, so `fullscreenChartHeight`
 * needs a live value to recompute against. */
export function useViewportHeight(active: boolean): number | undefined {
  const [height, setHeight] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (!active || typeof window === "undefined") {
      setHeight(undefined);
      return;
    }
    const update = () => setHeight(window.innerHeight);
    update();
    window.addEventListener("resize", update);
    window.visualViewport?.addEventListener("resize", update);
    return () => {
      window.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("resize", update);
    };
  }, [active]);

  return height;
}
