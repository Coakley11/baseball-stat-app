import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

export default function config(phase: string): NextConfig {
  const production = phase === PHASE_PRODUCTION_BUILD;
  // Sample (fixture) data is for local development only; a production build must use the API.
  if (production && process.env.NEXT_PUBLIC_BASEBALL_DATA_SOURCE === "mock") {
    throw new Error(
      "NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock is for local development only. Unset it to build for production.",
    );
  }
  return {
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
