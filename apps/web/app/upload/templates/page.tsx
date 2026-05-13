import Link from "next/link";

export const metadata = {
  title: "ERP CSV templates — Inventory Optimizer",
};

type Template = {
  vendor: string;
  blurb: string;
  required: { col: string; maps_to: string; notes?: string }[];
  optional: { col: string; maps_to: string; notes?: string }[];
  notes: string[];
};

const TEMPLATES: Template[] = [
  {
    vendor: "Shopify",
    blurb: "Auto-detected. Export from Admin → Orders → Export. The system rolls line items into a daily SKU panel automatically.",
    required: [
      { col: "Lineitem sku", maps_to: "sku_id" },
      { col: "Lineitem quantity", maps_to: "demand", notes: "Rolled up by sku × date" },
      { col: "Created at", maps_to: "date", notes: "ISO date with TZ, normalized to UTC midnight" },
      { col: "Financial Status", maps_to: "(filter)", notes: "Rows with cancelled/refunded/voided are dropped" },
    ],
    optional: [
      { col: "Lineitem price", maps_to: "unit_price", notes: "Volume-weighted mean across the day" },
      { col: "Lineitem name", maps_to: "category", notes: "Falls back to product name as a coarse category" },
    ],
    notes: [
      "Returns / refunds with negative quantities are dropped.",
      "Multi-location: line items are summed across all locations (single-location stores unaffected).",
    ],
  },
  {
    vendor: "NetSuite",
    blurb: "Saved search export with item ledger lines. NetSuite's column names vary by saved search; map manually in the column dropdowns.",
    required: [
      { col: "Item / Internal ID", maps_to: "sku_id" },
      { col: "Tran Date", maps_to: "date" },
      { col: "Quantity", maps_to: "demand", notes: "Use positive values; debit memos are returns" },
    ],
    optional: [
      { col: "Item Rate / Item Price", maps_to: "unit_price" },
      { col: "Item Cost / Avg Cost", maps_to: "unit_cost" },
      { col: "Vendor / Preferred Vendor", maps_to: "supplier" },
      { col: "Item Category / Class", maps_to: "category" },
      { col: "Quantity Available", maps_to: "on_hand", notes: "Latest-row snapshot per SKU" },
    ],
    notes: [
      "Run a Saved Search of type 'Transaction' filtered to type=Sales Order, status=Sales Order:Pending Fulfillment or Billed/Closed.",
      "If demand spans multiple subsidiaries, filter to one before exporting — multi-currency rows will fail validation.",
    ],
  },
  {
    vendor: "SAP IM (Inventory Management)",
    blurb: "Transaction MB51 / MB5B for movement history; MM03 for SKU master. SAP IM exports are tab-delimited by default.",
    required: [
      { col: "Material", maps_to: "sku_id", notes: "Use 18-char material number, no prefix zeros" },
      { col: "Pstng Date", maps_to: "date", notes: "DD.MM.YYYY format — system parses this" },
      { col: "Quantity", maps_to: "demand", notes: "Sign convention: outbound 261 movements are demand" },
    ],
    optional: [
      { col: "Unit Price", maps_to: "unit_price" },
      { col: "Moving Avg Price", maps_to: "unit_cost" },
      { col: "Vendor / Supplier", maps_to: "supplier" },
      { col: "Material Group", maps_to: "category" },
      { col: "Unrestricted Use Stock", maps_to: "on_hand", notes: "Latest snapshot from MMBE" },
    ],
    notes: [
      "Filter to a single plant before export — mixing plants violates the panel-per-location assumption.",
      "Convert European decimal commas (1.234,56) to US format (1234.56) before upload — the CSV parser doesn't auto-fix locale.",
    ],
  },
  {
    vendor: "QuickBooks Online — Inventory",
    blurb: "Reports → Inventory Valuation Detail and Sales by Item Detail. QuickBooks exports CSV with header rows the parser auto-skips.",
    required: [
      { col: "Product/Service", maps_to: "sku_id" },
      { col: "Date", maps_to: "date" },
      { col: "Quantity", maps_to: "demand", notes: "Sales rows count as demand; invoice + sales receipt only" },
    ],
    optional: [
      { col: "Rate", maps_to: "unit_price" },
      { col: "Cost", maps_to: "unit_cost" },
      { col: "Vendor", maps_to: "supplier" },
      { col: "Category", maps_to: "category" },
      { col: "Qty On Hand", maps_to: "on_hand", notes: "Snapshot from inventory valuation report" },
    ],
    notes: [
      "QuickBooks ships header text in the first few rows (TOTAL ROW labels, blank rows). The parser scans for the row containing the actual headers — usually row 4-6.",
      "Use the 'Sales by Item Detail' report for demand history, not 'Inventory Valuation' alone.",
    ],
  },
  {
    vendor: "Square POS",
    blurb: "Square Dashboard → Items → Export Items, plus Transactions → Sales → Item Sales for demand history.",
    required: [
      { col: "Item / SKU", maps_to: "sku_id" },
      { col: "Date", maps_to: "date" },
      { col: "Items Sold / Quantity", maps_to: "demand" },
    ],
    optional: [
      { col: "Price", maps_to: "unit_price" },
      { col: "Cost", maps_to: "unit_cost" },
      { col: "Category", maps_to: "category" },
      { col: "Vendor", maps_to: "supplier", notes: "Optional in Square; many small merchants leave blank" },
    ],
    notes: [
      "Square's Item Sales report defaults to one row per item, not one per transaction. That's fine — daily aggregation is what we want.",
      "Variants (size/color) appear as separate items in Square. If you want them collapsed to one SKU, normalize before upload.",
    ],
  },
];

