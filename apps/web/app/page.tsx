import {
  ArrowDown,
  Box,
  LayoutDashboard,
  LineChart,
  MessageSquare,
  ShieldCheck,
  ShoppingCart,
  Sliders,
  Sparkles,
  Target,
  TrendingUp,
  Truck,
  Zap,
} from "lucide-react";
import { LandingActions } from "@/components/LandingActions";
import { ThemeToggle } from "@/components/ThemeToggle";

interface TabSpec {
  Icon: typeof LayoutDashboard;
  label: string;
  blurb: string;
  details: string[];
}

const TABS: TabSpec[] = [
  {
    Icon: LayoutDashboard,
    label: "Overview",
    blurb:
      "Today's snapshot — KPI tiles, the ABC × XYZ heatmap, working-capital tile, and a heuristic + AI insights panel.",
    details: [
      "Dataset-wide KPIs at the top: revenue, inventory value, days-of-cover.",
      "ABC × XYZ heatmap shows where revenue meets variability.",
      "Insights panel turns raw aggregates into one-line actions (heuristic, with optional Claude enrichment).",
    ],
  },
  {
    Icon: ShoppingCart,
    label: "Reorder Queue",
    blurb:
      "Ranked list of SKUs that need attention — sorted by score = stockout-prob × revenue-at-risk.",
    details: [
      "Each row shows on-hand, reorder point, recommended quantity (rounded to MOQ + case-pack).",
      "Expedite flags fire when the projected stockout date sits inside the lead time.",
      "Joint-replenishment groups are highlighted so you bundle co-supplied SKUs into one PO.",
    ],
  },
  {
    Icon: TrendingUp,
    label: "Forecasts",
    blurb:
      "Per-SKU forecasts with calibrated 95% intervals, click through to a deep dive.",
    details: [
      "Header tiles segment the panel by status: order-now, at-risk, watch, healthy.",
      "Default sort is days-of-cover ascending, filtered to A and B class — what to do today.",
      "Per-SKU page: header block, ensemble breakdown (ETS + Chronos-Bolt + LightGBM), per-horizon conformal coverage, what-if sliders, audit footer.",
    ],
  },
  {
    Icon: Sliders,
    label: "Frontier",
    blurb:
      "Cost-vs-service-level frontier, plus the newsvendor calculator for single-period decisions.",
    details: [
      "Move the service-level slider; see the policy's recommended order quantity, safety stock, and total annual cost track in real time.",
      "Newsvendor calculator (Q*) for perishables: F⁻¹(Cu / (Cu + Co)) on the demand distribution.",
      "Recommended Q (multi-period (s,S)) and Q* (single-period newsvendor) answer different questions — both are surfaced with explainers.",
    ],
  },
  {
    Icon: Truck,
    label: "Suppliers",
    blurb:
      "Scorecards with OTIF, lead-time mean ± std, and a Bayesian posterior that updates from receipts.",
    details: [
      "Lead-time variance, on-time %, in-full %, payment terms, MOQ — all per supplier.",
      "Posterior mean and std come from Gamma updating against actual receipt history.",
      "Insights panel calls out concentration risk and the slowest OTIF supplier by revenue share.",
    ],
  },
  {
    Icon: Zap,
    label: "Stress test",
    blurb:
      "Shock the inputs (lead-time, demand) and watch revenue at risk move.",
    details: [
      "Outputs Δ revenue at risk, VaR 95%, CVaR 95%, count of SKUs over threshold.",
      "Top-impacted table shows base vs shock for stockout %, $ at risk, and recommended Q.",
      "Run before a forecasted disruption (port strike, viral spike) to see who's exposed.",
    ],
  },
  {
    Icon: ShieldCheck,
    label: "Data quality",
    blurb:
      "Composite score over five components, scored against a domain-appropriate reference profile.",
    details: [
      "Completeness, plausibility, history depth, stationarity, distribution profile.",
      "Distribution profile uses a soft-penalty curve against one of five reference profiles (retail M5, e-commerce, B2B, pharma, MRO).",
      "Auto-detect picks the profile from your panel medians; you can swap in Settings.",
    ],
  },
  {
    Icon: MessageSquare,
    label: "Chat",
    blurb:
      "A tool-using Claude agent with structured access to your dataset.",
    details: [
      "Tools: query SKUs, get forecast, run scenario, compute reorder, compare to M5, decompose series.",
      "Streamed via SSE so partial answers render as the agent works.",
      "Cost-capped: 30 requests / minute / IP, with a daily USD budget guard.",
    ],
  },
];

