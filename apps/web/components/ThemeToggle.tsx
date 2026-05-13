"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={
        "inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card " +
        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none " +
        "focus-visible:ring-2 focus-visible:ring-ring " +
        (className ?? "")
      }
    >
      {isDark ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
    </button>
  );
}
