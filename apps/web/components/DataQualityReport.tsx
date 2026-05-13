"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { listProfiles, patchDatasetMetadata } from "@/lib/api-client";
import type {
  Assertion,
  ComponentName,
  ComponentScore,
  DataQualityReport,
  ProfileListEntry,
  Severity,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const COMPONENT_LABEL: Record<ComponentName, string> = {
  completeness: "Completeness",
  plausibility: "Plausibility",
  distribution_profile: "Distribution profile",
  history_depth: "History depth",
  stationarity: "Stationarity / regime stability",
};

const COMPONENT_HELP: Record<ComponentName, string> = {
  completeness: "Optional fields populated + per-SKU date coverage.",
  plausibility:
    "Penalties from business-logic violations: negative demand, price < cost, lead-time outliers, demand spikes, implausible on-hand, date gaps.",
  distribution_profile:
    "How closely your data matches the chosen reference profile's distribution norms. Out-of-band SKUs are flagged for awareness, not penalized harshly.",
  history_depth: "Observation count per SKU. Drives forecast confidence and cold-start treatment.",
  stationarity:
    "Pettitt + Mann-Kendall + rolling-mean shift to catch structural breaks in the recent window.",
};

function scoreColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 80) return "text-green-600 dark:text-green-400";
  if (score >= 60) return "text-yellow-600 dark:text-yellow-400";
  return "text-destructive";
}

function severityClass(s: Severity): string {
  if (s === "hard") return "bg-destructive/10 text-destructive";
  if (s === "soft") return "bg-yellow-500/10 text-yellow-700 dark:text-yellow-300";
  return "bg-sky-500/10 text-sky-700 dark:text-sky-300";
}

