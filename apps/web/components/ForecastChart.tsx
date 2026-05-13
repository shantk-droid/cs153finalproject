"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Forecast } from "@/lib/types";

interface HistoryPoint {
  date: string;
  demand: number;
}

interface Props {
  history: HistoryPoint[];
  forecast: Forecast;
  height?: number;
}

interface ChartPoint {
  date: string;
  history?: number;
  point?: number;
  band80_low?: number;
  band80_high?: number;
  band95_low?: number;
  band95_high?: number;
}

export function ForecastChart({ history, forecast, height = 320 }: Props) {
  const historyPoints: ChartPoint[] = history.map((h) => ({ date: h.date, history: h.demand }));

  const q025 = forecast.quantiles["0.025"] ?? [];
  const q1 = forecast.quantiles["0.1"] ?? [];
  const q9 = forecast.quantiles["0.9"] ?? [];
  const q975 = forecast.quantiles["0.975"] ?? [];

  const forecastPoints: ChartPoint[] = forecast.forecast_dates.map((date, i) => ({
    date,
    point: forecast.point[i],
    band80_low: q1[i],
    band80_high: q9[i],
    band95_low: q025[i],
    band95_high: q975[i],
  }));

  const data = [...historyPoints, ...forecastPoints];

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11 }}
            tickFormatter={(d) => String(d).slice(5)}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 6 }}
            labelFormatter={(d) => String(d)}
            formatter={(value: number, name: string) => [
              typeof value === "number" ? value.toFixed(1) : value,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />

          <Area
            type="monotone"
            dataKey="band95_high"
            stroke="none"
            fill="hsl(var(--primary))"
            fillOpacity={0.08}
            name="95% interval"
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="band95_low"
            stroke="none"
            fill="hsl(var(--background))"
            fillOpacity={1}
            isAnimationActive={false}
            legendType="none"
          />
          <Area
            type="monotone"
            dataKey="band80_high"
            stroke="none"
            fill="hsl(var(--primary))"
            fillOpacity={0.18}
            name="80% interval"
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="band80_low"
            stroke="none"
            fill="hsl(var(--background))"
            fillOpacity={1}
            isAnimationActive={false}
            legendType="none"
          />

          <Line
            type="monotone"
            dataKey="history"
            stroke="hsl(var(--foreground))"
            strokeWidth={1.5}
            dot={false}
            name="actual"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="point"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
            name="forecast"
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
