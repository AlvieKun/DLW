"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Home,
  BookOpen,
  Map,
  FolderOpen,
  Brain,
  PlusCircle,
  Settings,
  Wrench,
} from "lucide-react";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/session", label: "Study Session", icon: BookOpen },
  { href: "/plan", label: "Your Plan", icon: Map },
  { href: "/portfolio", label: "Learning Journal", icon: FolderOpen },
  { href: "/my-data", label: "Add Study Data", icon: PlusCircle },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex flex-col w-64 border-r border-[var(--border)] bg-[var(--card)]">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-[var(--border)]">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600">
          <Brain className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="text-sm font-bold tracking-tight">Learning Navigator</h1>
          <p className="text-[10px] text-[var(--muted-foreground)] font-medium uppercase tracking-widest">
            Your AI Tutor
          </p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150",
                active
                  ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)]"
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-[var(--border)]">
        <Link
          href="/dev-tools"
          className="flex items-center justify-center gap-1.5 text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
        >
          <Wrench className="w-3 h-3" />
          Developer Tools
        </Link>
      </div>
    </aside>
  );
}
