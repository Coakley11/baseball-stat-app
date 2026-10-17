import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";
import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../../../next.config";
import { createDefaultClient } from "./provider";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("data source selection", () => {
  it("defaults to the real Python API", () => {
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "");
    expect(createDefaultClient().source).toBe("api");
  });

  it("uses sample data only when explicitly enabled outside production", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "mock");
    const client = createDefaultClient();
    expect(client.source).toBe("mock");
    // Loads the fixture adapter through the `baseball-sample-data` alias.
    expect((await client.getCatalog()).years.end).toBe(2025);
  });

  it("aliases the sample data to a data-free stub in production builds", () => {
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "");
    expect(nextConfig(PHASE_PRODUCTION_BUILD).turbopack?.resolveAlias).toEqual({ "baseball-sample-data": "./src/lib/api/mock/disabled.ts" });
    expect(nextConfig(PHASE_DEVELOPMENT_SERVER).turbopack?.resolveAlias).toEqual({ "baseball-sample-data": "./src/lib/api/mock/mockClient.ts" });
  });

  it("never uses sample data in production, even if asked", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "mock");
    expect(createDefaultClient().source).toBe("api");
  });

  it("refuses a production build configured for sample data", () => {
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "mock");
    expect(() => nextConfig(PHASE_PRODUCTION_BUILD)).toThrow(/local development only/);
    expect(() => nextConfig(PHASE_DEVELOPMENT_SERVER)).not.toThrow();
    vi.stubEnv("NEXT_PUBLIC_BASEBALL_DATA_SOURCE", "");
    expect(nextConfig(PHASE_PRODUCTION_BUILD).cacheComponents).toBe(true);
  });
});
