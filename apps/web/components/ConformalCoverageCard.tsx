"use client";

import type { ConformalCoverage } from "@/lib/types";

export function ConformalCoverageCard({ coverage }: { coverage: ConformalCoverage[] }) {
  if (!coverage || coverage.length === 0) return null;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-semibold">Prediction interval calibration</h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {coverage.map((c, idx) => {
          const empPct = c.empirical != null ? `${(c.empirical * 100).toFixed(0)}%` : "—";
          const nomPct = `${(c.nominal * 100).toFixed(0)}%`;
          const off =
            c.empirical != null ? Math.abs(c.empirical - c.nominal) * 100 : null;
          const tone =
            off == null
              ? "text-muted-foreground"
              : off < 3
              ? "text-emerald-600 dark:text-emerald-400"
              : off < 7
              ? "text-amber-600 dark:text-amber-400"
              : "text-rose-600 dark:text-rose-400";
          return (
            <li key={idx} className="flex items-baseline justify-between gap-3">
              <span className="text-muted-foreground">
                {c.horizon}-step ahead ({nomPct} nominal)
              </span>
              <span className={`font-mono tabular-nums ${tone}`}>
                empirical {empPct} (n={c.n_residuals})
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Closer to nominal is better. Above = over-conservative; below = overconfident.
      </p>
    </div>
  );
}
