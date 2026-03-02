"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { Sidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";

const PUBLIC_ROUTES = ["/login", "/register"];

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublic = PUBLIC_ROUTES.includes(pathname);

  useEffect(() => {
    if (loading) return;
    if (!user && !isPublic) {
      router.replace("/login");
    }
    if (user && isPublic) {
      router.replace(user.onboarded ? "/" : "/onboarding");
    }
    if (user && !user.onboarded && pathname !== "/onboarding" && !isPublic) {
      router.replace("/onboarding");
    }
  }, [user, loading, isPublic, pathname, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-4 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-[var(--muted-foreground)]">Loading...</p>
        </div>
      </div>
    );
  }

  // Public pages — no shell
  if (isPublic || pathname === "/onboarding") {
    return <>{children}</>;
  }

  // Not logged in — handled by redirect above, show nothing while redirecting
  if (!user) return null;

  // Authenticated layout
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

export function ClientShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>{children}</AuthGate>
    </AuthProvider>
  );
}
