"use client";

import type { SkuStatus } from "@/lib/types";

const STYLE: Record<SkuStatus, { label: string; classes: string }> = {
  order_now: {
    label: "Order now",
    classes: "border-red-300 bg-red-100 text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300",
  },
  at_risk: {
    label: "At risk",
    classes: "border-amber-300 bg-amber-100 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300",
  },
  watch: {
    label: "Watch",
    classes: "border-yellow-300 bg-yellow-100 text-yellow-800 dark:border-yellow-900/60 dark:bg-yellow-950/40 dark:text-yellow-300",
  },
  healthy: {
    label: "Healthy",
    classes: "border-emerald-300 bg-emerald-100 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300",
  },
};

export function StatusPill({ status, size = "md" }: { status: SkuStatus; size?: "sm" | "md" }) {
  const s = STYLE[status];
  const sz = size === "sm" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${sz} ${s.classes}`}
      aria-label={`Status: ${s.label}`}
    >
      {s.label}
    </span>
  );
}

export const STATUS_LABELS: Record<SkuStatus, string> = {
  order_now: "Order now",
  at_risk: "At risk",
  watch: "Watch",
  healthy: "Healthy",
};
