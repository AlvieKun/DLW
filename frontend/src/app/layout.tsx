import type { Metadata } from "next";
import "./globals.css";
import { ClientShell } from "@/components/client-shell";

export const metadata: Metadata = {
  title: "Learning Navigator AI",
  description: "Multi-agent adaptive learning system",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="dark">
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
