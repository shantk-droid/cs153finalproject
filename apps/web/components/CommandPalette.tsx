"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, ArrowUpRight, Hash, Truck, FileText } from "lucide-react";
import { listSkus } from "@/lib/api-client";
import type { SkuTableRow } from "@/lib/types";

type ResultKind = "page" | "sku" | "supplier";

interface Result {
  kind: ResultKind;
  label: string;
  sublabel?: string;
  href: string;
  score: number;
}

const PAGES: Array<{ label: string; suffix: string; sub: string }> = [
  { label: "Overview", suffix: "/overview", sub: "KPIs · ABC×XYZ · insights" },
  { label: "Reorder Queue", suffix: "/reorder", sub: "Ranked POs · drafts" },
  { label: "Forecasts", suffix: "/forecasts", sub: "Sparkline table · per-SKU detail" },
  { label: "Frontier", suffix: "/frontier", sub: "Service-level vs cost · newsvendor" },
  { label: "Suppliers", suffix: "/suppliers", sub: "Scorecards · OTIF · lead-time" },
  { label: "Stress test", suffix: "/stress", sub: "Lead-time & demand shocks · VaR" },
  { label: "Data quality", suffix: "/quality", sub: "Composite · components · profile selector" },
  { label: "Chat", suffix: "/chat", sub: "Ask the data anything" },
];

function fuzzyScore(haystack: string, needle: string): number {
  if (!needle) return 0.0;
  const h = haystack.toLowerCase();
  const n = needle.toLowerCase();
  if (h.startsWith(n)) return 5 + (n.length / h.length);
  if (h.includes(" " + n)) return 4;
  if (h.includes(n)) return 3 + (n.length / h.length);
  // initials match: split words and check first chars
  const words = h.split(/[^a-z0-9]+/);
  const inits = words.map((w) => w[0] ?? "").join("");
  if (inits.includes(n)) return 2;
  return 0;
}

export function CommandPalette({ datasetId }: { datasetId: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [skus, setSkus] = useState<SkuTableRow[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open && skus === null) {
      listSkus(datasetId, { limit: 1000 }).then(setSkus).catch(() => setSkus([]));
    }
  }, [open, datasetId, skus]);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      setQuery("");
    }
  }, [open]);

  const results = useMemo<Result[]>(() => {
    const out: Result[] = [];
    const q = query.trim();
    const base = `/dashboard/${datasetId}`;

    for (const p of PAGES) {
      const score = q ? fuzzyScore(p.label + " " + p.sub, q) : 1;
      if (q === "" || score > 0) {
        out.push({
          kind: "page",
          label: p.label,
          sublabel: p.sub,
          href: base + p.suffix,
          score: q ? score : 1,
        });
      }
    }

    if (skus && q) {
      const supplierMap = new Map<string, number>();
      for (const r of skus) {
        const s = (r as unknown as { supplier?: string | null }).supplier;
        if (s) supplierMap.set(s, (supplierMap.get(s) ?? 0) + 1);
        const text = `${r.sku_id} ${r.supplier ?? ""} ${r.category ?? ""}`;
        const score = fuzzyScore(text, q);
        if (score > 0) {
          out.push({
            kind: "sku",
            label: r.sku_id,
            sublabel: [r.category, r.supplier].filter(Boolean).join(" · "),
            href: `${base}/sku/${encodeURIComponent(r.sku_id)}`,
            score,
          });
        }
      }
      for (const [name] of supplierMap) {
        const score = fuzzyScore(name, q);
        if (score > 0) {
          out.push({
            kind: "supplier",
            label: name,
            sublabel: "Supplier",
            href: `${base}/suppliers?q=${encodeURIComponent(name)}`,
            score,
          });
        }
      }
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, 30);
  }, [query, skus, datasetId]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="m-3 ml-auto hidden items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent md:inline-flex"
        aria-label="Open command palette"
      >
        <Search className="h-3.5 w-3.5" />
        Search
        <kbd className="rounded border border-border bg-card px-1 font-mono text-[10px]">⌘K</kbd>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={() => setOpen(false)}
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="mt-24 w-full max-w-xl overflow-hidden rounded-lg border bg-card shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type to search SKUs, suppliers, pages..."
            className="flex-1 bg-transparent px-1 py-3 text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            ESC
          </kbd>
        </div>
        <div className="max-h-[420px] overflow-y-auto py-1">
          {results.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">No matches</p>
          )}
          {results.map((r, i) => (
            <button
              key={`${r.kind}-${r.href}-${i}`}
              type="button"
              onClick={() => {
                setOpen(false);
                router.push(r.href);
              }}
              className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-accent"
            >
              <span className="text-muted-foreground">
                {r.kind === "page" ? (
                  <FileText className="h-3.5 w-3.5" />
                ) : r.kind === "sku" ? (
                  <Hash className="h-3.5 w-3.5" />
                ) : (
                  <Truck className="h-3.5 w-3.5" />
                )}
              </span>
              <span className="flex-1">
                <span className="font-medium">{r.label}</span>
                {r.sublabel && (
                  <span className="ml-2 text-xs text-muted-foreground">{r.sublabel}</span>
                )}
              </span>
              <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
