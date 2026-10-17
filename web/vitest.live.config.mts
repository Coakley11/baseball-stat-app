import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

// Live integration tests against a running Baseball API (`npm run test:live`).
// Requires BASEBALL_API_ORIGIN, e.g. http://127.0.0.1:8601 for the pinned API in openapi/.
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: "node",
    include: ["src/**/*.live.test.ts"],
    testTimeout: 60_000,
    pool: "threads",
    maxWorkers: 1,
  },
});
