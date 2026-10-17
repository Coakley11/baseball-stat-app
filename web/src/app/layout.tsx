import type { Metadata, Viewport } from "next";

import { AppShell } from "@/components/shell/AppShell";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Baseball Explorer", template: "%s · Baseball Explorer" },
  description: "Look up players, compare seasons, prepare for your draft and run your fantasy league.",
  icons: { icon: "/brand/dcbe_logo_128.png", apple: "/brand/dcbe_logo_128.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1520" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
