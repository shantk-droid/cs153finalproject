"use client";

import { useState } from "react";

interface Props {
  values: number[] | null | undefined;
  width?: number;
  height?: number;
  className?: string;
  /** Show hover tooltip with the underlying values. Disable on dense pages. */
  interactive?: boolean;
}

export function Sparkline({ values, width = 80, height = 24, className, interactive = true }: Props) {
  const [hover, setHover] = useState(false);

  if (!values || values.length < 2) {
    return (
      <svg width={width} height={height} className={className} aria-hidden>
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="currentColor" strokeOpacity={0.2} />
      </svg>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const fillPath = `M0,${height} L${points.join(" L")} L${width},${height} Z`;

  const minIdx = values.indexOf(min);
  const maxIdx = values.indexOf(max);
  const anchorY = (idx: number) => height - ((values[idx] - min) / range) * (height - 2) - 1;

  return (
    <span
      className={`relative inline-block align-middle ${className ?? ""}`}
      onMouseEnter={interactive ? () => setHover(true) : undefined}
      onMouseLeave={interactive ? () => setHover(false) : undefined}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        <path d={fillPath} fill="currentColor" fillOpacity={0.12} />
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.25}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx={maxIdx * stepX} cy={anchorY(maxIdx)} r={1.6} className="fill-emerald-500" />
        <circle cx={minIdx * stepX} cy={anchorY(minIdx)} r={1.6} className="fill-rose-500" />
      </svg>
      {interactive && hover && (
        <span
          role="tooltip"
          className="pointer-events-none absolute left-1/2 top-full z-30 mt-1 -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-[10px] text-popover-foreground shadow-lg"
        >
          {values.map((v, i) => (
            <span key={i} className="mr-1 tabular-nums">
              {Math.round(v)}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
