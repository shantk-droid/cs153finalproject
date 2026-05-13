"use client";

import type { ForecastAudit } from "@/lib/types";

export function AuditFooter({ audit }: { audit: ForecastAudit | null | undefined }) {
  if (!audit) return null;
  const generated = new Date(audit.forecast_generated_at);
  const generatedFmt = generated.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });

  const weightsList = Object.entries(audit.ensemble_weights)
    .map(([m, w]) => `${m} ${(w * 100).toFixed(0)}%`)
    .join(", ");

  return (
    <footer className="rounded-md border border-dashed bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
      Forecast generated {generatedFmt}
      {audit.train_cutoff_date && ` · Train cutoff ${audit.train_cutoff_date}`}
      {weightsList && ` · Models: ${weightsList}`}
      {audit.ensemble_method_version && ` · Ensemble ${audit.ensemble_method_version}`}
    </footer>
  );
}
