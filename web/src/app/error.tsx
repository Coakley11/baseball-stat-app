"use client";

/**
 * The page-level error boundary: wraps each page inside the app shell, so the navigation stays.
 * It shows a fixed, generic message. The thrown error's message and stack are never rendered
 * (server errors arrive here already redacted to a digest by Next.js, and the digest is the only
 * thing worth quoting to whoever reads the server logs).
 */
export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  const digest = typeof error === "object" && error !== null && "digest" in error ? String((error as { digest?: unknown }).digest ?? "") : "";
  return (
    <section role="alert" style={{ display: "grid", gap: "var(--space-3)", maxWidth: "60ch" }}>
      <h1>Something went wrong</h1>
      <p>This page couldn&apos;t be shown. Nothing you entered was lost or changed. Try again in a moment.</p>
      <p>
        <button type="button" onClick={() => retry()}>
          Try again
        </button>
      </p>
      {digest ? <p style={{ opacity: 0.7, fontSize: "0.85em" }}>Reference: {digest}</p> : null}
    </section>
  );
}
