import { useEffect, useState } from "react";
import type { RefObject } from "react";

/** True while the element can scroll further right — drives the right-edge
 * fade so the affordance renders only when content is actually hidden, and
 * disappears once the user reaches the end. */
export function useScrollFade(ref: RefObject<HTMLElement>): boolean {
  const [showFade, setShowFade] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => {
      const canScroll = node.scrollWidth - node.clientWidth > 1;
      const atEnd = node.scrollLeft + node.clientWidth >= node.scrollWidth - 1;
      setShowFade(canScroll && !atEnd);
    };
    update();
    node.addEventListener("scroll", update, { passive: true });
    // ResizeObserver is absent in some test environments — degrade to the
    // window resize listener below.
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    observer?.observe(node);
    window.addEventListener("resize", update);
    return () => {
      node.removeEventListener("scroll", update);
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [ref]);

  return showFade;
}
