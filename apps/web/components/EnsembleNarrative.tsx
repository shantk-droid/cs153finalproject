"use client";

const MODEL_DESC: Record<string, string> = {
  ets: "ETS — captures trend and weekly seasonality.",
  arima: "ARIMA — autoregressive errors with seasonal differencing.",
  seasonal_naive: "Seasonal naive — last period's value at the same season.",
  croston: "Croston / TSB — intermittent demand decomposition.",
  tsb: "TSB — Croston variant with smoothed inter-arrival times.",
  ml_lgb: "LightGBM — picks up promo, calendar, and category effects via engineered features.",
  chronos_bolt: "Chronos-Bolt — Amazon's foundation model for time series; handles structural shifts well.",
  ensemble: "Weighted ensemble.",
  negbin_bayes: "Bayesian Negative Binomial — short-history shrinkage to M5 priors.",
};

interface Props {
  weights: Record<string, number>;
}

export function EnsembleNarrative({ weights }: Props) {
  const entries = Object.entries(weights)
    .filter(([, w]) => w > 0.001)
    .sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) return null;

  const isEnsemble = entries.length > 1;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-semibold">
        {isEnsemble ? "Forecast model: weighted ensemble" : "Forecast model"}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        {isEnsemble
          ? "Weights set by inverse out-of-fold loss on the recent backtest window."
          : "Single-model forecast (ensemble members fell back when unavailable)."}
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {entries.map(([model, weight]) => (
          <li key={model} className="flex items-baseline gap-2">
            <span className="inline-flex w-12 justify-end font-mono text-xs tabular-nums text-muted-foreground">
              {weight.toFixed(2)}
            </span>
            <span className="text-foreground/85">{MODEL_DESC[model] ?? model}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
