"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { ForecastDecomposition, ModelLeaderboardEntry } from "@/lib/types";

interface Props {
  datasetId: string;
  skuId: string;
}

type Tab = "decomposition" | "leaderboard";

export function DecompositionTabs({ datasetId, skuId }: Props) {
  const [tab, setTab] = useState<Tab>("decomposition");
  const [decomp, setDecomp] = useState<ForecastDecomposition | null>(null);
  const [leaderboard, setLeaderboard] = useState<ModelLeaderboardEntry[] | null>(null);
  const [loading, setLoading] = useState<Tab | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (tab === "decomposition" && decomp === null) {
      setLoading("decomposition");
      setError(null);
      fetch(`/api/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/decomposition`)
        .then(async (r) => {
          if (!r.ok) throw new Error(await r.text());
          return r.json() as Promise<ForecastDecomposition>;
        })
        .then(setDecomp)
        .catch((e) => setError(e instanceof Error ? e.message : "load failed"))
        .finally(() => setLoading(null));
    }
    if (tab === "leaderboard" && leaderboard === null) {
      setLoading("leaderboard");
      setError(null);
      fetch(`/api/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/leaderboard`)
        .then(async (r) => {
          if (!r.ok) throw new Error(await r.text());
          return r.json() as Promise<ModelLeaderboardEntry[]>;
        })
        .then(setLeaderboard)
        .catch((e) => setError(e instanceof Error ? e.message : "load failed"))
        .finally(() => setLoading(null));
    }
  }, [tab, datasetId, skuId, decomp, leaderboard]);

  return (
    <div className="rounded-lg border bg-card">
      <header className="flex items-center gap-1 border-b px-2 py-1.5">
        <TabButton active={tab === "decomposition"} onClick={() => setTab("decomposition")}>
          Decomposition
        </TabButton>
        <TabButton active={tab === "leaderboard"} onClick={() => setTab("leaderboard")}>
          Model leaderboard
        </TabButton>
      </header>
      <div className="p-4">
        {loading && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
        {tab === "decomposition" && decomp && !loading && <DecompChart d={decomp} />}
        {tab === "leaderboard" && leaderboard && !loading && <LeaderboardTable entries={leaderboard} />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-sm transition-colors ${active ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground hover:bg-accent"}`}
    >
      {children}
    </button>
  );
}

function DecompChart({ d }: { d: ForecastDecomposition }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Observed = trend + seasonal (period {d.seasonal_period}) + residual.
      </p>
      <MiniChart label="Observed" values={d.observed} stroke="hsl(215 70% 50%)" />
      <MiniChart label="Trend" values={d.trend} stroke="hsl(140 60% 40%)" />
      <MiniChart label="Seasonal" values={d.seasonal} stroke="hsl(35 80% 50%)" />
      <MiniChart label="Residual" values={d.residual} stroke="hsl(0 60% 50%)" zeroLine />
    </div>
  );
}

function MiniChart({
  label,
  values,
  stroke,
  zeroLine,
}: {
  label: string;
  values: number[];
  stroke: string;
  zeroLine?: boolean;
}) {
  if (values.length < 2) return null;
  const W = 720;
  const H = 80;
  const padX = 32;
  const padY = 8;
  const innerW = W - padX * 2;
  const innerH = H - padY * 2;
  const lo = Math.min(...values, zeroLine ? 0 : Infinity);
  const hi = Math.max(...values, zeroLine ? 0 : -Infinity);
  const range = hi - lo || 1;
  const xs = values.map((_, i) => padX + (i / (values.length - 1)) * innerW);
  const ys = values.map((v) => padY + innerH - ((v - lo) / range) * innerH);
  const points = xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const zeroY = zeroLine ? padY + innerH - ((0 - lo) / range) * innerH : null;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs text-muted-foreground">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums">
          {lo.toFixed(1)} – {hi.toFixed(1)}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 w-full">
        {zeroY !== null && (
          <line
            x1={padX}
            y1={zeroY}
            x2={padX + innerW}
            y2={zeroY}
            stroke="currentColor"
            strokeOpacity={0.15}
          />
        )}
        <polyline points={points} fill="none" stroke={stroke} strokeWidth={1.5} />
      </svg>
    </div>
  );
}

function LeaderboardTable({ entries }: { entries: ModelLeaderboardEntry[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-muted-foreground">
        <tr>
          <th className="px-2 py-1.5 text-left">Method</th>
          <th className="px-2 py-1.5 text-right">MAPE</th>
          <th className="px-2 py-1.5 text-right">sMAPE</th>
          <th className="px-2 py-1.5 text-right">MASE</th>
          <th className="px-2 py-1.5 text-right">CRPS</th>
          <th className="px-2 py-1.5 text-left">Selected</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr
            key={e.method}
            className={`border-t ${e.selected ? "bg-emerald-50" : ""} ${!e.available ? "text-muted-foreground" : ""}`}
          >
            <td className="px-2 py-1.5 font-mono text-xs">
              {e.method}
              {e.notes && !e.notes.startsWith("unavailable") && (
                <span className="ml-1 text-muted-foreground">· {e.notes}</span>
              )}
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">
              {e.mape === null ? "—" : `${e.mape.toFixed(1)}%`}
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">
              {e.smape === null ? "—" : `${e.smape.toFixed(1)}%`}
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">
              {e.mase === null ? "—" : e.mase.toFixed(2)}
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">
              {e.crps === null ? "—" : e.crps.toFixed(2)}
            </td>
            <td className="px-2 py-1.5 text-left">
              {e.selected ? (
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
                  ✓ winner
                </span>
              ) : !e.available ? (
                <span className="text-[11px] text-muted-foreground">unavailable</span>
              ) : (
                <span className="text-[11px] text-muted-foreground">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
