import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Returns a URL on the Next.js /api/* proxy. Server-side it forwards to MODAL_API_URL. */
export function apiUrl(path: string): string {
  const clean = path.startsWith("/") ? path : "/" + path;
  return clean.startsWith("/api/") ? clean : "/api" + clean;
}