function ComponentTile({ c }: { c: ComponentScore }) {
  const deferred = c.score === null;
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        deferred && "border-dashed bg-muted/30",
      )}
    >
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-medium">{COMPONENT_LABEL[c.name]}</h3>
        <p className={cn("text-2xl font-semibold tabular-nums", scoreColor(c.score))}>
          {deferred ? "—" : Math.round(c.score!)}
          {!deferred && <span className="text-xs font-normal text-muted-foreground"> / 100</span>}
        </p>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{COMPONENT_HELP[c.name]}</p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        Weight: {(c.weight * 100).toFixed(0)}%
      </p>
      <ul className="mt-3 space-y-0.5">
        {c.notes.map((n, i) => (
          <li key={i} className="text-xs text-muted-foreground">
            • {n}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssertionRow({ a }: { a: Assertion }) {
  return (
    <details className="rounded-md border bg-card">
      <summary className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium uppercase", severityClass(a.severity))}>
            {a.severity}
          </span>
          <span className="font-mono text-xs text-muted-foreground">{a.code}</span>
          <span className="text-sm">{a.message}</span>
        </div>
        <span className="text-xs text-muted-foreground">
          {a.offending_row_count} rows
          {a.skus_affected ? ` · ${a.skus_affected} SKUs` : ""}
        </span>
      </summary>
      {a.offending_examples.length > 0 && (
        <div className="overflow-auto border-t px-3 py-2">
          <table className="min-w-full text-xs">
            <thead className="text-left">
              <tr>
                {Object.keys(a.offending_examples[0]).map((k) => (
                  <th key={k} className="border-b px-2 py-1 font-medium">
                    {k}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.offending_examples.map((row, i) => (
                <tr key={i} className="border-b last:border-b-0">
                  {Object.keys(a.offending_examples[0]).map((k) => (
                    <td key={k} className="px-2 py-1 font-mono">
                      {row[k] === null || row[k] === undefined ? "—" : String(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

export function DataQualityReportView({ report }: { report: DataQualityReport }) {
  const composite = report.composite_score;
  const assertionsBySeverity = {
    hard: report.assertions.filter((a) => a.severity === "hard"),
    soft: report.assertions.filter((a) => a.severity === "soft"),
    info: report.assertions.filter((a) => a.severity === "info"),
  };
  const flagged = report.flagged_metrics ?? {};
  const flaggedEntries = Object.entries(flagged).filter(([, v]) => v > 0);

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between gap-6">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">Data Quality</p>
          <h1 className="text-3xl font-semibold tracking-tight">Composite Score</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {report.n_rows.toLocaleString()} rows · {report.n_skus.toLocaleString()} SKUs ·{" "}
            {report.skus_low_history.length} SKUs flagged for cold-start treatment
          </p>
          {report.profile && (
            <ProfileSelector
              datasetId={report.dataset_id}
              currentId={report.profile.profile_id}
              currentLabel={report.profile.label}
              autoDetected={report.profile.auto_detected}
              matchConfidence={report.profile.match_confidence}
            />
          )}
        </div>
        <p className={cn("text-6xl font-bold tabular-nums", scoreColor(composite))}>
          {composite === null ? "—" : Math.round(composite)}
        </p>
      </header>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Components
        </h2>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {report.components.map((c) => (
            <ComponentTile key={c.name} c={c} />
          ))}
        </div>
        {flaggedEntries.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            <span className="font-medium">Outside [p10, p90] for this profile:</span>{" "}
            {flaggedEntries.map(([m, n], i) => (
              <span key={m}>
                {i > 0 ? ", " : ""}
                {m} ({n})
              </span>
            ))}
            . These are informational — not penalized.
          </p>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Assertions
        </h2>
        {report.assertions.length === 0 && (
          <p className="text-sm text-muted-foreground">No assertions triggered. Looks clean.</p>
        )}
        {assertionsBySeverity.hard.length > 0 && (
          <div className="space-y-2">
            {assertionsBySeverity.hard.map((a, i) => (
              <AssertionRow key={`hard-${i}`} a={a} />
            ))}
          </div>
        )}
        {assertionsBySeverity.soft.length > 0 && (
          <div className="space-y-2">
            {assertionsBySeverity.soft.map((a, i) => (
              <AssertionRow key={`soft-${i}`} a={a} />
            ))}
          </div>
        )}
        {assertionsBySeverity.info.length > 0 && (
          <div className="space-y-2">
            {assertionsBySeverity.info.map((a, i) => (
              <AssertionRow key={`info-${i}`} a={a} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ProfileSelector({
  datasetId,
  currentId,
  currentLabel,
  autoDetected,
  matchConfidence,
}: {
  datasetId: string;
  currentId: string;
  currentLabel: string;
  autoDetected: boolean;
  matchConfidence: number | null;
}) {
  const router = useRouter();
  const [profiles, setProfiles] = useState<ProfileListEntry[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selection = autoDetected ? "auto" : currentId;

  useEffect(() => {
    if (!editing || profiles !== null) return;
    listProfiles()
      .then((p) => setProfiles(p.profiles))
      .catch(() => setProfiles([]));
  }, [editing, profiles]);

  async function onChange(next: string) {
    if (next === selection) return;
    setSaving(true);
    setError(null);
    try {
      await patchDatasetMetadata(datasetId, next);
      router.refresh();
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <p className="mt-2 inline-flex flex-wrap items-center gap-2 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-[11px] text-muted-foreground">
        Profile:{" "}
        <span className="font-medium text-foreground">{currentLabel}</span>
        {autoDetected && (
          <span>
            (auto-detected
            {matchConfidence != null ? `, ${(matchConfidence * 100).toFixed(0)}% confidence` : ""}
            )
          </span>
        )}
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-primary hover:underline"
        >
          change →
        </button>
      </p>
    );
  }

  return (
    <div className="mt-2 inline-flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-[11px]">
      <span className="text-muted-foreground">Profile:</span>
      <select
        value={selection}
        disabled={saving || profiles === null}
        onChange={(e) => onChange(e.target.value)}
        className="h-7 rounded-md border border-input bg-background px-2 text-[11px] text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="auto">Auto-detect (recommended)</option>
        {profiles?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
      </select>
      {saving && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Rescoring…
        </span>
      )}
      {!saving && (
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setError(null);
          }}
          className="text-muted-foreground hover:text-foreground"
        >
          cancel
        </button>
      )}
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
