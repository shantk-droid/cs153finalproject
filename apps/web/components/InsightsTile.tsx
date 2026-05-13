import { headers } from "next/headers";
import { TrendingUp, TrendingDown, AlertTriangle, Lightbulb, ArrowRight } from "lucide-react";
import Link from "next/link";

export interface Insight {
  id: string;
  severity: "info" | "warn" | "crit";
  title: string;
  body: string;
  cta_label?: string | null;
  cta_href?: string | null;
}

interface InsightsResponse {
  insights: Insight[];
}

async function fetchInsights(datasetId: string): Promise<Insight[]> {
  const h = await headers();
  const host = h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "http";
  try {
    const r = await fetch(
      `${proto}://${host}/api/datasets/${encodeURIComponent(datasetId)}/insights`,
      { cache: "no-store" },
    );
    if (!r.ok) return [];
    const data = (await r.json()) as InsightsResponse;
    return data.insights ?? [];
  } catch {
    return [];
  }
}

function iconFor(sev: Insight["severity"]) {
  if (sev === "crit") return <AlertTriangle className="h-4 w-4 text-red-600" />;
  if (sev === "warn") return <TrendingDown className="h-4 w-4 text-amber-600" />;
  return <Lightbulb className="h-4 w-4 text-blue-600" />;
}

export async function InsightsTile({ datasetId }: { datasetId: string }) {
  const insights = await fetchInsights(datasetId);

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Insights</h3>
        <span className="text-[11px] uppercase tracking-widest text-muted-foreground">
          {insights.length} this period
        </span>
      </div>
      {insights.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          No anomalies. Things look stable.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {insights.slice(0, 5).map((it) => (
            <li
              key={it.id}
              className="flex items-start gap-2 rounded border-l-2 border-muted bg-muted/30 px-2 py-2"
              style={{
                borderLeftColor:
                  it.severity === "crit"
                    ? "hsl(0 70% 50%)"
                    : it.severity === "warn"
                      ? "hsl(35 90% 50%)"
                      : "hsl(215 70% 55%)",
              }}
            >
              <span className="mt-0.5">{iconFor(it.severity)}</span>
              <div className="flex-1 text-xs">
                <p className="font-medium leading-tight">{it.title}</p>
                <p className="mt-0.5 text-muted-foreground">{it.body}</p>
                {it.cta_href && (
                  <Link
                    href={it.cta_href}
                    className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
                  >
                    {it.cta_label ?? "Open"} <ArrowRight className="h-3 w-3" />
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
