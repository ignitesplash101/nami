import { useCallback, useEffect, useState } from "react";

/** Dual-theme state. The boot script in index.html sets `data-theme` on <html>
 * before first paint (no FOUC); this hook mirrors and mutates that attribute.
 * System preference is followed until the user toggles explicitly — the
 * explicit choice persists in localStorage and wins from then on. */

export type Theme = "dark" | "light";

const STORAGE_KEY = "nami-theme";
/** Keep in sync with --bg in styles.css and the boot script in index.html. */
const THEME_COLORS: Record<Theme, string> = { dark: "#0b1b2b", light: "#f4efe3" };

export function readTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function writeTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLORS[theme]);
}

function storedChoice(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (event: MediaQueryListEvent) => {
      if (storedChoice()) return; // explicit choice wins over OS changes
      const next: Theme = event.matches ? "light" : "dark";
      writeTheme(next);
      setTheme(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      writeTheme(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Private-mode storage failure: theme still flips for this session.
      }
      return next;
    });
  }, []);

  return { theme, toggleTheme };
}
