// `baseball-sample-data` is a build alias (next.config.ts, vitest.config.mts): the fixture adapter
// in development and tests, a data-free stub (./disabled.ts) in production builds.
declare module "baseball-sample-data" {
  export { createMockClient } from "@/lib/api/mock/mockClient";
}
