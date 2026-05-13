"use client";

interface Props {
  observed: number[];
  priorMean: number | null;
  priorStd: number | null;
  posteriorMean: number | null;
  posteriorStd: number | null;
}

function gaussianPdf(x: number, mu: number, sigma: number): number {
  if (sigma <= 0) return 0;
  const z = (x - mu) / sigma;
  return Math.exp(-0.5 * z * z) / (sigma * Math.sqrt(2 * Math.PI));
}

export function LeadTimeHistogram({ observed, priorMean, priorStd, posteriorMean, posteriorStd }: Props) {
  const allLT = [...observed];
  if (priorMean !== null) allLT.push(priorMean);
  if (posteriorMean !== null) allLT.push(posteriorMean);
  if (allLT.length === 0) return null;

  const lo = Math.max(0, Math.floor(Math.min(...allLT) - 2));
  const hi = Math.ceil(Math.max(...allLT) + 2);
  const range = hi - lo || 1;
  const nBins = Math.min(20, Math.max(6, Math.floor(observed.length / 2) || 6));
  const binWidth = range / nBins;

  const bins = Array(nBins).fill(0);
  for (const v of observed) {
    const idx = Math.max(0, Math.min(nBins - 1, Math.floor((v - lo) / binWidth)));
    bins[idx] += 1;
  }
  const maxCount = Math.max(...bins, 1);

  const W = 540;
  const H = 200;
  const padX = 32;
  const padY = 18;
  const innerW = W - padX * 2;
  const innerH = H - padY * 2;

  const xToPx = (x: number) => padX + ((x - lo) / range) * innerW;
  const histYToPx = (count: number) => padY + innerH - (count / maxCount) * innerH;

  const xs: number[] = [];
  for (let i = 0; i <= 60; i++) xs.push(lo + (range * i) / 60);
  const priorPath =
    priorMean !== null && priorStd !== null && priorStd > 0
      ? xs.map((x) => gaussianPdf(x, priorMean, priorStd))
      : null;
  const postPath =
    posteriorMean !== null && posteriorStd !== null && posteriorStd > 0
      ? xs.map((x) => gaussianPdf(x, posteriorMean, posteriorStd))
      : null;
  const maxPdf = Math.max(
    priorPath ? Math.max(...priorPath) : 0,
    postPath ? Math.max(...postPath) : 0,
    1e-6,
  );

  const pdfYToPx = (p: number) => padY + innerH - (p / maxPdf) * innerH * 0.85;

  const ticks: number[] = [];
  const tickStep = range > 30 ? 5 : range > 15 ? 2 : 1;
  for (let v = Math.ceil(lo); v <= hi; v += tickStep) ticks.push(v);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-2xl">
      {bins.map((count, i) => {
        const x = padX + (i / nBins) * innerW;
        const w = innerW / nBins - 1;
        const y = histYToPx(count);
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={w}
            height={padY + innerH - y}
            fill="hsl(215 50% 50%)"
            fillOpacity={0.3}
          />
        );
      })}
      {priorPath && (
        <polyline
          fill="none"
          stroke="hsl(35 80% 50%)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          points={xs.map((x, i) => `${xToPx(x)},${pdfYToPx(priorPath[i])}`).join(" ")}
        />
      )}
      {postPath && (
        <polyline
          fill="none"
          stroke="hsl(150 70% 35%)"
          strokeWidth={2}
          points={xs.map((x, i) => `${xToPx(x)},${pdfYToPx(postPath[i])}`).join(" ")}
        />
      )}
      <line x1={padX} y1={padY + innerH} x2={padX + innerW} y2={padY + innerH} stroke="currentColor" strokeOpacity={0.3} />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={xToPx(t)} y1={padY + innerH} x2={xToPx(t)} y2={padY + innerH + 3} stroke="currentColor" strokeOpacity={0.4} />
          <text x={xToPx(t)} y={padY + innerH + 14} textAnchor="middle" fontSize="10" fill="currentColor" opacity={0.6}>
            {t}d
          </text>
        </g>
      ))}
      <g transform={`translate(${padX}, ${padY})`} fontSize="10" fill="currentColor">
        <rect x={0} y={0} width={10} height={2} fill="hsl(215 50% 50%)" fillOpacity={0.5} />
        <text x={14} y={4} opacity={0.7}>observed (n={observed.length})</text>
        {priorPath && (
          <>
            <rect x={120} y={0} width={10} height={2} fill="hsl(35 80% 50%)" />
            <text x={134} y={4} opacity={0.7}>prior</text>
          </>
        )}
        {postPath && (
          <>
            <rect x={170} y={0} width={10} height={2} fill="hsl(150 70% 35%)" />
            <text x={184} y={4} opacity={0.7}>posterior</text>
          </>
        )}
      </g>
    </svg>
  );
}
