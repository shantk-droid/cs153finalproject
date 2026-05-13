import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider, THEME_INIT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://web-delta-one-65.vercel.app",
  ),
  title: "Inventory Optimizer",
  description:
    "Demand forecasts, reorder decisions, and supplier scorecards for any SKU panel.",
  openGraph: {
    title: "Inventory Optimizer",
    description:
      "Demand forecasts, reorder decisions, and supplier scorecards for any SKU panel.",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Inventory Optimizer",
    description:
      "Demand forecasts, reorder decisions, and supplier scorecards for any SKU panel.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-background antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
