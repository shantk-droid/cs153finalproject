"use client";

import { useState } from "react";
import { Info, X } from "lucide-react";
import { METHODOLOGY } from "@/lib/methodology";

interface Props {
  metric: keyof typeof METHODOLOGY;
  contextValues?: Record<string, string | number | null>;
}

export function MethodologyDrawer({ metric, contextValues }: Props) {
  const [open, setOpen] = useState(false);
  const entry = METHODOLOGY[metric];
  if (!entry) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
        aria-label={`How is ${entry.title} computed?`}
      >
        <Info className="h-3 w-3" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/40 backdrop-blur-sm"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md overflow-y-auto bg-card shadow-2xl"
          >
            <header className="flex items-center justify-between border-b px-4 py-3">
              <div className="flex items-center gap-2">
                <Info className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold">How this is computed</h2>
              </div>
              <button type="button" onClick={() => setOpen(false)} className="rounded p-1 hover:bg-muted">
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="space-y-4 p-4">
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Metric</p>
                <h3 className="text-base font-semibold">{entry.title}</h3>
              </div>
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Formula</p>
                <pre className="mt-1 overflow-x-auto rounded bg-muted/40 p-2 font-mono text-xs">
                  {entry.formula}
                </pre>
              </div>
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Inputs</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {entry.inputs.map((line, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-muted-foreground">•</span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {contextValues && Object.keys(contextValues).length > 0 && (
                <div>
                  <p className="text-xs uppercase tracking-widest text-muted-foreground">Current values</p>
                  <table className="mt-1 w-full text-sm">
                    <tbody>
                      {Object.entries(contextValues).map(([k, v]) => (
                        <tr key={k} className="border-b last:border-0">
                          <td className="py-1 text-muted-foreground">{k}</td>
                          <td className="py-1 text-right font-mono tabular-nums">
                            {v === null ? "—" : v}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Assumptions</p>
                <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
                  {entry.assumptions.map((a, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span>—</span>
                      <span>{a}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
