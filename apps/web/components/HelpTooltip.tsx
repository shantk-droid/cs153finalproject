"use client";

import { useState } from "react";
import { Info } from "lucide-react";

interface Props {
  text: string;
  side?: "top" | "bottom";
  /** Horizontal placement of the tooltip relative to the icon.
   *  - "center" (default): centered on the icon. Best for mid-row columns.
   *  - "end": right edge of the tooltip aligned to icon's right edge — tooltip extends to the LEFT.
   *           Use this on the last column of a table so the tooltip doesn't overflow off-screen.
   *  - "start": left edge aligned to icon's left edge — tooltip extends to the RIGHT.
   */
  align?: "center" | "end" | "start";
  className?: string;
}

export function HelpTooltip({ text, side = "bottom", align = "center", className }: Props) {
  const [open, setOpen] = useState(false);
  const horizontal =
    align === "end"
      ? "right-0"
      : align === "start"
      ? "left-0"
      : "left-1/2 -translate-x-1/2";
  return (
    <span
      className={`relative ml-1 inline-block align-middle ${className ?? ""}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        tabIndex={0}
        aria-label="Column info"
        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-muted-foreground/70 hover:text-foreground"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <Info className="h-3 w-3" />
      </button>
      {open && (
        <span
          role="tooltip"
          className={`pointer-events-none absolute z-[60] w-60 rounded-md border bg-popover px-3 py-2 text-[11px] font-normal normal-case leading-snug text-popover-foreground shadow-xl ${horizontal} ${
            side === "bottom" ? "top-full mt-1" : "bottom-full mb-1"
          }`}
        >
          {text}
        </span>
      )}
    </span>
  );
}
