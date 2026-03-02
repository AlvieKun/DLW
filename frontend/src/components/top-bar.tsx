"use client";

import { useEffect, useState } from "react";
import { Moon, Sun, Menu, X, Brain, LogOut, User } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";

const NAV_MOBILE = [
  { href: "/", label: "Home" },
  { href: "/session", label: "Study Session" },
  { href: "/plan", label: "Your Plan" },
  { href: "/portfolio", label: "Learning Journal" },
  { href: "/my-data", label: "Add Study Data" },
  { href: "/settings", label: "Settings" },
];

export function TopBar() {
  const [dark, setDark] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const pathname = usePathname();
  const { user, logout } = useAuth();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <>
      <header className="flex items-center justify-between px-6 h-14 border-b border-[var(--border)] bg-[var(--card)] shrink-0">
        {/* Mobile hamburger */}
        <button
          className="md:hidden p-1"
          onClick={() => setMobileOpen(!mobileOpen)}
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>

        {/* Mobile logo */}
        <div className="md:hidden flex items-center gap-2">
          <Brain className="w-5 h-5 text-[var(--primary)]" />
          <span className="font-bold text-sm">Learning Navigator</span>
        </div>

        {/* Spacer for desktop */}
        <div className="hidden md:block" />

        {/* Right actions */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setDark(!dark)}
            className="p-2 rounded-lg hover:bg-[var(--muted)] transition-colors"
            title="Toggle dark mode"
          >
            {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>

          {/* User menu */}
          {user && (
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--muted)] transition-colors"
              >
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xs font-bold">
                  {(user.display_name || user.email)[0].toUpperCase()}
                </div>
                <span className="hidden sm:inline text-sm font-medium max-w-[120px] truncate">
                  {user.display_name || user.email.split("@")[0]}
                </span>
              </button>

              {userMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setUserMenuOpen(false)}
                  />
                  <div className="absolute right-0 top-full mt-1 z-50 w-56 rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg py-1">
                    <div className="px-4 py-2.5 border-b border-[var(--border)]">
                      <p className="text-sm font-medium truncate">
                        {user.display_name || "User"}
                      </p>
                      <p className="text-xs text-[var(--muted-foreground)] truncate">
                        {user.email}
                      </p>
                    </div>
                    <Link
                      href="/settings"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-[var(--muted)] transition-colors"
                    >
                      <User className="w-4 h-4" />
                      Settings
                    </Link>
                    <button
                      onClick={async () => {
                        setUserMenuOpen(false);
                        await logout();
                      }}
                      className="flex items-center gap-2 w-full px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Sign Out
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Mobile nav overlay */}
      {mobileOpen && (
        <div className="md:hidden absolute inset-0 z-50 bg-[var(--background)]/95 backdrop-blur-sm pt-14">
          <nav className="flex flex-col p-4 space-y-1">
            {NAV_MOBILE.map(({ href, label }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "px-4 py-3 rounded-lg text-sm font-medium transition-colors",
                    active
                      ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  )}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>
      )}
    </>
  );
}
