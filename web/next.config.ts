import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // The web app lives in web/ inside the Python repository; keep Turbopack's root here so it
  // never walks the Python tree or picks up a stray lockfile above this folder.
  turbopack: { root: __dirname },
};

export default nextConfig;
