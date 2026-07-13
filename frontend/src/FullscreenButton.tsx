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
 * Renders nothing when the controller reports no native support (iPhone
 * Safari, jsdom); a later task moves this gate out once a fallback mode
 * exists. */
export function FullscreenButton({
  controller,
  surface
}: {
  controller: FullscreenController;
  surface: string;
}) {
  if (!controller.supported) return null;
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
