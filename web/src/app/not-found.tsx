import Link from "next/link";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <section style={{ display: "grid", gap: "var(--space-3)", maxWidth: "60ch" }}>
      <h1>This page isn&apos;t here yet</h1>
      <p>
        Only Home, Historical Explorer and Leaderboards have moved to the new Baseball Explorer so far. The other
        tools are still in the current app.
      </p>
      <p>
        <Link href="/">Go to Home</Link>
      </p>
    </section>
  );
}
