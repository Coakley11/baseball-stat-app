/**
 * What `baseball-sample-data` resolves to in production builds (next.config.ts). It holds no
 * fixtures, so sample numbers can't ship. Unreachable in practice: the provider only imports it
 * outside production, and `next build` refuses NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock.
 */
import type { BaseballClient } from "../client";

export function createMockClient(): BaseballClient {
  throw new Error("Sample data is not available in production builds.");
}