export default function LandingPage() {
  return (
    <>
      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10">
              <Box className="h-4 w-4 text-primary" aria-hidden />
            </div>
            <span className="text-sm font-semibold tracking-tight">Inventory Optimizer</span>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="bg-background">
        <section className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_30%_-10%,hsl(var(--primary)/0.14),transparent_60%)] dark:bg-[radial-gradient(circle_at_30%_-10%,hsl(var(--primary)/0.20),transparent_60%)]" />
          <div className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-b from-card/40 via-background to-background" />
          <div className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-3xl flex-col items-start justify-center gap-8 px-6 py-16">
            <header className="space-y-3">
              <p className="text-sm uppercase tracking-widest text-muted-foreground">
                Inventory Optimizer
              </p>
              <h1 className="text-5xl font-bold tracking-tighter md:text-7xl">
                Demand forecasts, reorder decisions, and supplier scorecards{" "}
                <span className="bg-gradient-to-r from-foreground to-foreground/40 bg-clip-text text-transparent">
                  for any SKU panel.
                </span>
              </h1>
              <p className="max-w-xl text-muted-foreground">
                Drop in a CSV or Excel of SKU sales and get back forecasts with prediction intervals,
                (s,S) recommendations rounded to MOQ, a ranked reorder queue, OTIF supplier
                scorecards with Bayesian lead-time learning, a service-level frontier, stress tests,
                and a tool-using chat — all calibrated against the M5 Walmart dataset.
              </p>
            </header>

            <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
              <div>
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  Reference profiles
                </dt>
                <dd className="mt-0.5 text-base font-semibold tabular-nums">5</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  Workspace tabs
                </dt>
                <dd className="mt-0.5 text-base font-semibold tabular-nums">8</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  Backend tests
                </dt>
                <dd className="mt-0.5 text-base font-semibold tabular-nums">188</dd>
              </div>
            </dl>

            <LandingActions />

            <a
              href="#what-it-does"
              className="mt-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              Scroll for an overview <ArrowDown className="h-4 w-4" aria-hidden />
            </a>
          </div>
        </section>

        <section id="what-it-does" className="border-t bg-card/30">
          <div className="mx-auto max-w-4xl space-y-12 px-6 py-20">
            <header className="space-y-3">
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                What it does
              </p>
              <h2 className="text-3xl font-semibold tracking-tight">
                An ops workspace, not a directory.
              </h2>
              <p className="max-w-2xl text-muted-foreground">
                Most forecasting tools dump a number on you. This app starts with an action queue
                — what needs ordering today, what's at risk in four weeks — and lets you drill in
                when you need to. Every model decision is auditable: ensemble weights, train
                cutoff, and per-horizon conformal coverage are first-class artifacts on every
                forecast.
              </p>
            </header>

            <div className="grid gap-6 md:grid-cols-3">
              <Pillar
                Icon={LineChart}
                tint="bg-blue-500/10 text-blue-700 dark:text-blue-400"
                title="Forecasts you can defend"
                body={
                  <>
                    Weighted ensemble of ETS, Amazon&apos;s Chronos-Bolt, and a global LightGBM
                    model. Weights set by inverse out-of-fold loss. Intervals are
                    split-conformal calibrated, with empirical coverage reported per horizon
                    (h=1 and h=4) on every SKU page.
                  </>
                }
              />
              <Pillar
                Icon={Target}
                tint="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                title="Policies that match the SKU"
                body={
                  <>
                    Stable items get (s, S); perishables get newsvendor; smooth high-volume
                    items get EOQ or (Q, R). Service level is auto-derived from the
                    underage/overage ratio unless you pin it. Schedules are rounded to MOQ and
                    case-pack.
                  </>
                }
              />
              <Pillar
                Icon={ShieldCheck}
                tint="bg-amber-500/10 text-amber-700 dark:text-amber-400"
                title="Honest data quality"
                body={
                  <>
                    Composite score over five components. The distribution-profile component
                    asks &quot;does this look like the kind of data we expect?&quot; — separately
                    from &quot;is your data well-formed?&quot;. Auto-detects retail / e-commerce /
                    B2B / pharma / spare-parts; you can swap.
                  </>
                }
              />
            </div>
          </div>
        </section>

        <section className="border-t">
          <div className="mx-auto max-w-4xl space-y-10 px-6 py-20">
            <header className="space-y-3">
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                Tour the tabs
              </p>
              <h2 className="text-3xl font-semibold tracking-tight">
                Eight surfaces, one workflow.
              </h2>
              <p className="max-w-2xl text-muted-foreground">
                Every dataset opens with the same left-rail navigation. Each tab does one
                thing well; they share the same per-dataset settings and AI insights.
              </p>
            </header>

            <ul className="space-y-6">
              {TABS.map((t) => (
                <li
                  key={t.label}
                  className="flex flex-col gap-2 rounded-lg border bg-card p-5 transition-all hover:-translate-y-0.5 hover:shadow-md sm:flex-row sm:gap-5"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <t.Icon className="h-5 w-5" aria-hidden />
                  </div>
                  <div className="flex-1 space-y-2">
                    <h3 className="text-base font-semibold">{t.label}</h3>
                    <p className="text-sm text-foreground/85">{t.blurb}</p>
                    <ul className="ml-5 list-disc space-y-1 text-sm text-muted-foreground">
                      {t.details.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="border-t bg-card/30">
          <div className="mx-auto max-w-3xl space-y-6 px-6 py-20 text-center">
            <Sparkles className="mx-auto h-8 w-8 text-primary" aria-hidden />
            <h2 className="text-3xl font-semibold tracking-tight">Ready to try it?</h2>
            <p className="text-muted-foreground">
              Upload your panel, or boot a demo in one click. No login required.
            </p>
            <div className="flex justify-center pt-2">
              <LandingActions />
            </div>
            <footer className="pt-12 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Box className="h-3.5 w-3.5" aria-hidden /> v0.2.0 · {new Date().getFullYear()}
              </span>
            </footer>
          </div>
        </section>
      </main>
    </>
  );
}

function Pillar({
  Icon,
  tint,
  title,
  body,
}: {
  Icon: typeof LayoutDashboard;
  tint: string;
  title: string;
  body: React.ReactNode;
}) {
  return (
    <div className="group rounded-lg border bg-card p-5 transition-shadow hover:shadow-md">
      <div className={`mb-3 inline-flex h-9 w-9 items-center justify-center rounded-md ${tint}`}>
        <Icon className="h-4 w-4" aria-hidden />
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-foreground/80">{body}</p>
    </div>
  );
}
