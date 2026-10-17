import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  // Same alias next.config.ts uses outside production builds.
  resolve: { alias: { "baseball-sample-data": fileURLToPath(new URL("./src/lib/api/mock/mockClient.ts", import.meta.url)) } },
  test: {
    environment: "jsdom",
    // Threads are lighter than forked processes; two workers keep the suite reliable on a busy
    // dev machine (the suite is small, so more workers barely help).
    pool: "threads",
    maxWorkers: 2,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Live tests need a running API: `npm run test:live` (vitest.live.config.mts).
    exclude: ["**/node_modules/**", "src/**/*.live.test.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
});
