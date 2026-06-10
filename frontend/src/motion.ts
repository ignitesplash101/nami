/** "smooth" unless the user requests reduced motion. ALL JS-driven smooth
 * scrolls must gate through this — the global CSS reduced-motion block can't
 * reach JS `scrollIntoView` options. */
export function scrollBehavior(): ScrollBehavior {
  return typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}
