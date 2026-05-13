import Link from "next/link";
import { Box } from "lucide-react";
import { SidebarNav } from "@/components/SidebarNav";
import { CommandPalette } from "@/components/CommandPalette";
import { ThemeToggle } from "@/components/ThemeToggle";
import { serverFetch } from "@/lib/api-server";
import { cn } from "@/lib/utils";
import type { DatasetSummary } from "@/lib/types";

async function getSummary(id: string): Promise<DatasetSummary | null> {
  return serverFetch<DatasetSummary>(`/datasets/${encodeURIComponent(id)}`);
}

interface Props {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}

export default async function DashboardLayout({ children, params }: Props) {
  const { id } = await params;
  const summary = await getSummary(id);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10">
            <Box className="h-4 w-4 text-primary" aria-hidden />
          </div>
          <div className="leading-tight">
            <Link href="/" className="text-sm font-semibold tracking-tight hover:underline">
              Inventory
            </Link>
            <p className="text-[11px] text-muted-foreground">Optimizer</p>
          </div>
        </div>
        <div className="px-4 pb-2 text-[11px] uppercase tracking-widest text-muted-foreground">
          Dataset
        </div>
        <div className="px-4 pb-2">
          <p className="truncate font-mono text-[11px] text-muted-foreground" title={id}>
            {id.slice(0, 8)}…{id.slice(-4)}
          </p>
          {summary && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              {summary.n_skus.toLocaleString()} SKUs · {summary.frequency}
            </p>
          )}
        </div>
        <div className="my-2 border-t" />
        <SidebarNav datasetId={id} />
        <div className="mt-auto px-4 py-3 text-[11px] text-muted-foreground">
          <div className="mb-3 flex items-center justify-between">
            <span>Appearance</span>
            <ThemeToggle />
          </div>
          <div>
            <kbd className="rounded border border-border bg-background px-1 font-mono text-[10px]">
              ⌘K
            </kbd>{" "}
            to search
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <CommandPalette datasetId={id} />
        <div className={cn("flex-1")}>{children}</div>
      </div>
    </div>
  );
}
