"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";

interface ThemeCtx {
  theme: Theme;
  toggle: () => void;
  set: (t: Theme) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

const STORAGE_KEY = "io-theme";

function readInitial(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(t: Theme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (t === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const t = readInitial();
    setTheme(t);
    applyTheme(t);
  }, []);

  const set = useCallback((t: Theme) => {
    setTheme(t);
    applyTheme(t);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* ignore quota errors */
    }
  }, []);

  const toggle = useCallback(() => set(theme === "dark" ? "light" : "dark"), [theme, set]);

  return <Ctx.Provider value={{ theme, toggle, set }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    // Not inside a provider yet (e.g. during SSR before hydrate). Return a noop shim.
    return {
      theme: "light",
      toggle: () => undefined,
      set: () => undefined,
    };
  }
  return ctx;
}

/**
 * Inline script content — paste into <head> before hydration to avoid FOUC.
 * Reads localStorage + system preference and sets the `.dark` class on <html> *before*
 * any React or CSS evaluation.
 */
export const THEME_INIT_SCRIPT = `
(function(){try{var t=localStorage.getItem("${STORAGE_KEY}");if(!t){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}if(t==="dark"){document.documentElement.classList.add("dark");}}catch(e){}})();
`.trim();
