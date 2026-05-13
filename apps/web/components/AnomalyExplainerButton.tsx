"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { AnomalyDrawer } from "@/components/AnomalyDrawer";

interface Props {
  datasetId: string;
  skuId: string;
}

export function AnomalyExplainerButton({ datasetId, skuId }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-7 items-center gap-1 rounded-md border border-input bg-background px-2 text-xs hover:bg-accent"
        title="Explain anomalies in this SKU's history"
      >
        <Sparkles className="h-3 w-3 text-primary" />
        Explain anomaly
      </button>
      {open && (
        <AnomalyDrawer
          datasetId={datasetId}
          skuId={skuId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
