"use client";

import { useEffect, useRef } from "react";

interface Props {
  spec: object;
  title?: string | null;
}

export function VegaLiteEmbed({ spec, title }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    let cancelled = false;
    let view: { finalize?: () => void } | null = null;

    (async () => {
      try {
        const vegaEmbed = (await import("vega-embed")).default;
        if (cancelled || !ref.current) return;
        const result = await vegaEmbed(ref.current, spec as any, {
          actions: false,
          renderer: "svg",
        });
        view = result.view as unknown as { finalize?: () => void };
      } catch (err) {
        if (ref.current) {
          ref.current.innerHTML = `<p class="text-xs text-destructive">Chart render failed: ${
            err instanceof Error ? err.message : String(err)
          }</p>`;
        }
      }
    })();

    return () => {
      cancelled = true;
      if (view?.finalize) view.finalize();
    };
  }, [spec]);

  return (
    <div className="rounded-md border bg-card p-3">
      {title && <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>}
      <div ref={ref} className="overflow-auto" />
    </div>
  );
}
