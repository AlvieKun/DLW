import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function riskColor(v: number): string {
  if (v >= 0.7) return "text-red-500";
  if (v >= 0.4) return "text-amber-500";
  return "text-emerald-500";
}

export function confidenceBadge(v: number): string {
  if (v >= 0.8) return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  if (v >= 0.5) return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  return "bg-red-500/15 text-red-400 border-red-500/30";
}
