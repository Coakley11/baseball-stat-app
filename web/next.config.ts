import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";

type Header = { key: string; value: string };

/**
 * Response headers for every route (pages, the /api/baseball proxy, health routes).
 *
 * CSP: a nonce-based policy would force every page to render dynamically, and Next.js documents
 * that as incompatible with Partial Prerendering (`cacheComponents` / `partialPrefetching`, both
 * on here). So this is the documented nonce-less policy: Next's own inline bootstrap scripts need
 * `'unsafe-inline'`, and everything else stays closed. The browser only ever talks to this origin
 * (the Python API is reached through the server-side proxy), so `connect-src` is `'self'`, and
 * nothing may frame the app or load plugins. `'unsafe-eval'` is for the development server only.
 *
 * HSTS is production-only (browsers ignore it over plain http, so a local `next start` is
 * unaffected) and has no `includeSubDomains`/`preload`, which are commitments for the domain
 * owner to make. Set BASEBALL_WEB_HSTS=off at build time for a production build that is not
 * served over HTTPS. Headers are fixed into the build, so the variable is read at `next build`.
 */
function securityHeaders(development: boolean, env: Record<string, string | undefined> = process.env): Header[] {
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  const headers: Header[] = [
    { key: "Content-Security-Policy", value: csp },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ];
  if (!development && env.BASEBALL_WEB_HSTS?.trim().toLowerCase() !== "off") {
    headers.push({ key: "Strict-Transport-Security", value: "max-age=31536000" });
  }
  return headers;
}

export default function config(phase: string): NextConfig {
  const production = phase === PHASE_PRODUCTION_BUILD;
  const development = phase === PHASE_DEVELOPMENT_SERVER;
  // Sample (fixture) data is for local development only; a production build must use the API.
  if (production && process.env.NEXT_PUBLIC_BASEBALL_DATA_SOURCE === "mock") {
    throw new Error(
      "NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock is for local development only. Unset it to build for production.",
    );
  }
  return {
    async headers() {
      return [{ source: "/:path*", headers: securityHeaders(development) }];
    },
    cacheComponents: true,
    partialPrefetching: true,
    turbopack: {
      // The web app lives in web/ inside the Python repository; keep Turbopack's root here so it
      // never walks the Python tree or picks up a stray lockfile above this folder.
      root: __dirname,
      // The fixture adapter in development; a data-free stub in production, so no sample number
      // is ever emitted into a production build (see lib/api/provider.tsx).
      resolveAlias: {
        "baseball-sample-data": production ? "./src/lib/api/mock/disabled.ts" : "./src/lib/api/mock/mockClient.ts",
      },
    },
  };
}
