import { Maximize2, Minimize2 } from "lucide-react";

/** Subset of `useFullscreen`'s return value the button needs — plain props so
 * it renders and tests without mounting the native Fullscreen API. */
export interface FullscreenController {
  isFullscreen: boolean;
  toggle: () => void;
  supported: boolean;
}

/** Shared fullscreen toggle for chart cards. `surface` names what expands
 * ("contribution waterfall") so the label stays specific across many
 * instances — "View full screen" is ambiguous once several cards have one.
 * The affordance is universal: `useFullscreen` uses the native API where
 * supported and an app-owned expanded-card modal on the same node otherwise
 * (iPhone Safari), so the button no longer gates on `controller.supported`. */
export function FullscreenButton({
  controller,
  surface
}: {
  controller: FullscreenController;
  surface: string;
}) {
  const label = `${controller.isFullscreen ? "Collapse" : "Expand"} ${surface}`;
  return (
    <button
      type="button"
      className="methodology-btn"
      onClick={controller.toggle}
      aria-label={label}
      title={label}
    >
      {controller.isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
    </button>
  );
}
