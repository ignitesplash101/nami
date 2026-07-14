import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { useFocusTrap } from "./useFocusTrap";

/** At most one expanded card app-wide. A fixed-position card over the app is
 * modally exclusive by nature, and the app allows only ONE window-level Esc
 * owner at a time — so the singleton doubles as the mutual-exclusion handle the
 * overlay manager clears before opening a drawer/palette. */
interface ExpandedCardHandle {
  collapse: () => void;
}
let activeCard: ExpandedCardHandle | null = null;

/** Collapse the currently expanded card, if any. Safe no-op when none is open.
 * Called by the overlay manager so a drawer/palette never coexists with an
 * expanded card (two window-level Esc owners must never overlap). */
export function closeExpandedCard(): void {
  activeCard?.collapse();
}

export interface VisibilityTransition {
  /** Mounted container whose selected child is changing (area tabs or result tabs). */
  scope: Element | null;
  /** Child that will remain visible after the programmatic navigation. */
  nextVisible: Element | null;
}

/** Exit native fullscreen only when a programmatic area/tab change will hide
 * its owner. A Drivers waterfall that remains inside every affected visible
 * panel stays fullscreen; fullscreen outside an unrelated changing scope is
 * likewise untouched. The app-owned fallback is handled separately by
 * closeExpandedCard(), because it must release its own scroll lock eagerly. */
export function exitNativeFullscreenIfOwnerWillHide(
  transitions: VisibilityTransition[]
): boolean {
  if (typeof document === "undefined") return false;
  const owner = document.fullscreenElement;
  if (!owner) return false;

  const willHide = transitions.some(
    ({ scope, nextVisible }) =>
      scope?.contains(owner) === true && nextVisible?.contains(owner) !== true
  );
  if (!willHide || typeof document.exitFullscreen !== "function") return false;

  void Promise.resolve(document.exitFullscreen()).catch(() => {});
  return true;
}

export interface FullscreenOptions {
  /** Names what expands ("contribution waterfall"), used as the modal
   * `aria-label` in the expanded-card fallback. */
  surface: string;
}

/** Fullscreen for chart cards, with two presentation modes on the SAME node:
 * the native Fullscreen API where available, and an app-owned "expanded card"
 * modal fallback where it is absent (iPhone Safari: `document.fullscreenEnabled`
 * falsy) or rejects at runtime. Callers must not care which mode is active —
 * `isFullscreen` is true in both. A transition dispatches a window resize next
 * frame so Plotly (responsive: true) / useScrollFade re-fit both ways. */
export function useFullscreen(
  ref: RefObject<HTMLElement>,
  options?: FullscreenOptions
): {
  isFullscreen: boolean;
  toggle: () => void;
  supported: boolean;
} {
  const supported =
    typeof document !== "undefined" && Boolean(document.fullscreenEnabled);
  const [nativeFullscreen, setNativeFullscreen] = useState(false);
  const [cardExpanded, setCardExpanded] = useState(false);
  const wasFullscreen = useRef(false);
  const surfaceRef = useRef(options?.surface ?? "");
  surfaceRef.current = options?.surface ?? "";

  useEffect(() => {
    if (!supported) return;
    const onChange = () => {
      const next =
        document.fullscreenElement != null && document.fullscreenElement === ref.current;
      // `fullscreenchange` fires on `document` for every hook instance on
      // every transition — dispatch the resize only when THIS element's own
      // state actually flipped, or many mounted cards would fan out one real
      // transition into a resize storm. Compared via ref, NOT inside the
      // setNativeFullscreen updater: StrictMode double-invokes updaters in dev,
      // which would dispatch twice; the event handler itself runs once.
      if (wasFullscreen.current !== next) {
        wasFullscreen.current = next;
        requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
      }
      setNativeFullscreen(next);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [ref, supported]);

  const collapse = useCallback(() => setCardExpanded(false), []);
  const expand = useCallback(() => {
    // Singleton: displace any other expanded card in the same batch so exactly
    // one card is ever open.
    closeExpandedCard();
    setCardExpanded(true);
  }, []);

  // Focus containment while the fallback modal is open (Tab-cycling only; the
  // effect below owns capture/restore + scroll-lock + Esc).
  useFocusTrap(ref, cardExpanded);

  useEffect(() => {
    if (!cardExpanded) return;
    const node = ref.current;
    if (!node) return;
    const root = document.documentElement;

    const handle: ExpandedCardHandle = { collapse };
    activeCard = handle;

    // Mirror OverlayShell: capture the opener to restore focus to on exit.
    const opener = document.activeElement;

    node.classList.add("is-card-expanded");
    root.classList.add("has-expanded-card");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    node.setAttribute("aria-label", surfaceRef.current);

    // Mirror useOverlay's exact scroll-lock mechanism.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") collapse();
    };
    window.addEventListener("keydown", onKeyDown);

    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));

    return () => {
      node.classList.remove("is-card-expanded");
      root.classList.remove("has-expanded-card");
      node.removeAttribute("role");
      node.removeAttribute("aria-modal");
      node.removeAttribute("aria-label");
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
      if (activeCard === handle) activeCard = null;
      if (opener instanceof HTMLElement) opener.focus();
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
  }, [cardExpanded, ref, collapse]);

  const toggle = useCallback(() => {
    const node = ref.current;
    if (!node) return;

    if (cardExpanded) {
      collapse();
      return;
    }

    if (!supported) {
      expand();
      return;
    }

    if (document.fullscreenElement === node) {
      void document.exitFullscreen();
    } else {
      void node.requestFullscreen().catch(() => {
        // Native rejected at runtime (permission/policy): fall back to the
        // app-owned modal so the affordance is never a dead button.
        expand();
      });
    }
  }, [ref, cardExpanded, supported, collapse, expand]);

  return { isFullscreen: nativeFullscreen || cardExpanded, toggle, supported };
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