export default function TemplatesPage() {
  return (
    <main className="mx-auto max-w-5xl space-y-8 px-6 py-10">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">CSV templates</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">ERP / POS export reference</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Column shapes for five common sources. Required columns must be present; optional columns
          unlock additional features (inventory math, supplier scorecards). When in doubt, upload
          your file and the column mapper will auto-suggest the right canonical fields.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2 text-xs">
        {TEMPLATES.map((t) => (
          <a
            key={t.vendor}
            href={`#${t.vendor.toLowerCase().replace(/\s+/g, "-")}`}
            className="rounded-full border bg-background px-3 py-1 hover:bg-accent"
          >
            {t.vendor}
          </a>
        ))}
      </nav>

      {TEMPLATES.map((t) => (
        <section
          key={t.vendor}
          id={t.vendor.toLowerCase().replace(/\s+/g, "-")}
          className="space-y-4 rounded-lg border bg-card p-5"
        >
          <header>
            <h2 className="text-xl font-semibold">{t.vendor}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t.blurb}</p>
          </header>

          <div className="overflow-x-auto rounded-md border bg-background">
            <table className="w-full text-xs">
              <thead className="bg-muted/60 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Source column</th>
                  <th className="px-3 py-2 text-left font-medium">Maps to</th>
                  <th className="px-3 py-2 text-left font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {t.required.map((r) => (
                  <tr key={r.col} className="border-t">
                    <td className="px-3 py-1.5 font-mono">{r.col}</td>
                    <td className="px-3 py-1.5 font-mono text-primary">{r.maps_to}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">
                      <span className="mr-1 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">required</span>
                      {r.notes ?? ""}
                    </td>
                  </tr>
                ))}
                {t.optional.map((r) => (
                  <tr key={r.col} className="border-t">
                    <td className="px-3 py-1.5 font-mono">{r.col}</td>
                    <td className="px-3 py-1.5 font-mono text-muted-foreground">{r.maps_to}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{r.notes ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {t.notes.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {t.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
        Ready to try?{" "}
        <Link href="/upload" className="font-medium text-primary underline-offset-4 hover:underline">
          Upload a file →
        </Link>
      </div>
    </main>
  );
}
