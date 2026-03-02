"use client";

import { cn } from "@/lib/utils";
import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef } from "react";

// ─── Card ───
interface CardProps extends HTMLMotionProps<"div"> {
  gradient?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, gradient, ...props }, ref) => (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5",
        gradient &&
          "bg-gradient-to-br from-[var(--card)] to-[var(--muted)]",
        className
      )}
      {...props}
    />
  )
);
Card.displayName = "Card";

// ─── Badge ───
interface BadgeProps {
  variant?: "default" | "success" | "warning" | "danger" | "info" | "muted";
  children: React.ReactNode;
  className?: string;
}

const BADGE_VARIANTS: Record<string, string> = {
  default:
    "bg-[var(--primary)]/15 text-[var(--primary)] border-[var(--primary)]/30",
  success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  danger: "bg-red-500/15 text-red-400 border-red-500/30",
  info: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  muted:
    "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)]",
};

export function Badge({
  variant = "default",
  children,
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium border",
        BADGE_VARIANTS[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

// ─── Skeleton ───
interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return <div className={cn("skeleton h-4 w-full", className)} />;
}

export function CardSkeleton() {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 space-y-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-3 w-2/3" />
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="h-8 w-1/4 mt-2" />
    </div>
  );
}

// ─── Error Banner ───
interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="ml-4 px-3 py-1 rounded-lg bg-red-500/20 hover:bg-red-500/30 transition-colors text-xs font-medium"
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ─── SampleDataBanner ───
export function SampleDataBanner() {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-400">
      <span className="font-medium">Sample UI Data</span>
      <span className="text-amber-400/70">
        — Layout preview only. Connect backend for real results.
      </span>
    </div>
  );
}

// ─── Section Header ───
interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export function SectionHeader({ title, subtitle, action }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {subtitle && (
          <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
            {subtitle}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

// ─── Stat Card ───
interface StatCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  icon?: React.ReactNode;
  trend?: "up" | "down" | "neutral";
}

export function StatCard({ label, value, sublabel, icon, trend }: StatCardProps) {
  return (
    <Card className="flex items-start gap-4">
      {icon && (
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-[var(--primary)]/10 text-[var(--primary)] shrink-0">
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <p className="text-xs text-[var(--muted-foreground)] font-medium">
          {label}
        </p>
        <p className="text-2xl font-bold tracking-tight mt-0.5">{value}</p>
        {sublabel && (
          <p
            className={cn(
              "text-[11px] mt-0.5 font-medium",
              trend === "up" && "text-emerald-400",
              trend === "down" && "text-red-400",
              (!trend || trend === "neutral") && "text-[var(--muted-foreground)]"
            )}
          >
            {sublabel}
          </p>
        )}
      </div>
    </Card>
  );
}

// ─── Tabs ───
interface TabsProps {
  tabs: string[];
  active: string;
  onChange: (tab: string) => void;
}

export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="flex gap-1 bg-[var(--muted)] rounded-xl p-1">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={cn(
            "px-4 py-1.5 rounded-lg text-xs font-medium transition-all",
            t === active
              ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
