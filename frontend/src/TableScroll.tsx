import { useRef } from "react";
import type { ReactNode } from "react";
import { useScrollFade } from "./useScrollFade";

/** Scroll container + the right-edge fade affordance. The fade lives on the
 * NON-scrolling wrapper so it stays anchored to the scrollport, and it only
 * renders while there is hidden content to the right (useScrollFade). The
 * inner .table-scroll div is the load-bearing wrapper for wide tables — keep
 * it. */
export function TableScroll({ children }: { children: ReactNode }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const showFade = useScrollFade(scrollRef);
  return (
    <div className={`table-wrap${showFade ? " has-overflow" : ""}`}>
      <div className="table-scroll" ref={scrollRef}>
        {children}
      </div>
    </div>
  );
}
