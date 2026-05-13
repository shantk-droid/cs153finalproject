import { ImageResponse } from "next/og";

export const alt =
  "Inventory Optimizer — demand forecasts, reorder decisions, and supplier scorecards for any SKU panel.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "linear-gradient(135deg, #0a0a0a 0%, #1a1a1d 70%, #2a2a30 100%)",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 80,
          color: "white",
          fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 56,
              height: 56,
              background: "rgba(255,255,255,0.10)",
              border: "1px solid rgba(255,255,255,0.16)",
              borderRadius: 12,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "white",
              fontSize: 26,
              fontWeight: 700,
              letterSpacing: -1.5,
            }}
          >
            IO
          </div>
          <span style={{ fontSize: 28, fontWeight: 600, letterSpacing: -0.5 }}>
            Inventory Optimizer
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <h1
            style={{
              fontSize: 76,
              fontWeight: 700,
              lineHeight: 1.05,
              letterSpacing: -2.5,
              margin: 0,
              maxWidth: 1040,
            }}
          >
            Demand forecasts, reorder decisions, supplier scorecards.
          </h1>
          <p
            style={{
              fontSize: 28,
              color: "rgba(255,255,255,0.6)",
              margin: 0,
              letterSpacing: -0.4,
            }}
          >
            For any SKU panel · Calibrated against M5 Walmart
          </p>
        </div>
      </div>
    ),
    { ...size },
  );
}
