"use client";

/**
 * The last-resort boundary, used when the root layout itself fails. It replaces the whole document,
 * so it brings its own <html>/<body> and no app styles or providers. Fixed generic text only.
 */
export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: "60ch", colorScheme: "light dark" }}>
        <h1>Baseball Explorer is having trouble</h1>
        <p>The page couldn&apos;t be shown. Please try again in a moment.</p>
        <button type="button" onClick={() => retry()}>
          Try again
        </button>
      </body>
    </html>
  );
}
