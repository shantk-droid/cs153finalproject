"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ShoppingCart,
  TrendingUp,
  Sliders,
  Truck,
  Zap,
  ShieldCheck,
  MessageSquare,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  Icon: LucideIcon;
  shortcut?: string;
}

export function SidebarNav({ datasetId }: { datasetId: string }) {
  const pathname = usePathname();
  const base = `/dashboard/${datasetId}`;
  const items: NavItem[] = [
    { href: `${base}/overview`, label: "Overview", Icon: LayoutDashboard, shortcut: "1" },
    { href: `${base}/reorder`, label: "Reorder Queue", Icon: ShoppingCart, shortcut: "2" },
    { href: `${base}/forecasts`, label: "Forecasts", Icon: TrendingUp, shortcut: "3" },
    { href: `${base}/frontier`, label: "Frontier", Icon: Sliders, shortcut: "4" },
    { href: `${base}/suppliers`, label: "Suppliers", Icon: Truck, shortcut: "5" },
    { href: `${base}/stress`, label: "Stress test", Icon: Zap, shortcut: "6" },
    { href: `${base}/quality`, label: "Data quality", Icon: ShieldCheck, shortcut: "7" },
    { href: `${base}/chat`, label: "Chat", Icon: MessageSquare, shortcut: "8" },
  ];

  return (
    <nav className="flex flex-col gap-0.5 px-2 py-2">
      {items.map(({ href, label, Icon, shortcut }) => {
        const active =
          pathname === href ||
          (pathname?.startsWith(href + "/") ?? false) ||
          (href.endsWith("/overview") &&
            (pathname === base || pathname?.startsWith(`${base}/sku/`)));
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "group flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
              active
                ? "bg-primary/10 font-medium text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1">{label}</span>
            {shortcut && (
              <kbd className="hidden rounded border border-border bg-background px-1 font-mono text-[10px] text-muted-foreground group-hover:inline">
                g {shortcut}
              </kbd>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
